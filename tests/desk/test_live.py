"""The live engine and its routes, against the random short model."""

from types import SimpleNamespace

import pytest
import torch
from fastapi.testclient import TestClient

from ncm_art.api.app import create_app
from ncm_art.live.engine import LiveEngine
from ncm_art.storage.library import Library
from tests.adapter.tiny_bundle import LEVELS, build_tiny_bundle


class _Tokens:
    pad_token_id = 0
    eos_token_id = 1

    def encode(self, text: str) -> list[int]:
        # One token per character, so a long text overflows the 16-token window.
        return [3 + (len(text) % 5)] * max(1, len(text))

    def decode(self, ids: list[int]) -> str:
        return "x" * len(ids)


@pytest.fixture(scope="module")
def bundle():
    vqvae, generator = build_tiny_bundle()
    return SimpleNamespace(
        vqvae=vqvae,
        generator=generator,
        pre_tokenizer=_Tokens(),
        level0_unigram=torch.ones(16),
        file_hashes={"tokenizer.pt": "t", "generator.pt": "g"},
    )


def _client(tmp_path, bundle):
    def count(text: str) -> dict:
        return {"token_count": len(text), "text_length": 16, "too_long": len(text) > 16, "policy": "test"}

    engine = LiveEngine(loader=lambda: bundle)
    client = TestClient(create_app(Library(tmp_path), token_counter=count, live_engine=engine))
    client.post("/api/v1/projects", json={"title": "Live"})
    return client


def test_engine_loads_lazily_and_reports_failure(tmp_path):
    def broken():
        raise RuntimeError("no checkpoint here")

    engine = LiveEngine(loader=broken)
    assert engine.state()["state"] == "unloaded"
    with pytest.raises(Exception):
        engine.trace("x")
    assert engine.state()["state"] == "unavailable"
    assert "no checkpoint" in engine.state()["message"]


def test_trace_returns_every_pass_and_writes_nothing(tmp_path, bundle):
    client = _client(tmp_path, bundle)
    response = client.post("/api/v1/live/trace", json={"text": "Hello kite"})
    assert response.status_code == 200
    body = response.json()
    assert body["levels"] == LEVELS
    assert len(body["codes"]) == sum(LEVELS)
    assert [frame["level"] for frame in body["frames"]] == list(range(1, 13))
    assert body["token_count"] == 10
    assert client.get("/api/v1/desk").json()["revisions"] == []


def test_vary_can_cut_an_overflowing_text_to_the_window(tmp_path, bundle):
    client = _client(tmp_path, bundle)
    long_text = "y" * 30
    refused = client.post("/api/v1/live/vary", json={"text": long_text, "keep": 6, "seed": 1})
    assert refused.status_code == 409
    assert refused.json()["code"] == "INPUT_TOO_LONG"
    cut = client.post("/api/v1/live/vary", json={"text": long_text, "keep": 6, "seed": 1, "trim": True}).json()
    assert cut["trimmed"] is True
    assert cut["source_text"] == "x" * 16
    assert cut["source_token_count"] == 16
    plain = client.post("/api/v1/live/vary", json={"text": "short", "keep": 6, "seed": 1, "trim": True}).json()
    assert plain["trimmed"] is False and plain["source_text"] == "short"


def test_vary_keeps_the_prefix_and_marks_only_sampled_codes(tmp_path, bundle):
    client = _client(tmp_path, bundle)
    trace = client.post("/api/v1/live/trace", json={"text": "Hello kite"}).json()
    varied = client.post("/api/v1/live/vary", json={"codes": trace["codes"], "keep": 4, "seed": 7}).json()
    prefix = sum(LEVELS[:4])
    assert varied["codes"][:prefix] == trace["codes"][:prefix]
    assert set(varied["changed"][:prefix]) == {"0"}
    assert varied["keep"] == 4 and varied["seed"] == 7
    assert varied["prediction_count"] == 8
    again = client.post("/api/v1/live/vary", json={"codes": trace["codes"], "keep": 4, "seed": 7}).json()
    assert again["codes"] == varied["codes"]

    exact = client.post("/api/v1/live/vary", json={"codes": trace["codes"], "keep": 12}).json()
    assert exact["codes"] == trace["codes"] and exact["prediction_count"] == 0

    fresh = client.post("/api/v1/live/vary", json={"text": "Hello kite", "keep": 0, "seed": 1}).json()
    assert fresh["prediction_count"] == 11
    assert fresh["source_token_count"] == 10
    assert len(fresh["source_padded_token_ids"]) == 16

    bad = client.post("/api/v1/live/vary", json={"codes": trace["codes"], "keep": 13})
    assert bad.status_code == 400


def test_keep_commits_the_source_and_the_variation_with_provenance(tmp_path, bundle):
    client = _client(tmp_path, bundle)
    trace = client.post("/api/v1/live/trace", json={"text": "Hello kite"}).json()
    varied = client.post("/api/v1/live/vary", json={"codes": trace["codes"], "keep": 5, "seed": 3}).json()
    kept = client.post(
        "/api/v1/live/keep",
        json={
            "source_text": "Hello kite",
            "source_codes": trace["codes"],
            "source_padded_token_ids": trace["padded_token_ids"],
            "source_token_count": trace["token_count"],
            "variation": {k: varied[k] for k in ("text", "codes", "raw_token_ids", "keep", "seed", "sampling")},
        },
    )
    assert kept.status_code == 200
    revision = kept.json()
    assert revision["origin_kind"] == "generated"
    assert revision["parents"][0]["relationship"] == "generated_from"
    desk = client.get("/api/v1/desk").json()
    kinds = sorted(item["origin_kind"] for item in desk["revisions"])
    assert kinds == ["authored", "generated"]
    assert desk["draft"]["text"] == "Hello kite"
    history = client.get(f"/api/v1/passages/{revision['id']}/history").json()
    assert history["run"]["parameters"]["retained_level_count"] == 5
    assert history["run"]["parameters"]["base_seed"] == 3
    assert history["run"]["operation"] == "live_vary"


def test_keep_frame_records_a_decoded_passage(tmp_path, bundle):
    client = _client(tmp_path, bundle)
    trace = client.post("/api/v1/live/trace", json={"text": "Hello kite"}).json()
    frame = trace["frames"][2]
    kept = client.post(
        "/api/v1/live/keep-frame",
        json={
            "source_text": "Hello kite",
            "source_codes": trace["codes"],
            "source_padded_token_ids": trace["padded_token_ids"],
            "source_token_count": trace["token_count"],
            "level": frame["level"],
            "text": frame["text"],
            "raw_token_ids": frame["raw_token_ids"],
        },
    ).json()
    assert kept["origin_kind"] == "decoded"
    assert kept["parents"][0]["relationship"] == "decoded_from"


def test_keep_run_chains_tellings_and_rejects_a_broken_chain(tmp_path, bundle):
    client = _client(tmp_path, bundle)
    source = "Hello kite"
    current = source
    steps = []
    for index in range(3):
        varied = client.post("/api/v1/live/vary", json={"text": current, "keep": 6, "seed": 10 + index}).json()
        steps.append(
            {
                "reset": index == 2,
                "input_text": source if index == 2 else current,
                "input_codes": varied["source_codes"],
                "input_padded_token_ids": varied["source_padded_token_ids"],
                "input_token_count": varied["source_token_count"],
                "variation": {k: varied[k] for k in ("text", "codes", "raw_token_ids", "keep", "seed", "sampling")},
            }
        )
        current = source if index == 2 else varied["text"]
    # Telling 3 was told from the source again, so its recorded input must be the source.
    steps[2]["input_text"] = source
    kept = client.post("/api/v1/live/keep-run", json={"source_text": source, "keep": 6, "steps": steps})
    assert kept.status_code == 200, kept.text
    tellings = kept.json()["tellings"]
    assert len(tellings) == 3
    first = client.get(f"/api/v1/passages/{tellings[0]['revision_id']}/history").json()
    second = client.get(f"/api/v1/passages/{tellings[1]['revision_id']}/history").json()
    third = client.get(f"/api/v1/passages/{tellings[2]['revision_id']}/history").json()
    assert first["revision"]["parents"][0]["parent_id"] == kept.json()["source_revision_id"]
    assert second["revision"]["parents"][0]["parent_id"] == tellings[0]["revision_id"]
    assert third["revision"]["parents"][0]["parent_id"] == kept.json()["source_revision_id"]
    assert second["run"]["parameters"]["operation"] == "weather"
    assert second["run"]["parameters"]["step"] == 1

    steps[1]["input_text"] = "something else"
    broken = client.post("/api/v1/live/keep-run", json={"source_text": source, "keep": 6, "steps": steps})
    assert broken.status_code == 409
    assert broken.json()["code"] == "STALE_RUN"


def test_keep_run_records_a_cut_telling_as_its_own_revision(tmp_path, bundle):
    client = _client(tmp_path, bundle)
    source = "Hello kite"
    first = client.post("/api/v1/live/vary", json={"text": source, "keep": 6, "seed": 1}).json()
    # The tiny decoder returns one character per token, so the first telling is 16 characters and the
    # second input would overflow if the decoder had produced more. Simulate a longer telling.
    long_telling = first["text"] + "yyyyyyyy"
    second = client.post("/api/v1/live/vary", json={"text": long_telling, "keep": 6, "seed": 2, "trim": True}).json()
    assert second["trimmed"] is True
    steps = [
        {
            "reset": False,
            "input_text": source,
            "input_codes": first["source_codes"],
            "input_padded_token_ids": first["source_padded_token_ids"],
            "input_token_count": first["source_token_count"],
            "variation": {**{k: first[k] for k in ("codes", "raw_token_ids", "keep", "seed", "sampling")}, "text": long_telling},
        },
        {
            "reset": False,
            "trimmed": True,
            "input_text": second["source_text"],
            "input_codes": second["source_codes"],
            "input_padded_token_ids": second["source_padded_token_ids"],
            "input_token_count": second["source_token_count"],
            "variation": {k: second[k] for k in ("text", "codes", "raw_token_ids", "keep", "seed", "sampling")},
        },
    ]
    kept = client.post("/api/v1/live/keep-run", json={"source_text": source, "keep": 6, "steps": steps})
    assert kept.status_code == 200, kept.text
    tellings = kept.json()["tellings"]
    second_history = client.get(f"/api/v1/passages/{tellings[1]['revision_id']}/history").json()
    cut_id = second_history["revision"]["parents"][0]["parent_id"]
    cut = client.get(f"/api/v1/passages/{cut_id}/history").json()["revision"]
    assert cut["origin_kind"] == "edited"
    assert cut["parents"][0]["relationship"] == "trimmed_from"
    assert cut["parents"][0]["parent_id"] == tellings[0]["revision_id"]
    assert cut["text"] == second["source_text"]
