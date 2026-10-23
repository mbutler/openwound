"""A project archive round-trips history without replaying it."""

import base64
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from ncm_art.api.app import create_app
from ncm_art.corpus.sources import import_bytes
from ncm_art.exports.archive import export_project_archive, export_work_text, import_project_archive
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library
from ncm_art.works.service import (
    bind_influence,
    commit_prepared_application,
    create_influence,
    create_work,
    get_work,
    preview_return,
    preview_transfer,
)


def _project(tmp_path, title="Letters"):
    library = Library(tmp_path)
    project = library.create_project(title)
    library.open_project(project.manifest()["id"])
    return library, project


def _commit(project, work_id, preview, request_id):
    return commit_prepared_application(
        project,
        project.manifest()["id"],
        work_id,
        request_id,
        preview["id"],
        preview["candidate_id"],
        preview["work_state_version"],
    )


def test_export_and_import_keep_a_held_name_returnable(tmp_path):
    library, project = _project(tmp_path)
    source = b"\xef\xbb\xbfMara crossed the river.\r\nMara waved. \xf0\x9f\x8c\x8a"
    imported = import_bytes(project, source, title="River", filename="river.txt", budgets=[])
    assert project.read_asset_bytes(imported["text_sha256"]) == source
    work = create_work(project, "Crossing")
    donor = {
        "owner_kind": "source_version",
        "owner_id": imported["id"],
        "start_byte": 3,
        "end_byte": 3 + len("Mara crossed the river.".encode()),
    }
    marked = {"start_byte": 3, "end_byte": 7}
    version = create_influence(
        project,
        "What crosses must leave its name behind.",
        "Identity is displaced when this material enters the work.",
        template="withhold_marked_span_v1",
        parameters={"mark_role": "name", "replacement_text": "_____"},
    )
    bound = bind_influence(project, work["id"], version["id"], work["state_version"])
    preview = preview_transfer(project, work["id"], 0, donor, marked)
    _commit(project, work["id"], preview, "hold")
    project.set_draft("desk draft")
    project.submit_job("reconstruct", {"passage_revision_id": "not-run"}, "queued-export")
    with project._conn() as conn:
        conn.execute(
            """INSERT INTO embedding(id, fragment_id, input_sha256, profile_fingerprint, dimension, normalized, vector_json, created_at)
               VALUES ('embed-1', 'fragment', 'abc', 'profile', 3, 1, '[1,0,0]', 'now')"""
        )
    archive = export_project_archive(project)
    assert project.active_job() is not None

    other = Library(tmp_path / "imported")
    other.create_project("Crossing")
    restored = import_project_archive(other, archive)
    assert restored.manifest()["id"] != project.manifest()["id"]
    assert restored.manifest()["copied_from_project_id"] == project.manifest()["id"]
    assert restored.manifest()["title"] == "Letters"
    assert len(other.list_projects()) == 2
    loaded = get_work(restored, get_work(project, work["id"])["id"])
    assert loaded["entries"][0]["text"] == "_____ crossed the river."
    assert loaded["held_names"][0]["text"] == "Mara"
    assert loaded["held_names"][0]["status"] == "held"
    assert restored.read_asset_bytes(imported["text_sha256"]) == source
    assert restored.active_job() is None
    interrupted = restored.job(project.latest_job()["id"])
    assert interrupted["state"] == "interrupted"
    with restored._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM embedding").fetchone()[0] == 0
    returned = preview_return(restored, loaded["id"], loaded["held_names"][0]["id"], loaded["state_version"])
    _commit(restored, loaded["id"], returned, "return-after-import")
    assert get_work(restored, loaded["id"])["entries"][0]["text"] == "Mara crossed the river."
    assert restored.draft()["text"] == "desk draft"

    plain = export_work_text(project, work["id"], "markdown", appendix=False)
    assert plain.startswith("# Crossing\n")
    assert "_____ crossed the river." in plain
    assert "Held names" not in plain
    documented = export_work_text(project, work["id"], "markdown", appendix=True)
    assert "River" in documented
    assert "Mara — held from River" in documented


def test_a_corrupt_archive_is_rejected(tmp_path):
    library, project = _project(tmp_path)
    create_work(project, "Crossing")
    archive = export_project_archive(project)
    other = Library(tmp_path / "other")

    with pytest.raises(ProjectError):
        import_project_archive(other, b"not a zip")

    slipped = io.BytesIO()
    with zipfile.ZipFile(slipped, "w") as package:
        package.writestr("../outside.txt", b"no")
        package.writestr("export.json", b"{}")
    with pytest.raises(ProjectError) as caught:
        import_project_archive(other, slipped.getvalue())
    assert "unsafe" in caught.value.message

    broken = zipfile.ZipFile(io.BytesIO(archive))
    rewritten = io.BytesIO()
    with zipfile.ZipFile(rewritten, "w") as package:
        for info in broken.infolist():
            payload = broken.read(info.filename)
            if info.filename == "project.json":
                payload = payload.replace(b"Letters", b"Letterz")
            package.writestr(info.filename, payload)
    with pytest.raises(ProjectError) as mismatch:
        import_project_archive(other, rewritten.getvalue())
    assert "hash" in mismatch.value.message
    assert other.list_projects() == []

    client = TestClient(create_app(library))
    response = client.post(
        "/api/v1/projects/import",
        json={"content_base64": base64.b64encode(archive).decode("ascii")},
    )
    assert response.status_code == 200
    assert response.json()["copied_from_project_id"] == project.manifest()["id"]
    assert response.json()["id"] != project.manifest()["id"]
