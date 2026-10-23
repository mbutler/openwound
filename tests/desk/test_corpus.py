"""Exact import, lexical encounters, and saved correspondences."""

import base64

import pytest
from fastapi.testclient import TestClient

from ncm_art.api.app import create_app
from ncm_art.corpus.sources import WindowBudget, import_bytes, list_fragments, occurrences
from ncm_art.corpus.correspondences import create_correspondence, get_correspondence, revise_interpretation, set_disposition
from ncm_art.retrieval.encounters import another_passage, run_encounter
from ncm_art.retrieval.semantic import select_related
from ncm_art.retrieval.vectors import normalize, store_embedding
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library


def _project(tmp_path):
    library = Library(tmp_path)
    project = library.create_project("Letters")
    library.open_project(project.manifest()["id"])
    return library, project


def _revision_count(project) -> int:
    with project._conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM passage_revision").fetchone()[0]


def test_import_keeps_exact_bytes_and_distinct_occurrences(tmp_path):
    _library, project = _project(tmp_path)
    raw = "\ufeffHello\r\n\r\ncafe\u0301 \U0001F680\r\n\r\nthe name and the name.".encode("utf-8")
    before = _revision_count(project)
    imported = import_bytes(project, raw, title="Field notes", filename="notes.txt", budgets=[])
    assert project.read_asset_bytes(imported["text_sha256"]) == raw
    assert _revision_count(project) == before
    found = occurrences(project, imported["id"], "the name")
    starts = [item["start_byte"] for item in found["occurrences"]]
    assert len(starts) == 2
    assert starts[0] < starts[1]
    assert found["occurrences"][0]["slice_sha256"] == found["occurrences"][1]["slice_sha256"]
    first = project.read_asset_bytes(imported["text_sha256"])
    for anchor in found["occurrences"]:
        assert first[anchor["start_byte"] : anchor["end_byte"]] == b"the name"


def test_invalid_utf8_is_rejected(tmp_path):
    _library, project = _project(tmp_path)
    with pytest.raises(ProjectError) as error:
        import_bytes(project, b"Hello\xff", title="Broken", filename="notes.txt", budgets=[])
    assert error.value.code == "INVALID_TEXT"
    with project._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM source_document").fetchone()[0] == 0


def test_reimport_keeps_a_family_and_does_not_treat_filename_as_identity(tmp_path):
    _library, project = _project(tmp_path)
    first = import_bytes(project, b"First text.", title="One", filename="shared.txt", budgets=[])
    second = import_bytes(
        project,
        b"Second text.",
        title="Two",
        filename="shared.txt",
        family_id=first["family_id"],
        budgets=[],
    )
    same = import_bytes(project, b"First text.", title="One again", filename="other.txt", budgets=[])
    assert second["id"] != first["id"]
    assert second["family_id"] == first["family_id"]
    assert same["id"] != first["id"]
    assert same["family_id"] != first["family_id"]
    assert same["text_sha256"] == first["text_sha256"]
    assets = list(project.asset_dir.iterdir())
    assert len([path for path in assets if not path.name.startswith(".")]) == 2


def test_a_long_source_stays_intact_and_windows_are_explicit(tmp_path):
    _library, project = _project(tmp_path)
    raw = "one two three four five six seven eight.\n\nShort.".encode("utf-8")
    before = _revision_count(project)

    def count(text: str) -> int:
        return len(text.split())

    imported = import_bytes(
        project,
        raw,
        title="Long",
        budgets=[
            WindowBudget(
                profile_id="test-window",
                limit=4,
                special_tokens_included=False,
                count=count,
                preprocessing_policy="test",
            )
        ],
    )
    assert project.read_asset_bytes(imported["text_sha256"]) == raw
    assert imported["window_count"] >= 2
    assert _revision_count(project) == before
    windows = list_fragments(project, imported["id"], kind="window", limit=20)
    assert windows["fragments"]
    stored = project.read_asset_bytes(imported["text_sha256"])
    for fragment in windows["fragments"]:
        piece = stored[fragment["start_byte"] : fragment["end_byte"]]
        assert piece.decode("utf-8") == fragment["text"]
        assert fragment["token_count"] <= fragment["token_limit"] == 4
        assert fragment["anchor"]["slice_sha256"] == fragment["slice_sha256"]


def test_lexical_encounter_excludes_the_query_and_groups_duplicates(tmp_path):
    _library, project = _project(tmp_path)
    query = import_bytes(
        project,
        b"The lantern crossed the river.\n\nThe lantern remained.",
        title="River",
        budgets=[],
    )
    square = import_bytes(project, b"The lantern crossed the square.", title="Square", budgets=[])
    import_bytes(project, b"The lantern crossed the river.", title="River copy", budgets=[])
    again = import_bytes(project, b"The lantern crossed the square.", title="Square copy", budgets=[])
    fragments = list_fragments(project, query["id"])
    focus = fragments["fragments"][0]
    result = run_encounter(
        project,
        text=focus["text"],
        source_id=query["id"],
        start_byte=focus["start_byte"],
        end_byte=focus["end_byte"],
        views=["lexical"],
    )
    titles = [hit["title"] for hit in result["hits"]]
    assert "River" not in titles
    assert "River copy" not in titles
    assert titles.count("Square") + titles.count("Square copy") == 1
    grouped = result["hits"][0]
    assert grouped["reason"] == "Shared phrase"
    assert any(span["text"] == "The lantern crossed" and span["label"] == "exact" for span in grouped["matched_spans"])
    also_ids = {item["source_id"] for item in grouped["also"]}
    assert also_ids == {square["id"], again["id"]} - {grouped["source_id"]}


def test_related_meaning_ranks_semantic_candidates_before_overlap():
    query = "the lantern crossed the river"
    high = {"id": "a", "text": "the lantern crossed the river at night", "vector": [0.99, 0.01]}
    low = {"id": "b", "text": "a lamp went over the water", "vector": [0.8, 0.2]}
    distant = {"id": "c", "text": "birds slept in the eaves", "vector": [0.05, 0.95]}
    ranked = select_related(query, [high, low, distant], [1.0, 0.0], limit=2)
    assert ranked[0]["id"] == "b"
    assert ranked[0]["reason"] == "Different words, related meaning"
    assert select_related(query, [high], [1.0, 0.0], limit=1)[0]["id"] == "a"
    with pytest.raises(ProjectError):
        normalize([0.0, 0.0])
    with pytest.raises(ProjectError):
        normalize([float("nan"), 1.0])


def test_saved_vectors_reopen_as_a_semantic_encounter(tmp_path):
    _library, project = _project(tmp_path)
    query = import_bytes(project, b"the lantern crossed the river", title="River", budgets=[])
    lamp = import_bytes(project, b"a lamp went over the water", title="Lamp", budgets=[])
    import_bytes(project, b"the lantern crossed the river at night", title="Night", budgets=[])
    fingerprint = "test-vectors"
    by_title = {}
    with project._conn() as conn:
        rows = conn.execute(
            """SELECT f.id, f.source_id, f.start_byte, f.end_byte, s.title, s.text_sha256
               FROM source_fragment f JOIN source_document s ON s.id = f.source_id
               WHERE f.kind = 'paragraph'"""
        ).fetchall()
    for row in rows:
        text = project.read_asset_bytes(row["text_sha256"])[row["start_byte"] : row["end_byte"]].decode("utf-8")
        by_title[row["title"]] = (row["id"], text)
    store_embedding(project, by_title["River"][0], by_title["River"][1], [1.0, 0.0], fingerprint)
    store_embedding(project, by_title["Lamp"][0], by_title["Lamp"][1], [0.8, 0.2], fingerprint)
    store_embedding(project, by_title["Night"][0], by_title["Night"][1], [0.99, 0.01], fingerprint)
    focus = list_fragments(project, query["id"])["fragments"][0]
    result = run_encounter(
        project,
        text=focus["text"],
        source_id=query["id"],
        start_byte=focus["start_byte"],
        end_byte=focus["end_byte"],
        views=["semantic"],
        fingerprint=fingerprint,
    )
    assert result["semantic"]["state"] == "ready"
    assert result["hits"]
    assert result["hits"][0]["title"] == "Lamp"
    assert result["hits"][0]["view"] == "semantic"
    assert "vector" not in result["hits"][0]


def test_a_correspondence_reopens_with_interpretation_history(tmp_path):
    library, project = _project(tmp_path)
    first = import_bytes(project, b"The lantern crossed the river.", title="River", budgets=[])
    second = import_bytes(project, b"A lamp went over the water.", title="Lamp", budgets=[])
    left = list_fragments(project, first["id"])["fragments"][0]["anchor"]
    right = list_fragments(project, second["id"])["fragments"][0]["anchor"]
    with project._conn() as conn:
        edges = conn.execute("SELECT COUNT(*) FROM provenance_edge").fetchone()[0]
    saved = create_correspondence(
        project,
        members=[left, right],
        title="Crossing",
        interpretation="The condition of crossing changes the name.",
        producer="artist",
    )
    revised = revise_interpretation(project, saved["id"], "A model proposed a different reading.", "model")
    set_aside = set_disposition(project, saved["id"], "set_aside")
    assert [item["producer"] for item in revised["interpretations"]] == ["artist", "model"]
    assert set_aside["disposition"] == "set_aside"
    with project._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM provenance_edge").fetchone()[0] == edges
    reopened = Library(tmp_path).open_project(library.active_project_id())
    again = get_correspondence(reopened, saved["id"])
    assert again["members"][0]["text"] == "The lantern crossed the river."
    assert again["members"][1]["text"] == "A lamp went over the water."
    assert again["interpretations"][1]["producer"] == "model"
    assert again["disposition"] == "set_aside"


def test_another_passage_walks_the_imported_sources(tmp_path):
    _library, project = _project(tmp_path)
    import_bytes(project, b"Alpha passage.", title="Alpha", budgets=[])
    import_bytes(project, b"Beta passage.", title="Beta", budgets=[])
    seen = {another_passage(project)["title"] for _ in range(2)}
    assert seen == {"Alpha", "Beta"}
    assert "shuffle" in another_passage(project)["reason"]


def test_routes_import_search_and_reopen(tmp_path):
    client = TestClient(create_app(Library(tmp_path)))
    created = client.post("/api/v1/projects", json={"title": "Letters"})
    project_id = created.json()["id"]
    other = client.post("/api/v1/projects", json={"title": "Other"}).json()["id"]
    client.post("/api/v1/projects/open", json={"project_id": project_id})
    refused = client.post(
        f"/api/v1/projects/{other}/sources",
        json={"title": "Nope", "text": "Should not land."},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "PROJECT_NOT_ACTIVE"
    raw = "The lantern crossed the river.".encode("utf-8")
    imported = client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"title": "River", "filename": "river.txt", "content_base64": base64.b64encode(raw).decode("ascii")},
    )
    assert imported.status_code == 200
    source_id = imported.json()["id"]
    client.post(
        f"/api/v1/projects/{project_id}/sources",
        json={"title": "Square", "text": "The lantern crossed the square."},
    )
    fragments = client.get(f"/api/v1/projects/{project_id}/sources/{source_id}/fragments")
    focus = fragments.json()["fragments"][0]
    context = client.get(
        f"/api/v1/projects/{project_id}/sources/{source_id}/context",
        params={"start_byte": focus["start_byte"], "end_byte": focus["end_byte"]},
    )
    assert context.status_code == 200
    assert context.json()["focus"]["text"] == "The lantern crossed the river."
    encounter = client.post(
        f"/api/v1/projects/{project_id}/encounters",
        json={
            "text": focus["text"],
            "source_id": source_id,
            "start_byte": focus["start_byte"],
            "end_byte": focus["end_byte"],
            "views": ["lexical"],
        },
    )
    assert encounter.status_code == 200
    assert encounter.json()["hits"][0]["title"] == "Square"
    body = encounter.json()
    saved = client.post(
        f"/api/v1/projects/{project_id}/correspondences",
        json={
            "title": "Crossing",
            "interpretation": "The condition of crossing changes the name.",
            "encounter_id": body["id"],
            "members": [focus["anchor"], body["hits"][0]["anchor"]],
        },
    )
    assert saved.status_code == 200
    correspondence_id = saved.json()["id"]
    desk = client.get("/api/v1/desk").json()
    assert "fragments" not in desk
    assert all(item["text"] != "The lantern crossed the square." for item in desk["revisions"])
    client.post("/api/v1/projects", json={"title": "Pause"})
    client.post("/api/v1/projects/open", json={"project_id": project_id})
    reopened = client.get(f"/api/v1/projects/{project_id}/correspondences/{correspondence_id}")
    assert reopened.status_code == 200
    assert reopened.json()["interpretations"][0]["body"] == "The condition of crossing changes the name."
    assert reopened.json()["members"][1]["text"] == "The lantern crossed the square."


def test_a_missing_embedding_model_fails_the_job_and_leaves_the_worker_path(tmp_path):
    _library, project = _project(tmp_path)
    project.set_draft("Hello")
    job = project.submit_job("embed_encounter", {"query_text": "Hello"}, "embed-missing")
    claimed = project.claim_next_job()

    def missing():
        raise ProjectError("CAPABILITY_UNAVAILABLE", "The MiniLM embedding model is not available.")

    from ncm_art.retrieval.embed_job import execute_embed

    execute_embed(project, claimed, load=missing)
    finished = project.job(job["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert project.draft()["text"] == "Hello"
