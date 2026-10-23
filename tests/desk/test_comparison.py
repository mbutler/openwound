"""Agreement arithmetic stays independent of the model."""

import json

import pytest
import torch

from ncm_art.comparison.agreement import (
    PREPROCESSING,
    adjust,
    diagnose_baseline,
    prefix_agreement,
    require_compatible,
)
from ncm_art.comparison.jobs import queue_graft
from ncm_art.comparison.service import compare_hierarchies
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.tinystories import apply_graft
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library
from ncm_art.storage.migrate import write_manifest

LEVELS = [2, 2]
SIZES = [16, 16]


def _project(tmp_path):
    library = Library(tmp_path)
    project = library.create_project("Codes")
    library.open_project(project.manifest()["id"])
    return library, project


def _encoding(project, text, codes, fingerprint="tokenizer-a", token_count=4, family=None, policy=PREPROCESSING):
    revision = project.commit_text(text, "imported")
    _run, representation_id = project.save_source_run(
        operation="encode_corpus",
        passage_revision_id=revision["id"],
        parameters={
            "preprocessing_policy": policy,
            "source_title": text,
            "family_id": family,
            "token_count": token_count,
        },
        token_count=token_count,
        codes=codes,
        padded_token_ids=[1, 2, 3, 0],
        level_lengths=LEVELS,
        codebook_sizes=SIZES,
        model_profile="tinystories-v1",
        execution_profile="cpu-fp32-eager-v1",
        tokenizer_fingerprint=fingerprint,
        generator_fingerprint="generator-a",
        display_policy=None,
    )
    return representation_id


def test_zero_retained_levels_are_undefined():
    with pytest.raises(ProjectError) as caught:
        prefix_agreement([1, 1, 1, 1], [1, 1, 1, 1], LEVELS, 0)
    assert caught.value.code == "COMPARISON_UNDEFINED"


def test_equal_prefix_agreement_is_exact():
    score = prefix_agreement([1, 2, 3, 4], [1, 2, 9, 9], LEVELS, 1)
    assert score["agreement"] == 1
    assert score["shared_prefix"] is True
    wider = prefix_agreement([1, 2, 3, 4], [1, 2, 9, 9], LEVELS, 2)
    assert wider["agreement"] == 1 / 2
    assert wider["shared_prefix"] is False


def test_same_dimensions_with_another_tokenizer_are_incompatible():
    left = {
        "tokenizer_fingerprint": "tokenizer-a",
        "model_profile": "tinystories-v1",
        "preprocessing_policy": PREPROCESSING,
        "level_lengths": LEVELS,
        "codebook_sizes": SIZES,
    }
    right = dict(left)
    right["tokenizer_fingerprint"] = "tokenizer-b"
    with pytest.raises(ProjectError) as caught:
        require_compatible(left, right)
    assert caught.value.code == "PROFILE_MISMATCH"


def test_a_unanimous_baseline_is_degenerate_and_a_small_one_can_be_negative():
    unanimous = diagnose_baseline([[7, 7, 7, 7], [7, 7, 7, 7]], LEVELS, 2)
    assert unanimous["state"] == "degenerate"
    assert unanimous["value"] == 1
    assert adjust(prefix_agreement([7, 7, 7, 7], [1, 1, 1, 1], LEVELS, 2)["agreement"], unanimous["value"], unanimous["state"]) is None

    population = [[1, 1, 0, 0], [1, 0, 0, 0], [2, 0, 0, 0]]
    sparse = diagnose_baseline(population, LEVELS, 2)
    assert sparse["state"] == "sparse"
    assert sparse["count"] == 3
    adjusted = adjust(prefix_agreement([0, 0, 0, 0], [1, 1, 0, 0], LEVELS, 2)["agreement"], sparse["value"], sparse["state"])
    assert adjusted == -1 / 2
    empty = diagnose_baseline([[1, 1, 1, 1]], LEVELS, 1)
    assert empty["state"] == "unavailable"


def test_saved_comparison_keeps_raw_agreement_when_the_baseline_is_sparse(tmp_path):
    _library, project = _project(tmp_path)
    query = _encoding(project, "query passage", [0, 0, 0, 0])
    _encoding(project, "other alpha", [1, 1, 0, 0])
    _encoding(project, "other beta", [1, 0, 0, 0])
    _encoding(project, "other gamma", [2, 0, 0, 0])
    _encoding(project, "other layout", [0, 0, 0, 0], fingerprint="tokenizer-b")
    with pytest.raises(ProjectError) as undefined:
        compare_hierarchies(project, query, 0)
    assert undefined.value.code == "COMPARISON_UNDEFINED"

    compared = compare_hierarchies(project, query, 2)
    assert compared["baseline"]["state"] == "sparse"
    assert compared["snapshot"]["excluded"]["incompatible"] == 1
    alpha = next(pair for pair in compared["pairs"] if pair["title"] == "other alpha")
    assert alpha["agreement"] == 0.5
    assert alpha["adjusted"] == pytest.approx(-0.5)
    assert all(pair["title"] != "other layout" for pair in compared["pairs"])

    same = _encoding(project, "matching one", [4, 4, 4, 4], token_count=20)
    _encoding(project, "matching two", [4, 4, 4, 4], token_count=20)
    _encoding(project, "matching three", [4, 4, 4, 4], token_count=20)
    degenerate = compare_hierarchies(project, same, 2)
    assert degenerate["baseline"]["state"] == "degenerate"
    twin = next(pair for pair in degenerate["pairs"] if pair["title"] == "matching two")
    assert twin["agreement"] == 1
    assert twin["shared_prefix"] is True
    assert twin["adjusted"] is None
    assert "follows from the codes" in twin["note"]


def test_a_graft_rejects_duplicates_boundaries_and_codes_that_already_agree(tmp_path):
    base = torch.tensor([[1, 1, 1, 1]], dtype=torch.long)
    donor = torch.tensor([[2, 3, 4, 5]], dtype=torch.long)
    with pytest.raises(AdapterError) as duplicate:
        apply_graft(base, donor, [(0, 0), (0, 0)], 1, LEVELS, SIZES)
    assert "already" in duplicate.value.message
    with pytest.raises(AdapterError) as boundary:
        apply_graft(base, donor, [(1, 0)], 1, LEVELS, SIZES)
    assert boundary.value.code == "INVALID_SAMPLING"
    unchanged = apply_graft(base, base, [(0, 1)], 1, LEVELS, SIZES)
    assert not unchanged.changed
    assert torch.equal(unchanged.codes, base)

    _library, project = _project(tmp_path)
    base_id = _encoding(project, "base passage", [1, 1, 1, 1])
    donor_id = _encoding(project, "donor passage", [1, 1, 4, 5])
    quiet = queue_graft(project, base_id, donor_id, 1, None, "graft-quiet")
    assert quiet["changed"] is False
    assert quiet["message"] == "Those codes already agree. Nothing was generated."
    assert project.active_job() is None
    with pytest.raises(ProjectError) as repeated:
        queue_graft(project, base_id, donor_id, 2, [{"level_index": 0, "position": 0}, {"level_index": 0, "position": 0}], "graft-repeat")
    assert "already" in repeated.value.message
    with pytest.raises(ProjectError) as too_deep:
        queue_graft(project, base_id, donor_id, 1, [{"level_index": 1, "position": 0}], "graft-deep")
    assert "retained_level_count" in too_deep.value.message
    foreign = _encoding(project, "foreign passage", [1, 1, 1, 1], fingerprint="tokenizer-b")
    with pytest.raises(ProjectError) as mismatch:
        queue_graft(project, base_id, foreign, 1, [{"level_index": 0, "position": 0}], "graft-foreign")
    assert mismatch.value.code == "PROFILE_MISMATCH"


def test_a_corpus_encoding_stays_off_the_desk_and_format_4_opens(tmp_path):
    library, project = _project(tmp_path)
    hidden = project.commit_text("Encoded window.", "corpus_encoding")
    assert hidden["id"] not in {item["id"] for item in project.revisions()}
    assert project.revision(hidden["id"])["text"] == "Encoded window."
    assert project.draft()["text"] == ""

    with project._conn() as conn:
        conn.execute("DROP TABLE code_comparison_pair")
        conn.execute("DROP TABLE code_comparison")
        conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
    manifest = project.manifest()
    manifest["format_version"] = 4
    write_manifest(project.root, manifest)
    reopened = library.project(manifest["id"])
    assert reopened.schema_version() == 5
    assert (reopened.root / "backups" / "schema-4" / "complete").is_file()
    with reopened._conn() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "code_comparison" in tables
    assert json.loads((reopened.root / "backups" / "schema-4" / "project.json").read_text(encoding="utf-8"))["format_version"] == 4
