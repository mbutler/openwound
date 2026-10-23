"""Job execution against the random short model, not the released checkpoint."""

from types import SimpleNamespace

import pytest
import torch

from ncm_art.jobs.execute import execute_job
from ncm_art.storage.library import Library
from tests.adapter.tiny_bundle import build_tiny_bundle


class _Tokens:
    pad_token_id = 0
    eos_token_id = 1

    def encode(self, text: str) -> list[int]:
        return [3] * max(1, min(len(text), 8))

    def decode(self, ids: list[int]) -> str:
        return "out:" + ",".join(str(token) for token in ids[:12])


@pytest.fixture(scope="module")
def bundle():
    vqvae, generator = build_tiny_bundle()
    return SimpleNamespace(
        vqvae=vqvae,
        generator=generator,
        pre_tokenizer=_Tokens(),
        level0_unigram=torch.ones(16),
        file_hashes={},
    )


def _prepared(tmp_path, text="Hello kite"):
    project = Library(tmp_path).create_project("Desk")
    project.set_draft(text)
    revision = project.ensure_input_revision()
    return project, revision


def test_reconstruction_keeps_the_draft_and_records_twelve_frames(tmp_path, bundle):
    project, revision = _prepared(tmp_path)
    job = project.submit_job("reconstruct", {"passage_revision_id": revision["id"]}, "reconstruct-1")
    execute_job(project, bundle, project.claim_next_job())
    finished = project.job(job["id"])
    assert finished["state"] == "succeeded"
    assert len(finished["result"]["frames"]) == 12
    assert [frame["level"] for frame in finished["result"]["frames"]] == list(range(1, 13))
    assert project.draft()["text"] == "Hello kite"
    assert project.selected_revision_id() == revision["id"]
    decoded = [item for item in project.revisions() if item["origin_kind"] == "decoded"]
    assert len(decoded) == 12
    assert decoded[0]["parents"][0]["relationship"] == "decoded_from"
    assert decoded[0]["parents"][0]["parent_id"] == revision["id"]


def test_cancel_keeps_the_candidates_already_written(tmp_path, bundle):
    project, revision = _prepared(tmp_path)
    recipe = {
        "passage_revision_id": revision["id"],
        "retained_level_count": 3,
        "candidate_count": 4,
        "sampling": {"temperature": 1.0, "top_k": 0, "top_p": 1.0},
        "base_seed": 42,
    }
    job = project.submit_job("variants", recipe, "vary-1")

    def cancel_on_second(index: int) -> None:
        if index == 1:
            project.set_draft("still writing")
            project.cancel(job["id"])

    execute_job(project, bundle, project.claim_next_job(), before_candidate=cancel_on_second)
    finished = project.job(job["id"])
    assert finished["state"] == "cancelled"
    assert len(finished["result"]["candidates"]) == 1
    assert finished["result"]["candidates"][0]["seed"] == 42
    assert project.draft()["text"] == "still writing"
    assert project.selected_revision_id() == revision["id"]
    generated = [item for item in project.revisions() if item["origin_kind"] == "generated"]
    assert len(generated) == 1
    assert generated[0]["parents"][0]["relationship"] == "generated_from"


def test_two_candidates_use_distinct_stored_seeds(tmp_path, bundle):
    project, revision = _prepared(tmp_path, "A short passage")
    recipe = {
        "passage_revision_id": revision["id"],
        "retained_level_count": 12,
        "candidate_count": 2,
        "sampling": {"temperature": 0.0, "top_k": 0, "top_p": 1.0},
        "base_seed": 7,
    }
    job = project.submit_job("variants", recipe, "vary-full")
    execute_job(project, bundle, project.claim_next_job())
    finished = project.job(job["id"])
    assert finished["state"] == "succeeded"
    seeds = [item["seed"] for item in finished["result"]["candidates"]]
    assert seeds[0] == 7
    assert seeds[1] != seeds[0]
    assert all(item["prediction_count"] == 0 for item in finished["result"]["candidates"])
