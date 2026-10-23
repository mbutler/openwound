"""Ordered works, bound transfer, and the held-name index."""

import pytest
from fastapi.testclient import TestClient

from ncm_art.api.app import create_app
from ncm_art.corpus.sources import import_bytes
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library
from ncm_art.works.service import (
    CHANGED,
    bind_influence,
    commit_prepared_application,
    create_influence,
    create_work,
    edit_entry,
    get_work,
    preview_protected_insert,
    preview_return,
    preview_transfer,
    remove_entry,
    reorder_entries,
    retarget_held_name,
    unbind_influence,
)


def _project(tmp_path):
    library = Library(tmp_path)
    project = library.create_project("Letters")
    library.open_project(project.manifest()["id"])
    return library, project


def _donor(project, text: str, title: str = "River") -> dict:
    imported = import_bytes(project, text.encode("utf-8"), title=title, budgets=[])
    return {
        "owner_kind": "source_version",
        "owner_id": imported["id"],
        "start_byte": 0,
        "end_byte": len(text.encode("utf-8")),
        "text_sha256": imported["text_sha256"],
    }


def _mark(text: str, needle: str, occurrence: int = 0) -> dict:
    raw = text.encode("utf-8")
    encoded = needle.encode("utf-8")
    start = -1
    for _index in range(occurrence + 1):
        start = raw.find(encoded, start + 1)
    assert start >= 0
    return {"start_byte": start, "end_byte": start + len(encoded)}


def _influence(project, work: dict) -> dict:
    version = create_influence(
        project,
        "What crosses must leave its name behind.",
        "Identity is displaced when this material enters the work.",
        template="withhold_marked_span_v1",
        parameters={"mark_role": "name", "replacement_text": "_____"},
    )
    return bind_influence(project, work["id"], version["id"], work["state_version"])


def _commit(project, work_id: str, preview: dict, request_id: str) -> dict:
    return commit_prepared_application(
        project,
        project.manifest()["id"],
        work_id,
        request_id,
        preview["id"],
        preview["candidate_id"],
        preview["work_state_version"],
    )


def _count(project, table: str) -> int:
    with project._conn() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_preview_creates_no_live_entries_or_names(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed the river.")
    mark = _mark("Mara crossed the river.", "Mara")
    for _index in range(3):
        preview = preview_transfer(project, work["id"], 0, donor, mark)
        assert preview["binding_applies"] is True
        assert preview["final"]["text"] == "_____ crossed the river."
        assert preview["exact_donor_copy"] is False
    assert _count(project, "work_entry") == 0
    assert _count(project, "held_name") == 0
    assert work["state_version"] == get_work(project, work["id"])["state_version"]


def test_bound_transfer_commits_and_reopens(tmp_path):
    library, project = _project(tmp_path)
    saved = project.commit_text("A desk sentence.", "authored")
    project.select(saved["id"])
    project.set_draft("desk draft")
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed the river.")
    preview = preview_transfer(project, work["id"], 0, donor, _mark("Mara crossed the river.", "Mara"))
    result = _commit(project, work["id"], preview, "transfer-1")
    again = _commit(project, work["id"], preview, "transfer-1")
    assert again == result
    assert _count(project, "work_entry") == 1
    assert _count(project, "held_name") == 1
    assert _count(project, "application_receipt") == 1
    opened = get_work(project, work["id"])
    assert opened["entries"][0]["text"] == "_____ crossed the river."
    assert opened["held_names"][0]["text"] == "Mara"
    assert opened["held_names"][0]["source_title"] == "River"
    assert opened["state_version"] == result["work_state_version"]
    reopened = Library(tmp_path).open_project(project.manifest()["id"])
    restored = get_work(reopened, work["id"])
    assert restored["entries"][0]["text"] == "_____ crossed the river."
    assert restored["held_names"][0]["text"] == "Mara"
    assert any(event["action"] == "transfer" for event in restored["events"])
    assert project.draft()["text"] == "desk draft"
    assert project.selected_revision_id() == saved["id"]
    assert all(item["origin_kind"] != "candidate" for item in project.revisions())
    _ = library


def test_retry_after_the_work_advances_returns_the_original_receipt(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed the river.")
    first = preview_transfer(project, work["id"], 0, donor, _mark("Mara crossed the river.", "Mara"))
    original = _commit(project, work["id"], first, "same-request")
    second_donor = _donor(project, "Mara left the road.", "Road")
    current = get_work(project, work["id"])
    second = preview_transfer(
        project, work["id"], 1, second_donor, _mark("Mara left the road.", "Mara")
    )
    _commit(project, work["id"], second, "other-request")
    retried = _commit(project, work["id"], first, "same-request")
    assert retried == original
    assert _count(project, "work_entry") == 2
    assert _count(project, "held_name") == 2
    _ = current


def test_a_reused_request_id_conflicts(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed the river.")
    mark = _mark("Mara crossed the river.", "Mara")
    first = preview_transfer(project, work["id"], 0, donor, mark)
    second = preview_transfer(project, work["id"], 0, donor, mark)
    _commit(project, work["id"], first, "once")
    with pytest.raises(ProjectError) as error:
        _commit(project, work["id"], second, "once")
    assert error.value.code == "IDEMPOTENCY_CONFLICT"
    assert _count(project, "work_entry") == 1


def test_a_stale_preview_keeps_the_current_work(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed the river.")
    preview = preview_transfer(project, work["id"], 0, donor, _mark("Mara crossed the river.", "Mara"))
    moved = unbind_influence(project, work["id"], preview["work_state_version"])
    with pytest.raises(ProjectError) as error:
        _commit(project, work["id"], preview, "late")
    assert error.value.code == "STALE_PREVIEW"
    assert get_work(project, work["id"])["entries"] == []
    assert moved["state_version"] == get_work(project, work["id"])["state_version"]
    rebound = _influence(project, get_work(project, work["id"]))
    fresh = preview_transfer(project, work["id"], 0, donor, _mark("Mara crossed the river.", "Mara"))
    with pytest.raises(ProjectError) as mismatch:
        commit_prepared_application(
            project,
            project.manifest()["id"],
            work["id"],
            "wrong-candidate",
            fresh["id"],
            fresh["base"]["revision_id"],
            fresh["work_state_version"],
        )
    assert mismatch.value.code == "CONFLICT"
    assert _count(project, "work_entry") == 0
    _ = rebound


def test_only_the_marked_occurrence_is_withheld(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    text = "Mara saw Mara."
    preview = preview_transfer(project, work["id"], 0, _donor(project, text), _mark(text, "Mara", 1))
    assert preview["base"]["text"] == text
    assert preview["final"]["text"] == "Mara saw _____."


def test_a_bound_transfer_without_a_mark_is_refused(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    with pytest.raises(ProjectError) as error:
        preview_transfer(project, work["id"], 0, _donor(project, "Mara crossed."), None)
    assert error.value.code == "MARK_REQUIRED"
    assert _count(project, "operation_preview") == 0


def test_name_displacement_across_a_protected_donor_conflicts(tmp_path):
    _library, project = _project(tmp_path)
    work = create_work(project, "Crossing")
    host = _donor(project, "The river was wide.", "Host")
    added = preview_transfer(project, work["id"], 0, host, None)
    _commit(project, work["id"], added, "host")
    bound = _influence(project, get_work(project, work["id"]))
    entry = bound["entries"][0]
    donor = _donor(project, "Mara crossed.")
    with pytest.raises(ProjectError) as error:
        preview_protected_insert(
            project,
            work["id"],
            entry["id"],
            0,
            donor,
            " ",
            _mark("Mara crossed.", "Mara"),
        )
    assert error.value.code == "RULE_CONFLICT"
    kept = get_work(project, work["id"])
    assert kept["entries"][0]["text"] == "The river was wide."
    assert kept["state_version"] == bound["state_version"]
    assert kept["held_names"] == []


def test_duplicate_names_return_independently(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    first = _donor(project, "Mara crossed the river.", "River")
    second = _donor(project, "Mara crossed the square.", "Square")
    one = preview_transfer(project, work["id"], 0, first, _mark("Mara crossed the river.", "Mara"))
    _commit(project, work["id"], one, "one")
    current = get_work(project, work["id"])
    two = preview_transfer(project, work["id"], 1, second, _mark("Mara crossed the square.", "Mara"))
    _commit(project, work["id"], two, "two")
    named = get_work(project, work["id"])
    assert [item["text"] for item in named["held_names"]] == ["Mara", "Mara"]
    assert named["held_names"][0]["id"] != named["held_names"][1]["id"]
    earlier = named["held_names"][0]
    preview = preview_return(project, work["id"], earlier["id"], named["state_version"])
    assert preview["final"]["text"] == "Mara crossed the river."
    _commit(project, work["id"], preview, "return-one")
    after = get_work(project, work["id"])
    by_id = {item["id"]: item for item in after["held_names"]}
    assert by_id[earlier["id"]]["status"] == "returned"
    assert by_id[named["held_names"][1]["id"]]["status"] == "held"
    texts = [entry["text"] for entry in after["entries"] if not entry["removed"]]
    assert "Mara crossed the river." in texts
    assert "_____ crossed the square." in texts
    returned = next(entry for entry in after["entries"] if entry["text"] == "Mara crossed the river.")
    assert any(event["earlier_text"] == "_____ crossed the river." for event in after["events"])
    _ = current, returned


def test_edit_and_removal_do_not_guess_a_target(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed the river.")
    preview = preview_transfer(project, work["id"], 0, donor, _mark("Mara crossed the river.", "Mara"))
    _commit(project, work["id"], preview, "transfer")
    current = get_work(project, work["id"])
    entry = current["entries"][0]
    edited = edit_entry(project, work["id"], entry["id"], "The river remained.", current["state_version"])
    held = edited["held_names"][0]
    assert held["status"] == "held"
    assert held["target_state"] == "unresolved"
    assert held["message"] == CHANGED
    with pytest.raises(ProjectError) as error:
        preview_return(project, work["id"], held["id"], edited["state_version"])
    assert error.value.message == CHANGED
    assert edited["entries"][0]["text"] == "The river remained."
    removed = remove_entry(project, work["id"], entry["id"], edited["state_version"])
    detached = removed["held_names"][0]
    assert detached["status"] == "held"
    assert detached["target_state"] == "detached"
    with pytest.raises(ProjectError) as blocked:
        preview_return(project, work["id"], detached["id"], removed["state_version"])
    assert blocked.value.code == "TARGET_DETACHED"
    assert _count(project, "held_name") == 1


def test_unbinding_changes_only_future_transfers(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    text = "Mara crossed the river."
    donor = _donor(project, text)
    preview = preview_transfer(project, work["id"], 0, donor, _mark(text, "Mara"))
    _commit(project, work["id"], preview, "held")
    current = get_work(project, work["id"])
    revised = create_influence(
        project,
        "A later reading.",
        "The rule is still the same kind of withholding.",
        template="withhold_marked_span_v1",
        parameters={"mark_role": "name", "replacement_text": "_____"},
        influence_id=current["binding"]["influence_id"],
    )
    assert revised["version_number"] == 2
    assert get_work(project, work["id"])["binding"]["influence_version_id"] == current["binding"]["influence_version_id"]
    unbound = unbind_influence(project, work["id"], current["state_version"])
    copied = preview_transfer(project, work["id"], 1, donor, None)
    assert copied["binding_applies"] is False
    assert copied["exact_donor_copy"] is True
    assert copied["final"]["text"] == text
    _commit(project, work["id"], copied, "plain")
    after = get_work(project, work["id"])
    assert after["held_names"][0]["status"] == "held"
    assert any(entry["text"] == text for entry in after["entries"])
    assert any(event["action"] == "unbind" for event in after["events"])
    assert any(event["action"] == "transfer" for event in after["events"])
    _ = unbound


def test_protected_bytes_survive_until_they_are_released(tmp_path):
    _library, project = _project(tmp_path)
    work = create_work(project, "Crossing")
    host = preview_transfer(project, work["id"], 0, _donor(project, "The river was wide.", "Host"), None)
    _commit(project, work["id"], host, "host")
    current = get_work(project, work["id"])
    entry_id = current["entries"][0]["id"]
    inserted = preview_protected_insert(
        project,
        work["id"],
        entry_id,
        len("The river was wide.".encode("utf-8")),
        _donor(project, "Mara", "Name"),
        " ",
    )
    assert "Protected" not in inserted["final"]["text"]
    assert inserted["final"]["text"] == "The river was wide. Mara"
    assert inserted["protected"][0]["text"] == "Mara"
    _commit(project, work["id"], inserted, "graft")
    grafted = get_work(project, work["id"])
    assert grafted["entries"][0]["protected"][0]["text"] == "Mara"
    with pytest.raises(ProjectError) as blocked:
        edit_entry(project, work["id"], entry_id, "The river was wide.", grafted["state_version"])
    assert blocked.value.code == "PROTECTED_RANGE"
    assert get_work(project, work["id"])["entries"][0]["text"] == "The river was wide. Mara"
    released = edit_entry(
        project,
        work["id"],
        entry_id,
        "The river was wide.",
        grafted["state_version"],
        release_protection=True,
    )
    assert released["entries"][0]["text"] == "The river was wide."
    assert released["entries"][0]["protected"] == []


def test_a_return_over_protected_bytes_conflicts(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed.")
    preview = preview_transfer(project, work["id"], 0, donor, _mark("Mara crossed.", "Mara"))
    _commit(project, work["id"], preview, "held")
    current = unbind_influence(project, work["id"], get_work(project, work["id"])["state_version"])
    entry = current["entries"][0]
    grafted = preview_protected_insert(
        project,
        work["id"],
        entry["id"],
        len(entry["text"].encode("utf-8")),
        _donor(project, "stone", "Stone"),
        " ",
    )
    _commit(project, work["id"], grafted, "stone")
    named = get_work(project, work["id"])
    assert named["held_names"][0]["target_state"] == "resolved"
    protected = named["entries"][0]["protected"][0]
    with pytest.raises(ProjectError) as error:
        preview_return(
            project,
            work["id"],
            named["held_names"][0]["id"],
            named["state_version"],
            protected["start_byte"],
            protected["end_byte"],
        )
    assert error.value.code == "PROTECTED_RANGE"
    assert get_work(project, work["id"])["entries"][0]["text"] == named["entries"][0]["text"]
    assert get_work(project, work["id"])["state_version"] == named["state_version"]


def test_a_false_protection_label_is_not_kept(tmp_path):
    _library, project = _project(tmp_path)
    work = create_work(project, "Crossing")
    host = preview_transfer(project, work["id"], 0, _donor(project, "The river was wide."), None)
    _commit(project, work["id"], host, "host")
    current = get_work(project, work["id"])
    inserted = preview_protected_insert(
        project,
        work["id"],
        current["entries"][0]["id"],
        0,
        _donor(project, "Mara", "Name"),
        "",
    )
    _commit(project, work["id"], inserted, "graft")
    grafted = get_work(project, work["id"])
    revision_id = grafted["entries"][0]["revision_id"]
    with project.immediate_transaction() as conn:
        conn.execute(
            "UPDATE protected_range SET slice_sha256=? WHERE passage_revision_id=?",
            ("0" * 64, revision_id),
        )
    cleared = get_work(project, work["id"])
    assert cleared["entries"][0]["protected"] == []
    with project._conn() as conn:
        released = conn.execute(
            "SELECT released FROM protected_range WHERE passage_revision_id=?",
            (revision_id,),
        ).fetchone()[0]
    assert released == 1


def test_a_prose_influence_does_not_govern_the_work(tmp_path):
    _library, project = _project(tmp_path)
    work = create_work(project, "Crossing")
    idea = create_influence(project, "An idea", "This is not a rule.")
    assert idea["operative"] is False
    with pytest.raises(ProjectError) as error:
        bind_influence(project, work["id"], idea["id"], work["state_version"])
    assert error.value.code == "NOT_OPERATIVE"
    assert get_work(project, work["id"])["binding"] is None


def test_reordering_stales_a_preview(tmp_path):
    _library, project = _project(tmp_path)
    work = create_work(project, "Crossing")
    first = preview_transfer(project, work["id"], 0, _donor(project, "One.", "One"), None)
    _commit(project, work["id"], first, "one")
    current = get_work(project, work["id"])
    second = preview_transfer(project, work["id"], 1, _donor(project, "Two.", "Two"), None)
    _commit(project, work["id"], second, "two")
    current = get_work(project, work["id"])
    ids = [entry["id"] for entry in current["entries"]]
    pending = preview_transfer(project, work["id"], 0, _donor(project, "Three.", "Three"), None)
    reorder_entries(project, work["id"], list(reversed(ids)), current["state_version"])
    with pytest.raises(ProjectError) as error:
        _commit(project, work["id"], pending, "three")
    assert error.value.code == "STALE_PREVIEW"
    assert [entry["text"] for entry in get_work(project, work["id"])["entries"]] == ["Two.", "One."]


def test_a_host_and_donor_keep_both_parents(tmp_path):
    _library, project = _project(tmp_path)
    host_revision = project.commit_text("The river was wide.", "authored")
    work = create_work(project, "Crossing")
    added = preview_transfer(
        project,
        work["id"],
        0,
        {
            "owner_kind": "passage_revision",
            "owner_id": host_revision["id"],
            "start_byte": 0,
            "end_byte": len(host_revision["text"].encode("utf-8")),
        },
        None,
    )
    _commit(project, work["id"], added, "host")
    donor_revision = project.commit_text("Mara", "authored")
    current = get_work(project, work["id"])
    inserted = preview_protected_insert(
        project,
        work["id"],
        current["entries"][0]["id"],
        len("The river was wide.".encode("utf-8")),
        {
            "owner_kind": "passage_revision",
            "owner_id": donor_revision["id"],
            "start_byte": 0,
            "end_byte": len("Mara".encode("utf-8")),
        },
        " ",
    )
    result = _commit(project, work["id"], inserted, "graft")
    parents = {item["relationship"] for item in project.revision(result["revision_id"])["parents"]}
    assert parents == {"host", "transferred_from"}


def test_commit_routes_report_conflicts(tmp_path):
    client = TestClient(create_app(Library(tmp_path)))
    first = client.post("/api/v1/projects", json={"title": "One"}).json()["id"]
    client.post("/api/v1/projects", json={"title": "Two"})
    denied = client.post(f"/api/v1/projects/{first}/works", json={"title": "Elsewhere"})
    assert denied.status_code == 409
    assert denied.json()["code"] == "PROJECT_NOT_ACTIVE"
    project_id = client.get("/api/v1/projects").json()["active_project_id"]
    work = client.post(f"/api/v1/projects/{project_id}/works", json={"title": "Crossing"}).json()
    influence = client.post(
        f"/api/v1/projects/{project_id}/influences",
        json={
            "name": "What crosses must leave its name behind.",
            "interpretation": "Identity is displaced when this material enters the work.",
            "template": "withhold_marked_span_v1",
            "parameters": {"mark_role": "name", "replacement_text": "_____"},
        },
    ).json()
    bound = client.post(
        f"/api/v1/projects/{project_id}/works/{work['id']}/binding",
        json={"influence_version_id": influence["id"], "expected_work_state_version": work["state_version"]},
    ).json()
    imported = client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"title": "River", "text": "Mara crossed the river."},
    ).json()
    preview = client.post(
        f"/api/v1/projects/{project_id}/previews/transfer",
        json={
            "work_id": work["id"],
            "position": 0,
            "donor": {
                "owner_kind": "source_version",
                "owner_id": imported["id"],
                "start_byte": 0,
                "end_byte": len("Mara crossed the river.".encode("utf-8")),
            },
            "mark": {"start_byte": 0, "end_byte": 4},
        },
    ).json()
    adopted = client.post(
        f"/api/v1/projects/{project_id}/works/{work['id']}/commit",
        json={
            "client_request_id": "http-1",
            "preview_id": preview["id"],
            "candidate_id": preview["candidate_id"],
            "expected_work_state_version": preview["work_state_version"],
        },
    )
    assert adopted.status_code == 200
    assert adopted.json()["held_name_ids"]
    stale = client.post(
        f"/api/v1/projects/{project_id}/works/{work['id']}/commit",
        json={
            "client_request_id": "http-2",
            "preview_id": preview["id"],
            "candidate_id": preview["candidate_id"],
            "expected_work_state_version": preview["work_state_version"],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "STALE_PREVIEW"
    opened = client.get(f"/api/v1/projects/{project_id}/works/{work['id']}").json()
    assert opened["entries"][0]["text"] == "_____ crossed the river."
    assert opened["state_version"] == bound["state_version"] + 1


def test_retarget_lets_a_changed_entry_receive_the_name(tmp_path):
    _library, project = _project(tmp_path)
    work = _influence(project, create_work(project, "Crossing"))
    donor = _donor(project, "Mara crossed the river.")
    preview = preview_transfer(project, work["id"], 0, donor, _mark("Mara crossed the river.", "Mara"))
    _commit(project, work["id"], preview, "transfer")
    current = get_work(project, work["id"])
    entry = current["entries"][0]
    edited = edit_entry(project, work["id"], entry["id"], "The river remained.", current["state_version"])
    held = edited["held_names"][0]
    placed = retarget_held_name(project, work["id"], held["id"], edited["state_version"], 0, 0)
    assert placed["held_names"][0]["target_state"] == "resolved"
    returned = preview_return(project, work["id"], held["id"], placed["state_version"])
    assert returned["final"]["text"].startswith("Mara")
    _commit(project, work["id"], returned, "return")
    assert get_work(project, work["id"])["entries"][0]["text"].startswith("Mara")
