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
    encoding = project.representation(finished["result"]["encoding_id"])
    assert encoding["kind"] == "source_encoding"
    assert encoding["token_count"] > 0
    assert encoding["padded_token_ids"]
    assert sum(encoding["level_lengths"]) == len(encoding["codes"])
    assert encoding["hierarchy_available"] is True


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
    kept = project.sampled_hierarchy(generated[0]["id"])
    assert kept["hierarchy_available"] is True
    assert kept["token_count"] is None
    assert kept["raw_token_ids"]


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
    hierarchies = [project.sampled_hierarchy(item["revision_id"]) for item in finished["result"]["candidates"]]
    assert hierarchies[0]["seed"] == seeds[0]
    assert hierarchies[1]["seed"] == seeds[1]
    assert hierarchies[0]["source_representation_id"] == hierarchies[1]["source_representation_id"]
    assert hierarchies[0]["id"] != hierarchies[1]["id"]
    assert all(item["token_count"] is None and item["padded_token_ids"] is None for item in hierarchies)


def test_reencoding_edited_text_leaves_the_sampled_hierarchy(tmp_path, bundle):
    project, revision = _prepared(tmp_path, "A short passage")
    recipe = {
        "passage_revision_id": revision["id"],
        "retained_level_count": 3,
        "candidate_count": 1,
        "sampling": {"temperature": 1.0, "top_k": 0, "top_p": 1.0},
        "base_seed": 11,
    }
    job = project.submit_job("variants", recipe, "vary-keep")
    execute_job(project, bundle, project.claim_next_job())
    candidate = project.job(job["id"])["result"]["candidates"][0]
    sampled = project.sampled_hierarchy(candidate["revision_id"])
    original_id = sampled["id"]
    original_codes = list(sampled["codes"])
    assert sampled["kind"] == "sampled_hierarchy"
    assert sampled["raw_token_ids"]
    source = project.representation(sampled["source_representation_id"])
    assert source["kind"] == "source_encoding"
    assert source["passage_revision_id"] == revision["id"]

    project.select(candidate["revision_id"])
    project.set_draft(candidate["text"] + " more")
    edited = project.ensure_input_revision()
    reencode = project.submit_job("reconstruct", {"passage_revision_id": edited["id"]}, "reencode")
    execute_job(project, bundle, project.claim_next_job())
    assert project.job(reencode["id"])["state"] == "succeeded"

    again = project.sampled_hierarchy(candidate["revision_id"])
    assert again["id"] == original_id
    assert again["codes"] == original_codes
    child = project.representations_for(edited["id"])
    assert [item["kind"] for item in child] == ["source_encoding"]
    assert child[0]["id"] != original_id
    assert child[0]["token_count"] is not None
