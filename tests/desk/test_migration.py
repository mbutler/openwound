"""Opening a format-1 project upgrades it without rewriting its text."""

import hashlib
import json
import sqlite3

import pytest

from ncm_art.model_adapter.profile import LEVELS
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library
from ncm_art.storage.migrate import BASE_TABLES, SCHEMA_VERSION


def _baseline(tmp_path):
    project_id = "baseline-project"
    root = tmp_path / project_id
    root.mkdir()
    text = "Hello\r\n  kite  \u2014 \U0001F6F8"
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    generated = "Mara left."
    generated_bytes = generated.encode("utf-8")
    generated_digest = hashlib.sha256(generated_bytes).hexdigest()
    assets = root / "assets"
    assets.mkdir()
    (assets / digest).write_bytes(data)
    (assets / generated_digest).write_bytes(generated_bytes)
    codes = [0] * sum(LEVELS)
    codes[0] = 7
    manifest = {
        "id": project_id,
        "format_version": 1,
        "app_version": "4.0.0.dev0",
        "created_at": "2026-10-01T00:00:00+00:00",
        "title": "Baseline",
        "database": "project.sqlite",
    }
    (root / "project.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    connection = sqlite3.connect(root / "project.sqlite")
    connection.executescript(BASE_TABLES)
    connection.execute(
        "INSERT INTO meta(key, value) VALUES ('selected_revision_id', 'rev-source')"
    )
    connection.execute(
        "INSERT INTO editor_draft(id, base_revision_id, body, updated_at) VALUES ('current', 'rev-source', ?, '2026-10-01T00:00:00+00:00')",
        (text,),
    )
    connection.execute(
        """INSERT INTO source_document(id, title, origin_kind, text_sha256, notes, created_at)
           VALUES ('source-1', 'Baseline', 'authored', ?, '', '2026-10-01T00:00:00+00:00')""",
        (digest,),
    )
    connection.execute(
        """INSERT INTO passage_revision(id, text_sha256, origin_kind, source_id, created_at)
           VALUES ('rev-source', ?, 'authored', 'source-1', '2026-10-01T00:00:00+00:00')""",
        (digest,),
    )
    connection.execute(
        """INSERT INTO passage_revision(id, text_sha256, origin_kind, source_id, created_at)
           VALUES ('rev-generated', ?, 'generated', 'source-1', '2026-10-01T00:01:00+00:00')""",
        (generated_digest,),
    )
    connection.execute(
        """INSERT INTO provenance_edge(id, child_id, parent_id, relationship, run_id)
           VALUES ('edge-1', 'rev-generated', 'rev-source', 'generated_from', 'run-vary')"""
    )
    parameters = {
        "model_profile": "tinystories-v1",
        "execution_profile": "cpu-fp32-eager-v1",
        "display_policy": "tinystories-eval-cut-at-eos-v1",
        "artifact_sha256": {"tokenizer.pt": "abc", "generator.pt": "def"},
        "retained_level_count": 3,
    }
    connection.execute(
        """INSERT INTO run(id, operation, passage_revision_id, parameters_json, created_at)
           VALUES ('run-encode', 'reconstruct', 'rev-source', ?, '2026-10-01T00:00:30+00:00')""",
        (json.dumps(parameters),),
    )
    connection.execute(
        """INSERT INTO run(id, operation, passage_revision_id, parameters_json, created_at)
           VALUES ('run-vary', 'variants', 'rev-source', ?, '2026-10-01T00:01:00+00:00')""",
        (json.dumps(parameters),),
    )
    connection.execute(
        """INSERT INTO encoding(id, passage_revision_id, token_count, codes_json, padded_token_ids_json, run_id)
           VALUES ('enc-1', 'rev-source', 4, ?, ?, 'run-encode')""",
        (json.dumps(codes), json.dumps([9, 8, 7, 6])),
    )
    connection.execute(
        """INSERT INTO reconstruction(id, run_id, encoding_id, frames_json)
           VALUES ('recon-1', 'run-encode', 'enc-1', ?)""",
        (json.dumps([{"level": 12, "text": "kept"}]),),
    )
    connection.execute(
        """INSERT INTO annotation(id, revision_id, text_sha256, kind, value, created_at)
           VALUES ('note-1', 'rev-source', ?, 'note', 'Keep the kite.', '2026-10-01T00:02:00+00:00')""",
        (digest,),
    )
    result = {
        "run_id": "run-vary",
        "passage_revision_id": "rev-source",
        "candidates": [
            {
                "index": 0,
                "seed": 4,
                "prediction_count": 3,
                "revision_id": "rev-generated",
                "text": generated,
            }
        ],
    }
    request = {
        "operation": "variants",
        "passage_revision_id": "rev-source",
        "retained_level_count": 3,
        "candidate_count": 1,
        "base_seed": 4,
        "sampling": {"temperature": 1.0, "top_k": 0, "top_p": 1.0},
        "model_profile_id": "tinystories-v1",
    }
    connection.execute(
        """INSERT INTO job(
               id, client_request_id, request_hash, operation, request_json, state,
               progress_json, result_json, cancel_requested, created_at, updated_at
           ) VALUES ('job-1', 'old-vary', 'hash', 'variants', ?, 'succeeded', '{}', ?, 0,
                     '2026-10-01T00:01:00+00:00', '2026-10-01T00:01:30+00:00')""",
        (json.dumps(request), json.dumps(result)),
    )
    connection.commit()
    connection.close()
    return project_id, data, generated_bytes, codes


def _representation_count(project) -> int:
    with project._conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM representation").fetchone()[0]


def test_a_new_project_starts_at_the_current_schema(tmp_path):
    project = Library(tmp_path).create_project("Kite")
    assert project.manifest()["format_version"] == SCHEMA_VERSION
    assert project.schema_version() == SCHEMA_VERSION
    assert not (project.root / "backups").exists()


def test_opening_a_baseline_project_preserves_the_desk(tmp_path):
    project_id, source_bytes, generated_bytes, codes = _baseline(tmp_path)
    library = Library(tmp_path)
    project = library.open_project(project_id)
    root = project.root

    assert project.manifest()["format_version"] == SCHEMA_VERSION
    assert project.schema_version() == SCHEMA_VERSION
    assert project.draft()["text"].encode("utf-8") == source_bytes
    assert project.selected_revision_id() == "rev-source"
    assert project.revision("rev-source")["text"].encode("utf-8") == source_bytes
    assert project.revision("rev-generated")["text"].encode("utf-8") == generated_bytes
    assert project.annotations("rev-source")[0]["value"] == "Keep the kite."
    assert project.run("run-encode")["operation"] == "reconstruct"
    assert project.run("run-vary")["parameters"]["retained_level_count"] == 3
    job = project.job("job-1")
    assert job["state"] == "succeeded"
    assert job["result"]["candidates"][0]["revision_id"] == "rev-generated"
    assert (root / "assets" / hashlib.sha256(source_bytes).hexdigest()).read_bytes() == source_bytes
    assert (root / "assets" / hashlib.sha256(generated_bytes).hexdigest()).read_bytes() == generated_bytes

    encoding = project.representation("enc-1")
    assert encoding["kind"] == "source_encoding"
    assert encoding["token_count"] == 4
    assert encoding["padded_token_ids"] == [9, 8, 7, 6]
    assert encoding["codes"] == codes
    assert encoding["level_lengths"] == LEVELS
    assert encoding["tokenizer_fingerprint"] == "abc"
    assert encoding["hierarchy_available"] is True
    with pytest.raises(ProjectError) as missing:
        project.sampled_hierarchy("rev-generated")
    assert missing.value.code == "HIERARCHY_UNAVAILABLE"
    unavailable = project.representations_for("rev-generated")
    assert len(unavailable) == 1
    assert unavailable[0]["kind"] == "sampled_hierarchy"
    assert unavailable[0]["hierarchy_available"] is False
    assert unavailable[0]["codes"] is None
    assert unavailable[0]["token_count"] is None
    assert unavailable[0]["padded_token_ids"] is None
    assert unavailable[0]["seed"] == 4
    assert unavailable[0]["displayed_text_sha256"] == hashlib.sha256(generated_bytes).hexdigest()

    backup = root / "backups" / "schema-1"
    assert (backup / "complete").is_file()
    assert json.loads((backup / "project.json").read_text(encoding="utf-8"))["format_version"] == 1
    assert (backup / "assets" / hashlib.sha256(source_bytes).hexdigest()).read_bytes() == source_bytes
    saved = sqlite3.connect(backup / "project.sqlite")
    tables = {row[0] for row in saved.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "representation" not in tables
    assert saved.execute("SELECT token_count FROM encoding").fetchone()[0] == 4
    saved.close()

    again = Library(tmp_path).open_project(project_id)
    assert _representation_count(again) == _representation_count(project)
    live = sqlite3.connect(root / "project.sqlite")
    live_tables = {row[0] for row in live.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    live.close()
    assert "source_fragment" in live_tables
    assert "fragment_fts" in live_tables
    assert "work" in live_tables
    assert "held_name" in live_tables
    schema_two = root / "backups" / "schema-2"
    assert (schema_two / "complete").read_text(encoding="utf-8").startswith("schema-2")
    saved_two = sqlite3.connect(schema_two / "project.sqlite")
    tables_two = {row[0] for row in saved_two.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "representation" in tables_two
    assert "source_fragment" not in tables_two
    saved_two.close()
    schema_three = root / "backups" / "schema-3"
    assert (schema_three / "complete").read_text(encoding="utf-8").startswith("schema-3")
    saved_three = sqlite3.connect(schema_three / "project.sqlite")
    tables_three = {row[0] for row in saved_three.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "source_fragment" in tables_three
    assert "work" not in tables_three
    saved_three.close()
    assert list((root / "backups").glob(".schema-1-*")) == []

    manifest = again.manifest()
    manifest["format_version"] = 1
    (root / "project.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    reconciled = Library(tmp_path).open_project(project_id)
    assert reconciled.manifest()["format_version"] == SCHEMA_VERSION
    assert reconciled.schema_version() == SCHEMA_VERSION
    assert _representation_count(reconciled) == 2
    assert reconciled.draft()["text"].encode("utf-8") == source_bytes


def test_a_newer_format_is_rejected_without_migration(tmp_path):
    project_id, source_bytes, _generated, _codes = _baseline(tmp_path)
    root = tmp_path / project_id
    manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
    manifest["format_version"] = 99
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProjectError) as rejected:
        Library(tmp_path).open_project(project_id)
    assert rejected.value.code == "UNSUPPORTED_FORMAT"
    assert not (root / "backups").exists()
    assert json.loads((root / "project.json").read_text(encoding="utf-8"))["format_version"] == 99
    connection = sqlite3.connect(root / "project.sqlite")
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "representation" not in tables
    stored = connection.execute("SELECT body FROM editor_draft").fetchone()[0]
    connection.close()
    assert stored.encode("utf-8") == source_bytes


def test_a_failed_transaction_does_not_keep_a_partial_revision(tmp_path):
    project = Library(tmp_path).create_project("Kite")
    project.set_draft("Hello")
    original = project.ensure_input_revision()
    with pytest.raises(RuntimeError):
        with project.immediate_transaction() as conn:
            project.insert_revision(
                conn,
                revision_id="partial",
                text_sha256=original["text_sha256"],
                origin_kind="edited",
                source_id=None,
                created_at="2026-01-01T00:00:00+00:00",
            )
            raise RuntimeError("stop")
    assert [item["id"] for item in project.revisions()] == [original["id"]]


def test_a_representation_requires_a_real_passage(tmp_path):
    project = Library(tmp_path).create_project("Kite")
    with pytest.raises(sqlite3.IntegrityError):
        with project.immediate_transaction() as conn:
            project.insert_representation(
                conn,
                {
                    "kind": "source_encoding",
                    "passage_revision_id": "missing",
                    "token_count": 1,
                    "padded_token_ids": [1],
                    "codes": [1],
                    "level_lengths": [1],
                    "codebook_sizes": [16],
                    "model_profile": "tinystories-v1",
                    "execution_profile": "cpu-fp32-eager-v1",
                    "hierarchy_available": True,
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            )
