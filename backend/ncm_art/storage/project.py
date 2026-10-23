"""One studio project: a manifest, a SQLite database, and text assets.

Passage text is stored as exact UTF-8 bytes addressed by SHA-256. SQLite holds
identities, relationships, drafts, and jobs. Short code arrays live in SQLite
as JSON integers.
"""

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ncm_art import __version__
from ncm_art.storage.errors import ProjectError

FORMAT_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _request_hash(recipe: dict) -> str:
    payload = {key: value for key, value in recipe.items() if key != "client_request_id"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class Project:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.db_path = self.root / "project.sqlite"
        self.asset_dir = self.root / "assets"

    @classmethod
    def create(cls, root: Path, title: str) -> "Project":
        root.mkdir(parents=True, exist_ok=False)
        project = cls(root)
        project.asset_dir.mkdir()
        project_id = _new_id()
        manifest = {
            "id": project_id,
            "format_version": FORMAT_VERSION,
            "app_version": __version__,
            "created_at": _now(),
            "title": title,
            "database": "project.sqlite",
        }
        (root / "project.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        project._migrate()
        with project._conn() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('selected_revision_id', '')"
            )
            conn.execute(
                "INSERT INTO editor_draft(id, base_revision_id, body, updated_at) VALUES ('current', '', '', ?)",
                (_now(),),
            )
        return project

    def manifest(self) -> dict:
        return json.loads((self.root / "project.json").read_text(encoding="utf-8"))

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _migrate(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS source_document (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    origin_kind TEXT NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS passage_revision (
                    id TEXT PRIMARY KEY,
                    text_sha256 TEXT NOT NULL,
                    origin_kind TEXT NOT NULL,
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    disposition TEXT
                );
                CREATE TABLE IF NOT EXISTS provenance_edge (
                    id TEXT PRIMARY KEY,
                    child_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    run_id TEXT
                );
                CREATE TABLE IF NOT EXISTS editor_draft (
                    id TEXT PRIMARY KEY,
                    base_revision_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run (
                    id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    passage_revision_id TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS encoding (
                    id TEXT PRIMARY KEY,
                    passage_revision_id TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    codes_json TEXT NOT NULL,
                    padded_token_ids_json TEXT NOT NULL,
                    run_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reconstruction (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    encoding_id TEXT NOT NULL,
                    frames_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS annotation (
                    id TEXT PRIMARY KEY,
                    revision_id TEXT NOT NULL,
                    text_sha256 TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS job (
                    id TEXT PRIMARY KEY,
                    client_request_id TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _write_text(self, text: str) -> str:
        data = text.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        path = self.asset_dir / digest
        if not path.exists():
            path.write_bytes(data)
        return digest

    def _read_text(self, digest: str) -> str:
        path = self.asset_dir / digest
        if not path.is_file():
            raise ProjectError("NOT_FOUND", f"Text asset {digest} is missing.", status=500)
        return path.read_bytes().decode("utf-8")

    def set_draft(self, text: str) -> dict:
        selected = self.selected_revision_id() or ""
        with self._conn() as conn:
            conn.execute(
                "UPDATE editor_draft SET body=?, base_revision_id=?, updated_at=? WHERE id='current'",
                (text, selected, _now()),
            )
        return self.draft()

    def draft(self) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM editor_draft WHERE id='current'").fetchone()
        return {
            "text": row["body"],
            "base_revision_id": row["base_revision_id"] or None,
            "updated_at": row["updated_at"],
        }

    def selected_revision_id(self) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key='selected_revision_id'").fetchone()
        value = row["value"] if row else ""
        return value or None

    def select(self, revision_id: str) -> dict:
        revision = self.revision(revision_id)
        with self._conn() as conn:
            conn.execute(
                "UPDATE meta SET value=? WHERE key='selected_revision_id'",
                (revision_id,),
            )
            conn.execute(
                "UPDATE editor_draft SET body=?, base_revision_id=?, updated_at=? WHERE id='current'",
                (revision["text"], revision_id, _now()),
            )
        return revision

    def _revision_from_row(self, row: sqlite3.Row, parents: dict[str, list]) -> dict:
        parent_rows = parents.get(row["id"], [])
        return {
            "id": row["id"],
            "text": self._read_text(row["text_sha256"]),
            "text_sha256": row["text_sha256"],
            "origin_kind": row["origin_kind"],
            "source_id": row["source_id"],
            "created_at": row["created_at"],
            "disposition": row["disposition"],
            "parents": parent_rows,
        }

    def _parents(self, conn: sqlite3.Connection) -> dict[str, list]:
        grouped: dict[str, list] = {}
        for row in conn.execute("SELECT * FROM provenance_edge ORDER BY rowid"):
            grouped.setdefault(row["child_id"], []).append(
                {
                    "parent_id": row["parent_id"],
                    "relationship": row["relationship"],
                    "run_id": row["run_id"],
                }
            )
        return grouped

    def revision(self, revision_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM passage_revision WHERE id=?", (revision_id,)).fetchone()
            parents = self._parents(conn)
        if row is None:
            raise ProjectError("NOT_FOUND", "That passage revision is not in this project.", status=404)
        return self._revision_from_row(row, parents)

    def revisions(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM passage_revision ORDER BY created_at, rowid").fetchall()
            parents = self._parents(conn)
        return [self._revision_from_row(row, parents) for row in rows]

    def commit_text(
        self,
        text: str,
        origin_kind: str,
        *,
        parent_id: str | None = None,
        relationship: str | None = None,
        run_id: str | None = None,
        make_source: bool = False,
    ) -> dict:
        digest = self._write_text(text)
        source_id = None
        if make_source:
            source_id = _new_id()
        revision_id = _new_id()
        created = _now()
        with self._conn() as conn:
            if make_source:
                conn.execute(
                    """INSERT INTO source_document(id, title, origin_kind, text_sha256, created_at)
                       VALUES (?, ?, 'authored', ?, ?)""",
                    (source_id, self.manifest()["title"], digest, created),
                )
            elif parent_id:
                parent = conn.execute(
                    "SELECT source_id FROM passage_revision WHERE id=?",
                    (parent_id,),
                ).fetchone()
                if parent is None:
                    raise ProjectError("NOT_FOUND", "The parent passage is not in this project.", status=404)
                source_id = parent["source_id"]
            conn.execute(
                """INSERT INTO passage_revision(id, text_sha256, origin_kind, source_id, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (revision_id, digest, origin_kind, source_id, created),
            )
            if parent_id and relationship:
                conn.execute(
                    """INSERT INTO provenance_edge(id, child_id, parent_id, relationship, run_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (_new_id(), revision_id, parent_id, relationship, run_id),
                )
        return self.revision(revision_id)

    def ensure_input_revision(self) -> dict:
        """Use the selected revision when the draft matches it. Otherwise commit the draft."""
        draft = self.draft()
        selected_id = self.selected_revision_id()
        if selected_id:
            selected = self.revision(selected_id)
            if selected["text"] == draft["text"]:
                return selected
            revision = self.commit_text(
                draft["text"],
                "edited",
                parent_id=selected_id,
                relationship="edited_from",
            )
        else:
            if draft["text"] == "":
                raise ProjectError("INPUT_EMPTY", "Enter a nonempty passage.")
            revision = self.commit_text(draft["text"], "authored", make_source=True)
        self.select(revision["id"])
        return self.revision(revision["id"])

    def set_disposition(self, revision_id: str, disposition: str | None) -> dict:
        self.revision(revision_id)
        with self._conn() as conn:
            conn.execute(
                "UPDATE passage_revision SET disposition=? WHERE id=?",
                (disposition, revision_id),
            )
        return self.revision(revision_id)

    def add_annotation(self, revision_id: str, kind: str, value: str) -> dict:
        revision = self.revision(revision_id)
        if kind not in {"note", "tag"}:
            raise ProjectError("INVALID_ANNOTATION", "An annotation is a note or a tag.")
        annotation_id = _new_id()
        created = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO annotation(id, revision_id, text_sha256, kind, value, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (annotation_id, revision_id, revision["text_sha256"], kind, value, created),
            )
        return {
            "id": annotation_id,
            "revision_id": revision_id,
            "text_sha256": revision["text_sha256"],
            "kind": kind,
            "value": value,
            "created_at": created,
        }

    def annotations(self, revision_id: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if revision_id:
                rows = conn.execute(
                    "SELECT * FROM annotation WHERE revision_id=? ORDER BY created_at",
                    (revision_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM annotation ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def record_run(self, operation: str, passage_revision_id: str, parameters: dict) -> str:
        run_id = _new_id()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO run(id, operation, passage_revision_id, parameters_json, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (run_id, operation, passage_revision_id, json.dumps(parameters), _now()),
            )
        return run_id

    def run(self, run_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM run WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ProjectError("NOT_FOUND", "That run is not in this project.", status=404)
        return {
            "id": row["id"],
            "operation": row["operation"],
            "passage_revision_id": row["passage_revision_id"],
            "parameters": json.loads(row["parameters_json"]),
            "created_at": row["created_at"],
        }

    def record_encoding(self, passage_revision_id: str, token_count: int, codes: list[int], padded_token_ids: list[int], run_id: str) -> str:
        encoding_id = _new_id()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO encoding(id, passage_revision_id, token_count, codes_json, padded_token_ids_json, run_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (encoding_id, passage_revision_id, token_count, json.dumps(codes), json.dumps(padded_token_ids), run_id),
            )
        return encoding_id

    def record_reconstruction(self, run_id: str, encoding_id: str, frames: list[dict]) -> str:
        reconstruction_id = _new_id()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO reconstruction(id, run_id, encoding_id, frames_json) VALUES (?, ?, ?, ?)",
                (reconstruction_id, run_id, encoding_id, json.dumps(frames)),
            )
        return reconstruction_id

    def reconstruction_for_run(self, run_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM reconstruction WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "run_id": row["run_id"],
            "encoding_id": row["encoding_id"],
            "frames": json.loads(row["frames_json"]),
        }

    def active_job(self) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM job WHERE state IN ('queued', 'running') ORDER BY created_at LIMIT 1"
            ).fetchone()
        return self._job(row) if row else None

    def submit_job(self, operation: str, recipe: dict, client_request_id: str) -> dict:
        stored = dict(recipe)
        stored["operation"] = operation
        stored["client_request_id"] = client_request_id
        # A seed the server invents is not part of the client's request. The same
        # omitted-seed retry must return this job rather than conflict with itself.
        assign_seed = operation == "variants" and "base_seed" not in stored
        digest = _request_hash(stored)
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM job WHERE client_request_id=?",
                (client_request_id,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                if existing["request_hash"] != digest:
                    raise ProjectError(
                        "CONFLICT",
                        "That request id was already used for a different job.",
                        status=409,
                    )
                return self._job(existing)
            active = conn.execute(
                "SELECT id FROM job WHERE state IN ('queued', 'running') LIMIT 1"
            ).fetchone()
            if active is not None:
                conn.commit()
                raise ProjectError(
                    "JOB_ACTIVE",
                    "Finish or cancel the current job before starting another.",
                    status=409,
                )
            job_id = _new_id()
            now = _now()
            if assign_seed:
                stored["base_seed"] = secrets.randbelow(0x100000000)
            conn.execute(
                """INSERT INTO job(id, client_request_id, request_hash, operation, request_json, state,
                                    progress_json, cancel_requested, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'queued', '{}', 0, ?, ?)""",
                (job_id, client_request_id, digest, operation, json.dumps(stored), now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
        return self._job(row)

    def job(self, job_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM job WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ProjectError("NOT_FOUND", "That job is not in this project.", status=404)
        return self._job(row)

    def latest_job(self) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM job ORDER BY created_at DESC LIMIT 1").fetchone()
        return self._job(row) if row else None

    def claim_next_job(self) -> dict | None:
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM job WHERE state='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            now = _now()
            conn.execute(
                "UPDATE job SET state='running', updated_at=? WHERE id=? AND state='queued'",
                (now, row["id"]),
            )
            conn.commit()
            claimed = conn.execute("SELECT * FROM job WHERE id=?", (row["id"],)).fetchone()
        return self._job(claimed)

    def mark_interrupted(self) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """UPDATE job SET state='interrupted', updated_at=?,
                       error_json=?
                   WHERE state='running'""",
                (
                    _now(),
                    json.dumps(
                        {
                            "code": "JOB_INTERRUPTED",
                            "message": "The worker stopped while this job was running.",
                        }
                    ),
                ),
            )
            return cursor.rowcount

    def update_progress(self, job_id: str, progress: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE job SET progress_json=?, updated_at=? WHERE id=?",
                (json.dumps(progress), _now(), job_id),
            )

    def cancel(self, job_id: str) -> dict:
        job = self.job(job_id)
        if job["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return job
        with self._conn() as conn:
            if job["state"] == "queued":
                conn.execute(
                    """UPDATE job SET state='cancelled', cancel_requested=1, updated_at=?,
                           error_json=? WHERE id=?""",
                    (
                        _now(),
                        json.dumps({"code": "CANCELLED", "message": "Cancelled before it started."}),
                        job_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE job SET cancel_requested=1, updated_at=? WHERE id=?",
                    (_now(), job_id),
                )
        return self.job(job_id)

    def cancel_requested(self, job_id: str) -> bool:
        return bool(self.job(job_id)["cancel_requested"])

    def succeed(self, job_id: str, result: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE job SET state='succeeded', result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result), _now(), job_id),
            )

    def fail(self, job_id: str, code: str, message: str, details: dict | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE job SET state='failed', error_json=?, updated_at=? WHERE id=?",
                (json.dumps({"code": code, "message": message, "details": details or {}}), _now(), job_id),
            )

    def finish_cancelled(self, job_id: str, result: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE job SET state='cancelled', result_json=?, error_json=?, updated_at=?
                   WHERE id=?""",
                (
                    json.dumps(result),
                    json.dumps({"code": "CANCELLED", "message": "Cancelled with the candidates already saved."}),
                    _now(),
                    job_id,
                ),
            )

    def _job(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "client_request_id": row["client_request_id"],
            "request_hash": row["request_hash"],
            "operation": row["operation"],
            "request": json.loads(row["request_json"]),
            "state": row["state"],
            "progress": json.loads(row["progress_json"] or "{}"),
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": json.loads(row["error_json"]) if row["error_json"] else None,
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
