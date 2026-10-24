"""Protected host healing asks only for the surroundings, then waits to be adopted."""

import json

import pytest
from fastapi.testclient import TestClient

from ncm_art.api.app import create_app
from ncm_art.corpus.sources import import_bytes
from ncm_art.operations.healing import SYSTEM_PROMPT
from ncm_art.providers.healing_job import execute_healing
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library
from ncm_art.works.service import (
    bind_influence,
    commit_prepared_application,
    create_influence,
    create_work,
    get_preview,
    get_work,
    preview_protected_insert,
    preview_transfer,
    queue_healing,
)


def opened(tmp_path, configured=True):
    library = Library(tmp_path)
    project = library.create_project("Letters")
    library.open_project(project.manifest()["id"])
    if configured:
        (tmp_path / "instruction.json").write_text(
            json.dumps(
                {
                    "endpoint_kind": "openai-chat-completions",
                    "base_url": "http://127.0.0.1:9/v1",
                    "model": "local-test",
                }
            ),
            encoding="utf-8",
        )
    return library, project


def _entry(project, text="Keep this outside. The lantern crossed the river. The lantern stayed.", request_id="transfer-1"):
    imported = import_bytes(project, text.encode("utf-8"), title="River", budgets=[])
    work = create_work(project, "Crossing")
    donor = {
        "owner_kind": "source_version",
        "owner_id": imported["id"],
        "start_byte": 0,
        "end_byte": len(text.encode("utf-8")),
        "text_sha256": imported["text_sha256"],
    }
    preview = preview_transfer(project, work["id"], 0, donor)
    commit_prepared_application(
        project,
        project.manifest()["id"],
        work["id"],
        request_id,
        preview["id"],
        preview["candidate_id"],
        preview["work_state_version"],
    )
    loaded = get_work(project, work["id"])
    return loaded, loaded["entries"][0]


def _span(text: str, needle: str, occurrence=0):
    raw = text.encode("utf-8")
    encoded = needle.encode("utf-8")
    start = -1
    for _index in range(occurrence + 1):
        start = raw.find(encoded, start + 1)
    return start, start + len(encoded)


def _answer(before: str, after: str, finish="stop"):
    return {
        "model": "local-test-revision",
        "choices": [
            {
                "finish_reason": finish,
                "message": {"content": json.dumps({"before": before, "after": after})},
            }
        ],
    }


def _run(project, work, entry, transport, needle="crossed the river", host=None, count=1, release=False, request_id="heal-1"):
    start, end = _span(entry["text"], needle)
    raw = entry["text"].encode("utf-8")
    region = host or {"start_byte": 0, "end_byte": len(raw)}
    job = queue_healing(
        project,
        project.root.parent,
        work["id"],
        entry["revision_id"],
        region,
        {"start_byte": start, "end_byte": end},
        {
            "kind": "replace_entry",
            "entry_id": entry["id"],
            "expected_revision_id": entry["revision_id"],
        },
        request_id,
        count,
        release,
    )
    execute_healing(project, job, project.root.parent, transport)
    return project.job(job["id"])


def test_the_model_does_not_see_the_protected_span_and_the_outer_bytes_stay(tmp_path):
    _library, project = opened(tmp_path)
    text = "Keep this outside. The lantern crossed the river. The lantern stayed."
    work, entry = _entry(project, text)
    raw = text.encode("utf-8")
    host_start = raw.index(b"The lantern crossed")
    host_end = raw.index(b". The lantern stayed.")
    seen = []

    def transport(body):
        seen.append(body)
        return _answer("A boat ", "")

    finished = _run(
        project,
        work,
        entry,
        transport,
        host={"start_byte": host_start, "end_byte": host_end},
    )
    assert finished["state"] == "succeeded"
    request = seen[0]
    user = request["messages"][1]["content"]
    system = request["messages"][0]["content"]
    assert system == SYSTEM_PROMPT
    assert user == "Before the protected span:\nThe lantern \n\nAfter the protected span:\n"
    assert "crossed the river" not in user
    assert "Keep this outside." not in user
    assert "River" not in json.dumps(request["messages"])
    assert request["response_format"]["json_schema"]["schema"]["required"] == ["before", "after"]
    preview = get_preview(project, finished["result"]["preview_ids"][0])
    assert preview["provider_window"] == user
    assert preview["final"]["text"] == "Keep this outside. A boat crossed the river. The lantern stayed."
    assert preview["protected"] == [
        {
            "start_byte": len("Keep this outside. A boat ".encode()),
            "end_byte": len("Keep this outside. A boat crossed the river".encode()),
            "text": "crossed the river",
        }
    ]
    assert preview["binding_applies"] is False
    loaded = get_work(project, work["id"])
    assert loaded["state_version"] == work["state_version"]
    assert loaded["entries"][0]["text"] == text
    assert loaded["previews"]
    adopted = commit_prepared_application(
        project,
        project.manifest()["id"],
        work["id"],
        "adopt-heal",
        preview["id"],
        preview["candidate_id"],
        preview["work_state_version"],
    )
    kept = get_work(project, work["id"])
    assert kept["entries"][0]["text"] == preview["final"]["text"]
    assert kept["entries"][0]["protected"][0]["text"] == "crossed the river"
    assert kept["held_names"] == []
    assert adopted["held_name_ids"] == []
    assert kept["events"][0]["action"] == "heal"


def test_another_copy_in_the_surroundings_stays_visible(tmp_path):
    _library, project = opened(tmp_path)
    text = "The lantern crossed. The lantern stayed."
    work, entry = _entry(project, text, request_id="transfer-copy")
    seen = []

    def transport(body):
        seen.append(body)
        return _answer("The ", " crossed. The lantern stayed.")

    finished = _run(project, work, entry, transport, needle="lantern", request_id="heal-copy")
    user = seen[0]["messages"][1]["content"]
    assert user.count("lantern") == 1
    assert "The lantern crossed" not in user
    preview = get_preview(project, finished["result"]["preview_ids"][0])
    assert preview["final"]["text"] == text
    assert preview["protected"][0]["text"] == "lantern"


def test_a_bound_name_rule_does_not_change_a_healing(tmp_path):
    _library, project = opened(tmp_path)
    work, entry = _entry(project, "Mara crossed the river.", request_id="transfer-mara")
    version = create_influence(
        project,
        "What crosses must leave its name behind.",
        "Identity is displaced when this material enters the work.",
        template="withhold_marked_span_v1",
        parameters={"mark_role": "name", "replacement_text": "_____"},
    )
    bound = bind_influence(project, work["id"], version["id"], work["state_version"])
    entry = get_work(project, work["id"])["entries"][0]
    finished = _run(project, bound, entry, lambda _body: _answer("", " remained."), needle="Mara", request_id="heal-mara")
    preview = get_preview(project, finished["result"]["preview_ids"][0])
    assert preview["final"]["text"] == "Mara remained."
    assert "_____" not in preview["final"]["text"]


def test_an_extra_copy_of_the_protected_span_is_not_a_graft(tmp_path):
    _library, project = opened(tmp_path)
    text = "Keep this outside. The lantern crossed the river."
    work, entry = _entry(project, text, request_id="transfer-extra")
    state = get_work(project, work["id"])["state_version"]
    finished = _run(
        project,
        work,
        entry,
        lambda _body: _answer("crossed the river near ", ""),
        request_id="heal-extra",
    )
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "INVALID_PROVIDER_OUTPUT"
    assert finished["error"]["details"]["attempts"][0]["status"] == "duplicate_protected"
    assert get_work(project, work["id"])["previews"] == []
    assert get_work(project, work["id"])["entries"][0]["text"] == text
    assert get_work(project, work["id"])["state_version"] == state


def test_malformed_output_is_retried_once_and_then_refused(tmp_path):
    _library, project = opened(tmp_path)
    work, entry = _entry(project, "Mara crossed the river.", request_id="transfer-retry")
    calls = {"count": 0}

    def transport(_body):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]}
        return _answer("", " remained.")

    finished = _run(project, work, entry, transport, needle="Mara", request_id="heal-retry")
    assert calls["count"] == 2
    assert finished["state"] == "succeeded"

    work, entry = _entry(project, "Ida crossed the square.", request_id="transfer-ida")

    def always_bad(_body):
        return {"choices": [{"finish_reason": "length", "message": {"content": json.dumps({"before": "", "after": "x"})}}]}

    state = get_work(project, work["id"])["state_version"]
    failed = _run(project, work, entry, always_bad, needle="Ida", request_id="heal-ida")
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "INVALID_PROVIDER_OUTPUT"
    assert failed["error"]["details"]["attempts"]
    assert get_work(project, work["id"])["entries"][0]["text"] == "Ida crossed the square."
    assert get_work(project, work["id"])["state_version"] == state
    assert get_work(project, work["id"])["previews"] == []


def test_an_over_budget_surrounding_is_not_adopted(tmp_path):
    _library, project = opened(tmp_path)
    work, entry = _entry(project, "Mara crossed the river.", request_id="transfer-budget")
    finished = _run(project, work, entry, lambda _body: _answer("x" * 600, ""), needle="Mara", request_id="heal-budget")
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "INVALID_PROVIDER_OUTPUT"
    assert get_work(project, work["id"])["previews"] == []


def test_a_span_outside_the_host_is_refused_before_a_job(tmp_path):
    _library, project = opened(tmp_path)
    text = "Keep this outside. The lantern crossed the river."
    work, entry = _entry(project, text, request_id="transfer-outside")
    raw = text.encode("utf-8")
    start, end = _span(text, "Keep")
    with pytest.raises(ProjectError) as caught:
        queue_healing(
            project,
            project.root.parent,
            work["id"],
            entry["revision_id"],
            {"start_byte": raw.index(b"The lantern"), "end_byte": len(raw)},
            {"start_byte": start, "end_byte": end},
            {"kind": "replace_entry", "entry_id": entry["id"], "expected_revision_id": entry["revision_id"]},
            "heal-outside",
        )
    assert caught.value.code == "INVALID_SPAN"
    assert project.active_job() is None


def test_a_missing_provider_leaves_the_work_unchanged(tmp_path):
    library, project = opened(tmp_path, configured=False)
    work, entry = _entry(project, "Mara crossed the river.", request_id="transfer-missing")
    with pytest.raises(ProjectError) as caught:
        queue_healing(
            project,
            library.root,
            work["id"],
            entry["revision_id"],
            {"start_byte": 0, "end_byte": len(entry["text"].encode())},
            {"start_byte": 0, "end_byte": 4},
            {"kind": "replace_entry", "entry_id": entry["id"], "expected_revision_id": entry["revision_id"]},
            "missing",
        )
    assert caught.value.code == "CAPABILITY_UNAVAILABLE"
    assert project.active_job() is None
    client = TestClient(create_app(library))
    response = client.post(
        f"/api/v1/projects/{project.manifest()['id']}/works/{work['id']}/healings",
        json={
            "client_request_id": "http-missing",
            "passage_revision_id": entry["revision_id"],
            "host": {"start_byte": 0, "end_byte": len(entry["text"].encode())},
            "donor": {"start_byte": 0, "end_byte": 4},
            "destination": {
                "kind": "replace_entry",
                "entry_id": entry["id"],
                "expected_revision_id": entry["revision_id"],
            },
        },
    )
    assert response.status_code == 503
    assert get_work(project, work["id"])["entries"][0]["text"] == entry["text"]


def test_a_protected_surrounding_is_refused_before_a_provider_call(tmp_path):
    _library, project = opened(tmp_path)
    host_text = "The river was wide."
    work, host = _entry(project, host_text, request_id="transfer-stone")
    donor_text = "stone"
    imported = import_bytes(project, donor_text.encode("utf-8"), title="Stone", budgets=[])
    graft = preview_protected_insert(
        project,
        work["id"],
        host["id"],
        len(host_text.encode()),
        {
            "owner_kind": "source_version",
            "owner_id": imported["id"],
            "start_byte": 0,
            "end_byte": len(donor_text.encode()),
        },
        separator=" ",
    )
    commit_prepared_application(
        project,
        project.manifest()["id"],
        work["id"],
        "graft",
        graft["id"],
        graft["candidate_id"],
        graft["work_state_version"],
    )
    loaded = get_work(project, work["id"])
    entry = loaded["entries"][0]
    start, end = _span(entry["text"], "river")
    with pytest.raises(ProjectError) as caught:
        queue_healing(
            project,
            project.root.parent,
            work["id"],
            entry["revision_id"],
            {"start_byte": 0, "end_byte": len(entry["text"].encode())},
            {"start_byte": start, "end_byte": end},
            {"kind": "replace_entry", "entry_id": entry["id"], "expected_revision_id": entry["revision_id"]},
            "protected-heal",
        )
    assert caught.value.code == "PROTECTED_RANGE"
    assert project.active_job() is None
    assert get_work(project, work["id"])["entries"][0]["text"] == entry["text"]
