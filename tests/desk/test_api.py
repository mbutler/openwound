"""HTTP contracts for the desk. Inference is not run here."""

from fastapi.testclient import TestClient

from ncm_art.api.app import create_app
from ncm_art.storage.library import Library


def _client(tmp_path):
    def count(text: str) -> dict:
        return {
            "token_count": len(text),
            "text_length": 128,
            "too_long": len(text) > 128,
            "policy": "test",
        }

    return TestClient(create_app(Library(tmp_path), token_counter=count))


def test_create_reopen_and_queue_four_candidates(tmp_path):
    client = _client(tmp_path)
    created = client.post("/api/v1/projects", json={"title": "Desk"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    assert client.put("/api/v1/draft", json={"text": "Anna borrowed a kite."}).status_code == 200

    queued = client.post("/api/v1/jobs/variants", json={"client_request_id": "desk-1"})
    assert queued.status_code == 202
    body = queued.json()
    assert body["state"] == "queued"
    assert body["request"]["candidate_count"] == 4
    assert body["request"]["retained_level_count"] == 3
    assert body["request"]["sampling"] == {"temperature": 1.0, "top_k": 0, "top_p": 1.0}
    assert isinstance(body["request"]["base_seed"], int)

    again = client.post("/api/v1/jobs/variants", json={"client_request_id": "desk-1"})
    assert again.status_code == 202
    assert again.json()["id"] == body["id"]
    assert again.json()["request"]["base_seed"] == body["request"]["base_seed"]

    conflict = client.post(
        "/api/v1/jobs/variants",
        json={"client_request_id": "desk-1", "candidate_count": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "CONFLICT"

    client.post("/api/v1/projects", json={"title": "Other"})
    reopened = client.post("/api/v1/projects/open", json={"project_id": project_id})
    assert reopened.status_code == 200
    assert reopened.json()["draft"]["text"] == "Anna borrowed a kite."
    assert reopened.json()["latest_job"]["id"] == body["id"]


def test_overlong_text_is_rejected_before_a_job(tmp_path):
    client = _client(tmp_path)
    client.post("/api/v1/projects", json={"title": "Desk"})
    client.put("/api/v1/draft", json={"text": "x" * 129})
    response = client.post("/api/v1/jobs/reconstruct", json={"client_request_id": "too-long"})
    assert response.status_code == 409
    assert response.json()["code"] == "INPUT_TOO_LONG"


def test_selecting_an_earlier_passage_restores_its_text(tmp_path):
    client = _client(tmp_path)
    client.post("/api/v1/projects", json={"title": "Desk"})
    client.put("/api/v1/draft", json={"text": "original"})
    saved = client.post("/api/v1/passages", json={"text": "original"})
    original_id = saved.json()["id"]
    client.post("/api/v1/passages", json={"text": "revised"})
    restored = client.post(f"/api/v1/passages/{original_id}/select")
    assert restored.status_code == 200
    desk = client.get("/api/v1/desk").json()
    assert desk["draft"]["text"] == "original"
    assert desk["selected_revision_id"] == original_id
    assert any(item["text"] == "revised" for item in desk["revisions"])


def test_released_bpe_counts_the_smoke_sentence():
    from ncm_art.tokenize import preview_tokens

    counted = preview_tokens("Anna borrowed a red kite from Ben.")
    assert counted["token_count"] == 8
    assert counted["too_long"] is False
    assert preview_tokens("")["token_count"] == 0
