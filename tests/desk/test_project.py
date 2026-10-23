"""Saving, reopening, and editing a project without a model."""

import pytest

from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library


def test_reopen_keeps_exact_text_and_the_draft(tmp_path):
    library = Library(tmp_path)
    project = library.create_project("Kite")
    library.open_project(project.manifest()["id"])
    text = "Hello\n  kite  \u2014"
    project.set_draft(text)
    revision = project.ensure_input_revision()
    assert revision["text"] == text
    assert revision["origin_kind"] == "authored"

    reopened = Library(tmp_path).open_project(project.manifest()["id"])
    assert reopened.revision(revision["id"])["text"] == text
    assert reopened.draft()["text"] == text
    assert reopened.selected_revision_id() == revision["id"]


def test_an_edit_leaves_the_original_in_place(tmp_path):
    project = Library(tmp_path).create_project("Kite")
    project.set_draft("Anna borrowed a kite.")
    original = project.ensure_input_revision()
    project.set_draft("Ben borrowed a kite.")
    edited = project.ensure_input_revision()
    assert edited["origin_kind"] == "edited"
    assert edited["parents"][0]["relationship"] == "edited_from"
    assert edited["parents"][0]["parent_id"] == original["id"]
    assert project.revision(original["id"])["text"] == "Anna borrowed a kite."

    project.select(original["id"])
    assert project.draft()["text"] == "Anna borrowed a kite."
    assert project.revision(edited["id"])["text"] == "Ben borrowed a kite."


def test_repeated_request_id_returns_the_same_job(tmp_path):
    project = Library(tmp_path).create_project("Kite")
    project.set_draft("Hello")
    revision = project.ensure_input_revision()
    recipe = {"passage_revision_id": revision["id"], "candidate_count": 4}
    first = project.submit_job("variants", recipe, "same-id")
    second = project.submit_job("variants", recipe, "same-id")
    assert second["id"] == first["id"]
    with pytest.raises(ProjectError) as conflict:
        project.submit_job("variants", {"passage_revision_id": revision["id"], "candidate_count": 1}, "same-id")
    assert conflict.value.code == "CONFLICT"


def test_a_note_is_tied_to_the_revision_text(tmp_path):
    project = Library(tmp_path).create_project("Kite")
    project.set_draft("Hello")
    revision = project.ensure_input_revision()
    note = project.add_annotation(revision["id"], "note", "Keep the kite.")
    assert note["text_sha256"] == revision["text_sha256"]
    assert project.annotations(revision["id"])[0]["value"] == "Keep the kite."
