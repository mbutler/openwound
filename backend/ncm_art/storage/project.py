"""One studio project: a manifest, a SQLite database, and text assets.

Passage text is stored as exact UTF-8 bytes addressed by SHA-256. SQLite holds
identities, relationships, drafts, jobs, and model representations. Short code
arrays live in SQLite as JSON integers. A sampled hierarchy is not stored as a
source encoding.
"""

import hashlib
import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ncm_art import __version__
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.migrate import (
    SCHEMA_VERSION,
    install_schema,
    migrate_project,
    read_schema_version,
    write_manifest,
)


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
            "format_version": SCHEMA_VERSION,
            "app_version": __version__,
            "created_at": _now(),
            "title": title,
            "database": "project.sqlite",
        }
        write_manifest(root, manifest)
        install_schema(project)
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

    def ensure_current(self) -> None:
        migrate_project(self)

    def schema_version(self) -> int:
        with self._conn() as conn:
            return read_schema_version(conn)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def immediate_transaction(self):
        """One immediate write transaction. Callers share this connection."""
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _write_text(self, text: str) -> str:
        return self.write_asset_bytes(text.encode("utf-8"))

    def write_asset_bytes(self, data: bytes) -> str:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProjectError(
                "INVALID_TEXT",
                "That text is not valid UTF-8. It was not imported.",
                {"reason": str(error)},
            ) from error
        digest = hashlib.sha256(data).hexdigest()
        path = self.asset_dir / digest
        if not path.exists():
            temporary = self.asset_dir / f".{digest}.tmp"
            temporary.write_bytes(data)
            temporary.replace(path)
        return digest

    def read_asset_bytes(self, digest: str) -> bytes:
        path = self.asset_dir / digest
        if not path.is_file():
            raise ProjectError("NOT_FOUND", f"Text asset {digest} is missing.", status=500)
        return path.read_bytes()

    def insert_revision(
        self,
        conn: sqlite3.Connection,
        *,
        revision_id: str,
        text_sha256: str,
        origin_kind: str,
        source_id: str | None,
        created_at: str,
        disposition: str | None = None,
    ) -> None:
        conn.execute(
            """INSERT INTO passage_revision(id, text_sha256, origin_kind, source_id, created_at, disposition)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (revision_id, text_sha256, origin_kind, source_id, created_at, disposition),
        )

    def insert_provenance(
        self,
        conn: sqlite3.Connection,
        *,
        child_id: str,
        parent_id: str,
        relationship: str,
        run_id: str | None,
    ) -> None:
        conn.execute(
            """INSERT INTO provenance_edge(id, child_id, parent_id, relationship, run_id)
               VALUES (?, ?, ?, ?, ?)""",
            (_new_id(), child_id, parent_id, relationship, run_id),
        )

    def insert_run(
        self,
        conn: sqlite3.Connection,
        run_id: str,
        operation: str,
        passage_revision_id: str,
        parameters: dict,
        created_at: str,
    ) -> None:
        conn.execute(
            """INSERT INTO run(id, operation, passage_revision_id, parameters_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, operation, passage_revision_id, json.dumps(parameters), created_at),
        )

    def insert_encoding(
        self,
        conn: sqlite3.Connection,
        encoding_id: str,
        passage_revision_id: str,
        token_count: int,
        codes: list[int],
        padded_token_ids: list[int],
        run_id: str,
    ) -> None:
        conn.execute(
            """INSERT INTO encoding(id, passage_revision_id, token_count, codes_json, padded_token_ids_json, run_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                encoding_id,
                passage_revision_id,
                token_count,
                json.dumps(codes),
                json.dumps(padded_token_ids),
                run_id,
            ),
        )

    def insert_representation(self, conn: sqlite3.Connection, fields: dict) -> str:
        prepared = _prepare_representation(fields)
        representation_id = prepared["id"]
        conn.execute(
            """INSERT INTO representation(
                   id, kind, passage_revision_id, run_id, token_count, padded_token_ids_json,
                   codes_json, level_lengths_json, codebook_sizes_json, model_profile,
                   execution_profile, tokenizer_fingerprint, generator_fingerprint,
                   display_policy, displayed_text_sha256, raw_token_ids_json,
                   retained_level_count, sampling_json, seed, source_representation_id,
                   candidate_index, hierarchy_available, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                representation_id,
                prepared["kind"],
                prepared["passage_revision_id"],
                prepared["run_id"],
                prepared["token_count"],
                _dump(prepared["padded_token_ids"]),
                _dump(prepared["codes"]),
                json.dumps(prepared["level_lengths"]),
                json.dumps(prepared["codebook_sizes"]),
                prepared["model_profile"],
                prepared["execution_profile"],
                prepared["tokenizer_fingerprint"],
                prepared["generator_fingerprint"],
                prepared["display_policy"],
                prepared["displayed_text_sha256"],
                _dump(prepared["raw_token_ids"]),
                prepared["retained_level_count"],
                _dump(prepared["sampling"]),
                prepared["seed"],
                prepared["source_representation_id"],
                prepared["candidate_index"],
                1 if prepared["hierarchy_available"] else 0,
                prepared["created_at"],
            ),
        )
        return representation_id

    def _read_text(self, digest: str) -> str:
        return self.read_asset_bytes(digest).decode("utf-8")

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
        items = [self._revision_from_row(row, parents) for row in rows]
        # Work candidates stay on the work. The desk history lists desk passages.
        return [item for item in items if item["origin_kind"] != "candidate"]

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
        revision_id = _new_id()
        created = _now()
        with self.immediate_transaction() as conn:
            if make_source:
                source_id = _new_id()
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
            self.insert_revision(
                conn,
                revision_id=revision_id,
                text_sha256=digest,
                origin_kind=origin_kind,
                source_id=source_id,
                created_at=created,
            )
            if parent_id and relationship:
                self.insert_provenance(
                    conn,
                    child_id=revision_id,
                    parent_id=parent_id,
                    relationship=relationship,
                    run_id=run_id,
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
        with self.immediate_transaction() as conn:
            self.insert_run(conn, run_id, operation, passage_revision_id, parameters, _now())
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

    def save_source_run(
        self,
        *,
        operation: str,
        passage_revision_id: str,
        parameters: dict,
        token_count: int,
        codes: list[int],
        padded_token_ids: list[int],
        level_lengths: list[int],
        codebook_sizes: list[int],
        model_profile: str,
        execution_profile: str,
        tokenizer_fingerprint: str,
        generator_fingerprint: str,
        display_policy: str | None,
    ) -> tuple[str, str]:
        """Store a run and its source encoding together. The encoding id is the representation id."""
        run_id = _new_id()
        representation_id = _new_id()
        created = _now()
        with self.immediate_transaction() as conn:
            self.insert_run(conn, run_id, operation, passage_revision_id, parameters, created)
            self.insert_encoding(
                conn,
                representation_id,
                passage_revision_id,
                token_count,
                [int(code) for code in codes],
                [int(token) for token in padded_token_ids],
                run_id,
            )
            self.insert_representation(
                conn,
                {
                    "id": representation_id,
                    "kind": "source_encoding",
                    "passage_revision_id": passage_revision_id,
                    "run_id": run_id,
                    "token_count": token_count,
                    "padded_token_ids": [int(token) for token in padded_token_ids],
                    "codes": [int(code) for code in codes],
                    "level_lengths": [int(level) for level in level_lengths],
                    "codebook_sizes": [int(size) for size in codebook_sizes],
                    "model_profile": model_profile,
                    "execution_profile": execution_profile,
                    "tokenizer_fingerprint": tokenizer_fingerprint,
                    "generator_fingerprint": generator_fingerprint,
                    "display_policy": display_policy,
                    "hierarchy_available": True,
                    "created_at": created,
                },
            )
        return run_id, representation_id

    def save_generated_candidate(
        self,
        text: str,
        *,
        parent_id: str,
        run_id: str,
        codes: list[int],
        level_lengths: list[int],
        codebook_sizes: list[int],
        raw_token_ids: list[int],
        retained_level_count: int,
        sampling: dict | None,
        seed: int,
        source_representation_id: str,
        candidate_index: int,
        model_profile: str,
        execution_profile: str,
        tokenizer_fingerprint: str,
        generator_fingerprint: str,
        display_policy: str | None,
    ) -> dict:
        """Commit one generated passage and its sampled hierarchy in one transaction."""
        digest = self._write_text(text)
        revision_id = _new_id()
        representation_id = _new_id()
        created = _now()
        with self.immediate_transaction() as conn:
            parent = conn.execute(
                "SELECT source_id FROM passage_revision WHERE id=?",
                (parent_id,),
            ).fetchone()
            if parent is None:
                raise ProjectError("NOT_FOUND", "The parent passage is not in this project.", status=404)
            self.insert_revision(
                conn,
                revision_id=revision_id,
                text_sha256=digest,
                origin_kind="generated",
                source_id=parent["source_id"],
                created_at=created,
            )
            self.insert_provenance(
                conn,
                child_id=revision_id,
                parent_id=parent_id,
                relationship="generated_from",
                run_id=run_id,
            )
            self.insert_representation(
                conn,
                {
                    "id": representation_id,
                    "kind": "sampled_hierarchy",
                    "passage_revision_id": revision_id,
                    "run_id": run_id,
                    "codes": [int(code) for code in codes],
                    "level_lengths": [int(level) for level in level_lengths],
                    "codebook_sizes": [int(size) for size in codebook_sizes],
                    "raw_token_ids": [int(token) for token in raw_token_ids],
                    "retained_level_count": retained_level_count,
                    "sampling": sampling,
                    "seed": seed,
                    "source_representation_id": source_representation_id,
                    "candidate_index": candidate_index,
                    "model_profile": model_profile,
                    "execution_profile": execution_profile,
                    "tokenizer_fingerprint": tokenizer_fingerprint,
                    "generator_fingerprint": generator_fingerprint,
                    "display_policy": display_policy,
                    "displayed_text_sha256": digest,
                    "hierarchy_available": True,
                    "created_at": created,
                },
            )
        revision = self.revision(revision_id)
        revision["representation_id"] = representation_id
        return revision

    def representation(self, representation_id: str) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM representation WHERE id=?",
                (representation_id,),
            ).fetchone()
        if row is None:
            raise ProjectError("NOT_FOUND", "That representation is not in this project.", status=404)
        return _representation_from_row(row)

    def representations_for(self, revision_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM representation WHERE passage_revision_id=? ORDER BY created_at, rowid",
                (revision_id,),
            ).fetchall()
        return [_representation_from_row(row) for row in rows]

    def sampled_hierarchy(self, revision_id: str) -> dict:
        rows = [
            item
            for item in self.representations_for(revision_id)
            if item["kind"] == "sampled_hierarchy"
        ]
        available = [item for item in rows if item["hierarchy_available"]]
        if len(available) == 1:
            return available[0]
        if rows:
            raise ProjectError(
                "HIERARCHY_UNAVAILABLE",
                "The sampled hierarchy for this passage was not saved. Encoding the displayed text is a different operation.",
                {"passage_revision_id": revision_id},
                status=409,
            )
        raise ProjectError(
            "HIERARCHY_UNAVAILABLE",
            "This passage has no sampled hierarchy. Encoding the displayed text is a different operation.",
            {"passage_revision_id": revision_id},
            status=409,
        )

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

    def latest_succeeded(self, operation: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM job WHERE operation=? AND state='succeeded'
                   ORDER BY created_at DESC LIMIT 1""",
                (operation,),
            ).fetchone()
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


def _dump(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _load(value: str | None):
    if value is None:
        return None
    return json.loads(value)


def _ints(value, label: str) -> list[int]:
    if not isinstance(value, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ProjectError("INVALID_REPRESENTATION", f"{label} must be a list of integers.")
    return [int(item) for item in value]


def _prepare_representation(fields: dict) -> dict:
    kind = fields.get("kind")
    if kind not in {"source_encoding", "sampled_hierarchy"}:
        raise ProjectError("INVALID_REPRESENTATION", "Unknown representation kind.")
    available = bool(fields.get("hierarchy_available"))
    token_count = fields.get("token_count")
    padded = fields.get("padded_token_ids")
    codes = fields.get("codes")
    if kind == "source_encoding":
        if token_count is None or padded is None or codes is None or not available:
            raise ProjectError(
                "INVALID_REPRESENTATION",
                "A source encoding needs its token count, padded token ids, and codes.",
            )
    if kind == "sampled_hierarchy":
        if token_count is not None or padded is not None:
            raise ProjectError(
                "INVALID_REPRESENTATION",
                "A sampled hierarchy does not take a source token count or padded input.",
            )
        if available and fields.get("raw_token_ids") is None:
            raise ProjectError(
                "INVALID_REPRESENTATION",
                "A saved sampled hierarchy needs its raw decoded token ids.",
            )
    level_lengths = _ints(fields.get("level_lengths"), "Level lengths")
    codebook_sizes = _ints(fields.get("codebook_sizes"), "Codebook sizes")
    if available:
        codes = _ints(codes, "Codes")
        if sum(level_lengths) != len(codes):
            raise ProjectError(
                "INVALID_REPRESENTATION",
                "Code length does not match the level layout.",
                {"codes": len(codes), "level_lengths": level_lengths},
            )
        if len(level_lengths) != len(codebook_sizes):
            raise ProjectError("INVALID_REPRESENTATION", "Level lengths and codebook sizes disagree.")
    elif codes is not None:
        codes = _ints(codes, "Codes")
    if padded is not None:
        padded = _ints(padded, "Padded token ids")
    raw_token_ids = fields.get("raw_token_ids")
    if raw_token_ids is not None:
        raw_token_ids = _ints(raw_token_ids, "Raw token ids")
    if not fields.get("passage_revision_id") or not fields.get("model_profile") or not fields.get("execution_profile"):
        raise ProjectError("INVALID_REPRESENTATION", "A representation needs a passage, model, and execution profile.")
    if not fields.get("created_at"):
        raise ProjectError("INVALID_REPRESENTATION", "A representation needs a creation time.")
    return {
        "id": fields.get("id") or _new_id(),
        "kind": kind,
        "passage_revision_id": fields["passage_revision_id"],
        "run_id": fields.get("run_id"),
        "token_count": None if token_count is None else int(token_count),
        "padded_token_ids": padded,
        "codes": codes,
        "level_lengths": level_lengths,
        "codebook_sizes": codebook_sizes,
        "model_profile": fields["model_profile"],
        "execution_profile": fields["execution_profile"],
        "tokenizer_fingerprint": fields.get("tokenizer_fingerprint") or "",
        "generator_fingerprint": fields.get("generator_fingerprint") or "",
        "display_policy": fields.get("display_policy"),
        "displayed_text_sha256": fields.get("displayed_text_sha256"),
        "raw_token_ids": raw_token_ids,
        "retained_level_count": fields.get("retained_level_count"),
        "sampling": fields.get("sampling"),
        "seed": fields.get("seed"),
        "source_representation_id": fields.get("source_representation_id"),
        "candidate_index": fields.get("candidate_index"),
        "hierarchy_available": available,
        "created_at": fields["created_at"],
    }


def _representation_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "passage_revision_id": row["passage_revision_id"],
        "run_id": row["run_id"],
        "token_count": row["token_count"],
        "padded_token_ids": _load(row["padded_token_ids_json"]),
        "codes": _load(row["codes_json"]),
        "level_lengths": json.loads(row["level_lengths_json"]),
        "codebook_sizes": json.loads(row["codebook_sizes_json"]),
        "model_profile": row["model_profile"],
        "execution_profile": row["execution_profile"],
        "tokenizer_fingerprint": row["tokenizer_fingerprint"],
        "generator_fingerprint": row["generator_fingerprint"],
        "display_policy": row["display_policy"],
        "displayed_text_sha256": row["displayed_text_sha256"],
        "raw_token_ids": _load(row["raw_token_ids_json"]),
        "retained_level_count": row["retained_level_count"],
        "sampling": _load(row["sampling_json"]),
        "seed": row["seed"],
        "source_representation_id": row["source_representation_id"],
        "candidate_index": row["candidate_index"],
        "hierarchy_available": bool(row["hierarchy_available"]),
        "created_at": row["created_at"],
    }
