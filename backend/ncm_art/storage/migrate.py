"""Versioned project upgrades.

The database schema version is the recovery authority. A backup is taken before
the first upgrade away from the writing-desk schema, and the manifest is
replaced only after that upgrade commits.
"""

import json
import shutil
import sqlite3
import uuid
from pathlib import Path

from ncm_art import __version__
from ncm_art.model_adapter.profile import CODEBOOK_SIZE, LEVELS
from ncm_art.storage.errors import ProjectError

SCHEMA_VERSION = 4
BASELINE_VERSION = 1

REPRESENTATION_TABLE = """
CREATE TABLE representation (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('source_encoding', 'sampled_hierarchy')),
    passage_revision_id TEXT NOT NULL,
    run_id TEXT,
    token_count INTEGER,
    padded_token_ids_json TEXT,
    codes_json TEXT,
    level_lengths_json TEXT NOT NULL,
    codebook_sizes_json TEXT NOT NULL,
    model_profile TEXT NOT NULL,
    execution_profile TEXT NOT NULL,
    tokenizer_fingerprint TEXT NOT NULL DEFAULT '',
    generator_fingerprint TEXT NOT NULL DEFAULT '',
    display_policy TEXT,
    displayed_text_sha256 TEXT,
    raw_token_ids_json TEXT,
    retained_level_count INTEGER,
    sampling_json TEXT,
    seed INTEGER,
    source_representation_id TEXT,
    candidate_index INTEGER,
    hierarchy_available INTEGER NOT NULL CHECK (hierarchy_available IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (passage_revision_id) REFERENCES passage_revision(id),
    FOREIGN KEY (run_id) REFERENCES run(id),
    FOREIGN KEY (source_representation_id) REFERENCES representation(id)
);
"""

REPRESENTATION_INDEX = """
CREATE INDEX representation_by_revision ON representation(passage_revision_id);
"""

BASE_TABLES = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE source_document (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    origin_kind TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE passage_revision (
    id TEXT PRIMARY KEY,
    text_sha256 TEXT NOT NULL,
    origin_kind TEXT NOT NULL,
    source_id TEXT,
    created_at TEXT NOT NULL,
    disposition TEXT
);
CREATE TABLE provenance_edge (
    id TEXT PRIMARY KEY,
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    run_id TEXT
);
CREATE TABLE editor_draft (
    id TEXT PRIMARY KEY,
    base_revision_id TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE run (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    passage_revision_id TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE encoding (
    id TEXT PRIMARY KEY,
    passage_revision_id TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    codes_json TEXT NOT NULL,
    padded_token_ids_json TEXT NOT NULL,
    run_id TEXT NOT NULL
);
CREATE TABLE reconstruction (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    encoding_id TEXT NOT NULL,
    frames_json TEXT NOT NULL
);
CREATE TABLE annotation (
    id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE job (
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


CORRESPONDENCE_DDL = """
ALTER TABLE source_document ADD COLUMN family_id TEXT;
ALTER TABLE source_document ADD COLUMN author TEXT;
ALTER TABLE source_document ADD COLUMN source_uri TEXT;
ALTER TABLE source_document ADD COLUMN source_date TEXT;
ALTER TABLE source_document ADD COLUMN language TEXT;
ALTER TABLE source_document ADD COLUMN edition TEXT;
ALTER TABLE source_document ADD COLUMN collection TEXT NOT NULL DEFAULT 'desk';
ALTER TABLE source_document ADD COLUMN filename TEXT;
ALTER TABLE source_document ADD COLUMN media_type TEXT;
ALTER TABLE source_document ADD COLUMN byte_length INTEGER;
CREATE TABLE source_fragment (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    parent_fragment_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('paragraph', 'window')),
    ordinal INTEGER NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    slice_sha256 TEXT NOT NULL,
    source_text_sha256 TEXT NOT NULL,
    segmentation_method TEXT NOT NULL,
    segmentation_version TEXT NOT NULL,
    profile_id TEXT,
    token_count INTEGER,
    token_limit INTEGER,
    special_tokens_included INTEGER,
    preprocessing_policy TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES source_document(id),
    FOREIGN KEY (parent_fragment_id) REFERENCES source_fragment(id)
);
CREATE INDEX source_fragment_by_source ON source_fragment(source_id, ordinal);
CREATE TABLE corpus_snapshot (
    id TEXT PRIMARY KEY,
    collection TEXT NOT NULL,
    status TEXT NOT NULL,
    fragment_ids_json TEXT NOT NULL,
    profile_fingerprint TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE fragment_fts USING fts5(
    fragment_id UNINDEXED,
    source_id UNINDEXED,
    body,
    tokenize = "unicode61 remove_diacritics 0"
);
CREATE TABLE correspondence (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    disposition TEXT NOT NULL CHECK (disposition IN ('open', 'retained', 'set_aside', 'rejected')),
    encounter_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE correspondence_member (
    id TEXT PRIMARY KEY,
    correspondence_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    text_sha256 TEXT NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    slice_sha256 TEXT NOT NULL,
    UNIQUE (correspondence_id, ordinal),
    FOREIGN KEY (correspondence_id) REFERENCES correspondence(id)
);
CREATE TABLE interpretation_revision (
    id TEXT PRIMARY KEY,
    correspondence_id TEXT NOT NULL,
    body TEXT NOT NULL,
    producer TEXT NOT NULL CHECK (producer IN ('artist', 'model', 'adapted')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (correspondence_id) REFERENCES correspondence(id)
);
CREATE TABLE encounter (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT,
    recipe_json TEXT NOT NULL,
    query_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE encounter_hit (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    view TEXT NOT NULL,
    fragment_id TEXT,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    slice_sha256 TEXT NOT NULL,
    score REAL,
    reason TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    FOREIGN KEY (encounter_id) REFERENCES encounter(id)
);
CREATE TABLE embedding (
    id TEXT PRIMARY KEY,
    fragment_id TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    profile_fingerprint TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (input_sha256, profile_fingerprint)
);
"""

WORK_DDL = """
CREATE TABLE work (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    binding_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE work_entry (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    passage_revision_id TEXT NOT NULL,
    removed_at TEXT,
    FOREIGN KEY (work_id) REFERENCES work(id),
    FOREIGN KEY (passage_revision_id) REFERENCES passage_revision(id)
);
CREATE TABLE work_entry_draft (
    work_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (work_id, entry_id),
    FOREIGN KEY (work_id) REFERENCES work(id),
    FOREIGN KEY (entry_id) REFERENCES work_entry(id)
);
CREATE TABLE influence (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE influence_version (
    id TEXT PRIMARY KEY,
    influence_id TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    name TEXT NOT NULL,
    interpretation TEXT NOT NULL,
    template TEXT,
    parameters_json TEXT NOT NULL,
    correspondence_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (influence_id, version_number),
    FOREIGN KEY (influence_id) REFERENCES influence(id),
    FOREIGN KEY (correspondence_id) REFERENCES correspondence(id)
);
CREATE TABLE work_binding (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    influence_version_id TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    unbound_at TEXT,
    FOREIGN KEY (work_id) REFERENCES work(id),
    FOREIGN KEY (influence_version_id) REFERENCES influence_version(id)
);
CREATE UNIQUE INDEX work_one_active_binding ON work_binding(work_id) WHERE active = 1;
CREATE TABLE operation_preview (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    operation_version TEXT NOT NULL,
    request_json TEXT NOT NULL,
    work_state_version INTEGER NOT NULL,
    binding_id TEXT,
    influence_version_id TEXT,
    base_revision_id TEXT NOT NULL,
    final_revision_id TEXT NOT NULL,
    destination_json TEXT NOT NULL,
    effects_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (work_id) REFERENCES work(id),
    FOREIGN KEY (base_revision_id) REFERENCES passage_revision(id),
    FOREIGN KEY (final_revision_id) REFERENCES passage_revision(id)
);
CREATE TABLE application_receipt (
    id TEXT PRIMARY KEY,
    client_request_id TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    preview_id TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (preview_id) REFERENCES operation_preview(id)
);
CREATE TABLE work_event (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    action TEXT NOT NULL,
    preview_id TEXT,
    receipt_id TEXT,
    old_state_version INTEGER,
    new_state_version INTEGER NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (work_id) REFERENCES work(id)
);
CREATE TABLE held_name (
    id TEXT PRIMARY KEY,
    work_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('held', 'returned')),
    target_state TEXT NOT NULL CHECK (target_state IN ('resolved', 'unresolved', 'detached')),
    donor_owner_kind TEXT NOT NULL,
    donor_owner_id TEXT NOT NULL,
    donor_start INTEGER NOT NULL,
    donor_end INTEGER NOT NULL,
    donor_text TEXT NOT NULL,
    donor_text_sha256 TEXT NOT NULL,
    receiving_revision_id TEXT NOT NULL,
    placeholder_start INTEGER NOT NULL,
    placeholder_end INTEGER NOT NULL,
    placeholder_text TEXT NOT NULL,
    influence_version_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    returned_revision_id TEXT,
    target_start INTEGER,
    target_end INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (work_id) REFERENCES work(id),
    FOREIGN KEY (entry_id) REFERENCES work_entry(id),
    FOREIGN KEY (receiving_revision_id) REFERENCES passage_revision(id),
    FOREIGN KEY (influence_version_id) REFERENCES influence_version(id),
    FOREIGN KEY (event_id) REFERENCES work_event(id)
);
CREATE TABLE protected_range (
    id TEXT PRIMARY KEY,
    passage_revision_id TEXT NOT NULL,
    start_byte INTEGER NOT NULL,
    end_byte INTEGER NOT NULL,
    slice_sha256 TEXT NOT NULL,
    role TEXT NOT NULL,
    released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (passage_revision_id) REFERENCES passage_revision(id)
);
"""


def current_schema_script() -> str:
    return (
        BASE_TABLES
        + REPRESENTATION_TABLE
        + REPRESENTATION_INDEX
        + CORRESPONDENCE_DDL
        + WORK_DDL
        + f"INSERT INTO meta(key, value) VALUES ('schema_version', '{SCHEMA_VERSION}');\n"
    )


def write_manifest(root: Path, manifest: dict) -> None:
    payload = json.dumps(manifest, indent=2) + "\n"
    temporary = root / ".project.json.tmp"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(root / "project.json")


def read_schema_version(conn: sqlite3.Connection) -> int:
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "meta" not in tables:
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        if "passage_revision" in tables:
            return BASELINE_VERSION
        return 0
    value = row["value"] if isinstance(row, sqlite3.Row) else row[0]
    return int(value)


def install_schema(project) -> None:
    with project._conn() as conn:
        conn.executescript(current_schema_script())


def migrate_project(project) -> None:
    manifest = project.manifest()
    try:
        manifest_version = int(manifest["format_version"])
    except (KeyError, TypeError, ValueError) as error:
        raise ProjectError(
            "UNSUPPORTED_FORMAT",
            "This project manifest has no supported format version. It was not changed.",
            status=409,
        ) from error
    with project._conn() as conn:
        db_version = read_schema_version(conn)
    if manifest_version > SCHEMA_VERSION or db_version > SCHEMA_VERSION:
        found = max(manifest_version, db_version)
        raise ProjectError(
            "UNSUPPORTED_FORMAT",
            f"This project uses format {found}. This version of Openwound supports format {SCHEMA_VERSION}. The project was not changed.",
            {
                "format_version": manifest_version,
                "schema_version": db_version,
                "supported": SCHEMA_VERSION,
            },
            status=409,
        )
    while True:
        manifest = project.manifest()
        try:
            manifest_version = int(manifest["format_version"])
        except (KeyError, TypeError, ValueError) as error:
            raise ProjectError(
                "UNSUPPORTED_FORMAT",
                "This project manifest has no supported format version. It was not changed.",
                status=409,
            ) from error
        with project._conn() as conn:
            db_version = read_schema_version(conn)
        if manifest_version > SCHEMA_VERSION or db_version > SCHEMA_VERSION:
            found = max(manifest_version, db_version)
            raise ProjectError(
                "UNSUPPORTED_FORMAT",
                f"This project uses format {found}. This version of Openwound supports format {SCHEMA_VERSION}. The project was not changed.",
                {
                    "format_version": manifest_version,
                    "schema_version": db_version,
                    "supported": SCHEMA_VERSION,
                },
                status=409,
            )
        if db_version == SCHEMA_VERSION and manifest_version == SCHEMA_VERSION:
            return
        if db_version == SCHEMA_VERSION and manifest_version < SCHEMA_VERSION:
            _write_current_manifest(project, manifest)
            return
        if db_version < BASELINE_VERSION:
            raise ProjectError(
                "UNSUPPORTED_FORMAT",
                "This project database has no supported schema. It was not changed.",
                {"schema_version": db_version},
                status=409,
            )
        _backup_version(project, db_version)
        try:
            with project.immediate_transaction() as conn:
                current = read_schema_version(conn)
                if current > SCHEMA_VERSION:
                    raise ProjectError(
                        "UNSUPPORTED_FORMAT",
                        f"This project uses format {current}. This version of Openwound supports format {SCHEMA_VERSION}. The project was not changed.",
                        {"schema_version": current, "supported": SCHEMA_VERSION},
                        status=409,
                    )
                if current < SCHEMA_VERSION:
                    _apply_migration(conn, current)
                    conn.execute(
                        """INSERT INTO meta(key, value) VALUES ('schema_version', ?)
                           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                        (str(current + 1),),
                    )
        except ProjectError:
            raise
        except Exception as error:
            raise ProjectError(
                "MIGRATION_FAILED",
                "The project could not be upgraded. The previous copy is unchanged.",
                {"reason": str(error)},
                status=500,
            ) from error


def _write_current_manifest(project, manifest: dict) -> None:
    updated = dict(manifest)
    updated["format_version"] = SCHEMA_VERSION
    updated["app_version"] = __version__
    write_manifest(project.root, updated)


def _apply_migration(conn: sqlite3.Connection, version: int) -> None:
    if version == 1:
        _migrate_1_to_2(conn)
    elif version == 2:
        _migrate_2_to_3(conn)
    elif version == 3:
        _migrate_3_to_4(conn)
    else:
        raise ProjectError(
            "MIGRATION_FAILED",
            "This project schema cannot be upgraded.",
            {"schema_version": version},
            status=500,
        )


def _sql_statements(script: str) -> list[str]:
    return [statement.strip() for statement in script.split(";") if statement.strip()]


def _migrate_2_to_3(conn: sqlite3.Connection) -> None:
    for statement in _sql_statements(CORRESPONDENCE_DDL):
        conn.execute(statement)


def _migrate_3_to_4(conn: sqlite3.Connection) -> None:
    for statement in _sql_statements(WORK_DDL):
        conn.execute(statement)


def _backup_version(project, version: int) -> None:
    final = project.root / "backups" / f"schema-{version}"
    if (final / "complete").is_file():
        return
    staging = project.root / "backups" / f".schema-{version}-{uuid.uuid4()}"
    staging.mkdir(parents=True)
    try:
        shutil.copy2(project.root / "project.json", staging / "project.json")
        _backup_database(project, staging / "project.sqlite")
        if project.asset_dir.is_dir():
            shutil.copytree(project.asset_dir, staging / "assets", dirs_exist_ok=True)
        (staging / "complete").write_text(f"schema-{version}\n", encoding="utf-8")
        try:
            staging.rename(final)
        except OSError:
            if (final / "complete").is_file():
                shutil.rmtree(staging, ignore_errors=True)
            else:
                raise
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _backup_database(project, destination: Path) -> None:
    source = project._conn()
    try:
        copied = sqlite3.connect(destination)
        try:
            source.backup(copied)
        finally:
            copied.close()
    finally:
        source.close()


def _migrate_1_to_2(conn: sqlite3.Connection) -> None:
    conn.execute(REPRESENTATION_TABLE)
    conn.execute(REPRESENTATION_INDEX)
    revisions = {
        row["id"]: row
        for row in conn.execute("SELECT id, text_sha256, created_at, origin_kind FROM passage_revision")
    }
    runs = {row["id"]: row for row in conn.execute("SELECT * FROM run")}
    skipped: list[str] = []
    for row in conn.execute("SELECT * FROM encoding"):
        if row["passage_revision_id"] not in revisions or row["run_id"] not in runs:
            skipped.append(row["id"])
            continue
        codes, padded, usable = _legacy_code_arrays(row["codes_json"], row["padded_token_ids_json"])
        if not usable or codes is None or padded is None:
            skipped.append(row["id"])
            continue
        run = runs[row["run_id"]]
        parameters = _object(run["parameters_json"])
        level_lengths, codebook_sizes = _legacy_layout(codes, parameters)
        created = run["created_at"]
        conn.execute(
            """INSERT INTO representation(
                   id, kind, passage_revision_id, run_id, token_count, padded_token_ids_json,
                   codes_json, level_lengths_json, codebook_sizes_json, model_profile,
                   execution_profile, tokenizer_fingerprint, generator_fingerprint,
                   display_policy, displayed_text_sha256, raw_token_ids_json,
                   retained_level_count, sampling_json, seed, source_representation_id,
                   candidate_index, hierarchy_available, created_at
               ) VALUES (?, 'source_encoding', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL,
                         NULL, NULL, NULL, NULL, NULL, 1, ?)""",
            (
                row["id"],
                row["passage_revision_id"],
                row["run_id"],
                row["token_count"],
                json.dumps(padded),
                json.dumps(codes),
                json.dumps(level_lengths),
                json.dumps(codebook_sizes),
                str(parameters.get("model_profile") or "tinystories-v1"),
                str(parameters.get("execution_profile") or "cpu-fp32-eager-v1"),
                _fingerprint(parameters, "tokenizer.pt"),
                _fingerprint(parameters, "generator.pt"),
                parameters.get("display_policy"),
                created,
            ),
        )
    seen: set[str] = set()
    for job in conn.execute("SELECT * FROM job WHERE operation='variants'"):
        result = _object(job["result_json"]) if job["result_json"] else {}
        request = _object(job["request_json"])
        for candidate in result.get("candidates") or []:
            revision_id = candidate.get("revision_id")
            if not revision_id or revision_id in seen or revision_id not in revisions:
                continue
            _insert_unavailable_hierarchy(
                conn,
                revisions[revision_id],
                request,
                candidate.get("seed"),
                candidate.get("index"),
                _run_id_for(conn, revision_id),
                runs,
            )
            seen.add(revision_id)
    for revision in revisions.values():
        if revision["origin_kind"] != "generated" or revision["id"] in seen:
            continue
        _insert_unavailable_hierarchy(
            conn,
            revision,
            {},
            None,
            None,
            _run_id_for(conn, revision["id"]),
            runs,
        )
        seen.add(revision["id"])
    if skipped:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('legacy_encodings_unmigrated', ?)",
            (json.dumps(skipped),),
        )


def _insert_unavailable_hierarchy(conn, revision, request: dict, seed, candidate_index, run_id, runs) -> None:
    parameters = {}
    created = revision["created_at"]
    if run_id and run_id in runs:
        parameters = _object(runs[run_id]["parameters_json"])
        created = runs[run_id]["created_at"]
    model_profile = str(parameters.get("model_profile") or request.get("model_profile_id") or "tinystories-v1")
    if model_profile == "tinystories-v1":
        level_lengths = list(LEVELS)
        codebook_sizes = [CODEBOOK_SIZE] * len(LEVELS)
    else:
        level_lengths = []
        codebook_sizes = []
    sampling = request.get("sampling")
    if sampling is None:
        sampling = parameters.get("sampling")
    retained = request.get("retained_level_count")
    if retained is None:
        retained = parameters.get("retained_level_count")
    conn.execute(
        """INSERT INTO representation(
               id, kind, passage_revision_id, run_id, token_count, padded_token_ids_json,
               codes_json, level_lengths_json, codebook_sizes_json, model_profile,
               execution_profile, tokenizer_fingerprint, generator_fingerprint,
               display_policy, displayed_text_sha256, raw_token_ids_json,
               retained_level_count, sampling_json, seed, source_representation_id,
               candidate_index, hierarchy_available, created_at
           ) VALUES (?, 'sampled_hierarchy', ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                     ?, ?, ?, NULL, ?, 0, ?)""",
        (
            str(uuid.uuid4()),
            revision["id"],
            run_id if run_id in runs else None,
            json.dumps(level_lengths),
            json.dumps(codebook_sizes),
            model_profile,
            str(parameters.get("execution_profile") or request.get("execution_profile_id") or "cpu-fp32-eager-v1"),
            _fingerprint(parameters, "tokenizer.pt"),
            _fingerprint(parameters, "generator.pt"),
            parameters.get("display_policy"),
            revision["text_sha256"],
            retained,
            json.dumps(sampling) if sampling is not None else None,
            seed,
            candidate_index,
            created,
        ),
    )


def _run_id_for(conn, revision_id: str) -> str | None:
    row = conn.execute(
        """SELECT run_id FROM provenance_edge
           WHERE child_id=? AND relationship='generated_from' AND run_id IS NOT NULL
           ORDER BY rowid LIMIT 1""",
        (revision_id,),
    ).fetchone()
    if row is None:
        return None
    return row["run_id"]


def _legacy_code_arrays(codes_json: str, padded_json: str) -> tuple[list[int] | None, list[int] | None, bool]:
    codes = _int_list(codes_json)
    padded = _int_list(padded_json)
    if codes is None or padded is None:
        return None, None, False
    return codes, padded, True


def _legacy_layout(codes: list[int], parameters: dict) -> tuple[list[int], list[int]]:
    profile = parameters.get("model_profile") or "tinystories-v1"
    if profile == "tinystories-v1" and len(codes) == sum(LEVELS):
        return list(LEVELS), [CODEBOOK_SIZE] * len(LEVELS)
    return [], []


def _int_list(payload: str | None) -> list[int] | None:
    if payload is None:
        return None
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, list):
        return None
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        return None
    return [int(item) for item in value]


def _object(payload: str | None) -> dict:
    if not payload:
        return {}
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _fingerprint(parameters: dict, name: str) -> str:
    hashes = parameters.get("artifact_sha256")
    if not isinstance(hashes, dict):
        return ""
    value = hashes.get(name)
    return value if isinstance(value, str) else ""
