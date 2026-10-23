"""Marked omission asks only for the missing span, then waits to be adopted."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
from fastapi.testclient import TestClient

from ncm_art.api.app import create_app
from ncm_art.corpus.sources import import_bytes
from ncm_art.operations.omission import SYSTEM_PROMPT
from ncm_art.providers.repair_job import execute_repair
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
    queue_omission_repair,
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


def _answer(text: str, finish="stop"):
    return {
        "model": "local-test-revision",
        "choices": [
            {
                "finish_reason": finish,
                "message": {"content": json.dumps({"replacement_text": text})},
            }
        ],
    }


def _run(project, work, entry, transport, needle="lantern", count=1, release=False, request_id="repair-1"):
    start, end = _span(entry["text"], needle)
    job = queue_omission_repair(
        project,
        project.root.parent,
        work["id"],
        entry["revision_id"],
        {"start_byte": start, "end_byte": end},
        {"start_byte": 0, "end_byte": len(entry["text"].encode("utf-8"))},
        {
            "kind": "replace_entry",
            "entry_id": entry["id"],
            "expected_revision_id": entry["revision_id"],
        },
        request_id,
        count,
        release,
    )
    execute_repair(project, job, project.root.parent, transport)
    return project.job(job["id"])


def test_the_provider_sees_one_window_and_the_other_copy_stays(tmp_path):
    _library, project = opened(tmp_path)
    work, entry = _entry(project)
    seen = []

    def transport(body):
        seen.append(body)
        return _answer("boat")

    finished = _run(project, work, entry, transport)
    assert finished["state"] == "succeeded"
    request = seen[0]
    user = request["messages"][1]["content"]
    system = request["messages"][0]["content"]
    assert system == SYSTEM_PROMPT
    assert user == "Keep this outside. The _____ crossed the river. The lantern stayed."
    assert "lantern" not in system
    assert "River" not in json.dumps(request["messages"])
    assert request["response_format"]["json_schema"]["schema"]["required"] == ["replacement_text"]
    preview = get_preview(project, finished["result"]["preview_ids"][0])
    assert preview["provider_window"] == user
    assert preview["omitted_text"] == "lantern"
    assert preview["base"]["text"] == entry["text"]
    assert preview["final"]["text"] == "Keep this outside. The boat crossed the river. The lantern stayed."
    assert preview["binding_applies"] is False
    assert get_work(project, work["id"])["state_version"] == work["state_version"]
    assert get_work(project, work["id"])["entries"][0]["text"] == entry["text"]
    assert "authorization" not in json.dumps(finished["result"]).lower()


def test_a_narrow_context_keeps_the_bytes_outside_it(tmp_path):
    _library, project = opened(tmp_path)
    text = "Keep this outside. The lantern crossed the river. The lantern stayed."
    work, entry = _entry(project, text)
    raw = text.encode("utf-8")
    context_start = raw.index(b"The lantern")
    start, end = _span(text, "lantern")

    def transport(body):
        assert body["messages"][1]["content"] == "The _____ crossed the river. The lantern stayed."
        assert "Keep this outside." not in body["messages"][1]["content"]
        return _answer("boat")

    job = queue_omission_repair(
        project,
        project.root.parent,
        work["id"],
        entry["revision_id"],
        {"start_byte": start, "end_byte": end},
        {"start_byte": context_start, "end_byte": len(raw)},
        {"kind": "replace_entry", "entry_id": entry["id"], "expected_revision_id": entry["revision_id"]},
        "repair-narrow",
    )
    execute_repair(project, job, project.root.parent, transport)
    preview = get_preview(project, project.job(job["id"])["result"]["preview_ids"][0])
    assert preview["final"]["text"].startswith("Keep this outside. The boat crossed")


def test_a_bound_name_rule_does_not_change_a_repair(tmp_path):
    _library, project = opened(tmp_path)
    work, entry = _entry(project, "Mara crossed the river.")
    version = create_influence(
        project,
        "What crosses must leave its name behind.",
        "Identity is displaced when this material enters the work.",
        template="withhold_marked_span_v1",
        parameters={"mark_role": "name", "replacement_text": "_____"},
    )
    bound = bind_influence(project, work["id"], version["id"], work["state_version"])
    entry = get_work(project, work["id"])["entries"][0]
    finished = _run(project, bound, entry, lambda _body: _answer("the figure"), needle="Mara")
    preview = get_preview(project, finished["result"]["preview_ids"][0])
    assert preview["final"]["text"] == "the figure crossed the river."
    assert "_____" not in preview["final"]["text"]
    adopted = commit_prepared_application(
        project,
        project.manifest()["id"],
        work["id"],
        "adopt-repair",
        preview["id"],
        preview["candidate_id"],
        preview["work_state_version"],
    )
    loaded = get_work(project, work["id"])
    assert loaded["entries"][0]["text"] == "the figure crossed the river."
    assert loaded["held_names"] == []
    assert adopted["held_name_ids"] == []
    assert loaded["state_version"] == bound["state_version"] + 1


def test_malformed_output_is_retried_once_and_then_refused(tmp_path):
    _library, project = opened(tmp_path)
    work, entry = _entry(project, "Mara crossed the river.")
    calls = {"count": 0}

    def transport(_body):
        calls["count"] += 1
        if calls["count"] == 1:
            return {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]}
        return _answer("the figure")

    finished = _run(project, work, entry, transport, needle="Mara")
    assert calls["count"] == 2
    assert finished["state"] == "succeeded"
    assert finished["result"]["attempts"][0]["attempt"] == 2

    work, entry = _entry(project, "Ida crossed the square.", request_id="transfer-ida")
    request_id = "repair-ida"
    def always_bad(_body):
        return {"choices": [{"finish_reason": "length", "message": {"content": json.dumps({"replacement_text": "x"})}}]}

    state = get_work(project, work["id"])["state_version"]
    failed = _run(project, work, entry, always_bad, needle="Ida", request_id=request_id)
    assert failed["state"] == "failed"
    assert failed["error"]["code"] == "INVALID_PROVIDER_OUTPUT"
    assert get_work(project, work["id"])["entries"][0]["text"] == "Ida crossed the square."
    assert get_work(project, work["id"])["state_version"] == state
    assert get_work(project, work["id"])["previews"] == []


def test_an_over_budget_replacement_is_not_adopted(tmp_path):
    _library, project = opened(tmp_path)
    work, entry = _entry(project, "Mara crossed the river.")
    finished = _run(project, work, entry, lambda _body: _answer("x" * 600), needle="Mara")
    assert finished["state"] == "failed"
    assert finished["result"] is None or finished["error"]["code"] == "INVALID_PROVIDER_OUTPUT"
    assert get_work(project, work["id"])["previews"] == []


def test_a_missing_provider_does_not_block_the_archive(tmp_path):
    library, project = opened(tmp_path, configured=False)
    work, entry = _entry(project, "Mara crossed the river.")
    with pytest.raises(ProjectError) as caught:
        queue_omission_repair(
            project,
            library.root,
            work["id"],
            entry["revision_id"],
            {"start_byte": 0, "end_byte": 4},
            {"start_byte": 0, "end_byte": len(entry["text"].encode())},
            {"kind": "replace_entry", "entry_id": entry["id"], "expected_revision_id": entry["revision_id"]},
            "missing",
        )
    assert caught.value.code == "CAPABILITY_UNAVAILABLE"
    assert project.active_job() is None
    client = TestClient(create_app(library))
    response = client.post(
        f"/api/v1/projects/{project.manifest()['id']}/works/{work['id']}/repairs",
        json={
            "client_request_id": "http-missing",
            "passage_revision_id": entry["revision_id"],
            "omission": {"start_byte": 0, "end_byte": 4},
            "context": {"start_byte": 0, "end_byte": len(entry["text"].encode())},
            "destination": {
                "kind": "replace_entry",
                "entry_id": entry["id"],
                "expected_revision_id": entry["revision_id"],
            },
        },
    )
    assert response.status_code == 503
    assert response.json()["code"] == "CAPABILITY_UNAVAILABLE"
    transferred = preview_transfer(
        project,
        work["id"],
        1,
        {
            "owner_kind": "passage_revision",
            "owner_id": entry["revision_id"],
            "start_byte": 0,
            "end_byte": len(entry["text"].encode()),
        },
    )
    assert transferred["final"]["text"] == entry["text"]


def test_a_protected_omission_is_refused_before_a_provider_call(tmp_path):
    _library, project = opened(tmp_path)
    host_text = "The river was wide."
    work, host = _entry(project, host_text)
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
    start, end = _span(entry["text"], "stone")
    with pytest.raises(ProjectError) as caught:
        queue_omission_repair(
            project,
            project.root.parent,
            work["id"],
            entry["revision_id"],
            {"start_byte": start, "end_byte": end},
            {"start_byte": 0, "end_byte": len(entry["text"].encode())},
            {"kind": "replace_entry", "entry_id": entry["id"], "expected_revision_id": entry["revision_id"]},
            "protected-repair",
        )
    assert caught.value.code == "PROTECTED_RANGE"
    assert project.active_job() is None
    assert get_work(project, work["id"])["entries"][0]["text"] == entry["text"]


def test_the_chat_request_does_not_keep_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("NCM_ART_INSTRUCTION_API_KEY", "secret-token")
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            seen["authorization"] = self.headers.get("Authorization")
            seen["body"] = json.loads(raw.decode("utf-8"))
            payload = json.dumps(_answer("boat")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        library, project = opened(tmp_path, configured=False)
        (tmp_path / "instruction.json").write_text(
            json.dumps(
                {
                    "endpoint_kind": "openai-chat-completions",
                    "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                    "model": "local-test",
                }
            ),
            encoding="utf-8",
        )
        work, entry = _entry(project, "Mara crossed the river.")
        finished = _run(project, work, entry, None, needle="Mara")
    finally:
        server.shutdown()
        thread.join(2)
    assert seen["authorization"] == "Bearer secret-token"
    assert "secret-token" not in json.dumps(finished["result"])
    assert seen["body"]["messages"][1]["content"] == "_____ crossed the river."
    assert finished["result"]["attempts"][0]["actual_model"] == "local-test-revision"
