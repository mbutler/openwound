"""Import immutable UTF-8 sources and keep paragraph fragments exact."""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ncm_art.corpus.anchors import find_occurrences, make_anchor, string_span_to_bytes, validate_span
from ncm_art.corpus.segment import PARAGRAPH_SEGMENTATION, WINDOW_SEGMENTATION, paragraph_spans, window_spans
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.project import Project

ACCEPTED_SUFFIXES = {".txt", ".md"}


@dataclass
class WindowBudget:
    profile_id: str
    limit: int
    special_tokens_included: bool
    count: Callable[[str], int]
    preprocessing_policy: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def default_budgets() -> list[WindowBudget]:
    budgets = []
    try:
        from ncm_art.tokenize import POLICY, preview_tokens

        budgets.append(
            WindowBudget(
                profile_id="tinystories-v1",
                limit=preview_tokens("a")["text_length"],
                special_tokens_included=False,
                count=lambda text: preview_tokens(text)["token_count"],
                preprocessing_policy=POLICY,
            )
        )
    except Exception:
        pass
    return budgets


def import_bytes(
    project: Project,
    data: bytes,
    *,
    title: str,
    author: str | None = None,
    source_uri: str | None = None,
    source_date: str | None = None,
    language: str | None = None,
    edition: str | None = None,
    notes: str = "",
    family_id: str | None = None,
    filename: str | None = None,
    media_type: str | None = None,
    budgets: list[WindowBudget] | None = None,
) -> dict:
    if filename:
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if suffix not in ACCEPTED_SUFFIXES:
            raise ProjectError(
                "INVALID_TEXT",
                "Import a UTF-8 .txt or .md file, or paste plain text.",
                {"filename": filename},
            )
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError(
            "INVALID_TEXT",
            "That file is not valid UTF-8. Nothing was changed.",
            {"reason": str(error)},
        ) from error
    if data == b"":
        raise ProjectError("INVALID_TEXT", "The source is empty.")
    digest = project.write_asset_bytes(data)
    source_id = _new_id()
    family = family_id or _new_id()
    created = _now()
    chosen = default_budgets() if budgets is None else budgets
    paragraphs = paragraph_spans(data)
    with project.immediate_transaction() as conn:
        conn.execute(
            """INSERT INTO source_document(
                   id, title, origin_kind, text_sha256, notes, created_at, family_id, author,
                   source_uri, source_date, language, edition, collection, filename, media_type, byte_length
               ) VALUES (?, ?, 'imported', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'imported', ?, ?, ?)""",
            (
                source_id,
                title.strip() or filename or "Untitled source",
                digest,
                notes,
                created,
                family,
                author or None,
                source_uri or None,
                source_date or None,
                language or None,
                edition or None,
                filename,
                media_type,
                len(data),
            ),
        )
        window_count = 0
        for ordinal, (start, end) in enumerate(paragraphs):
            paragraph_id = _new_id()
            paragraph_text = data[start:end].decode("utf-8")
            _insert_fragment(
                conn,
                fragment_id=paragraph_id,
                source_id=source_id,
                parent_fragment_id=None,
                kind="paragraph",
                ordinal=ordinal,
                start=start,
                end=end,
                raw=data,
                segmentation_method="paragraph",
                segmentation_version=PARAGRAPH_SEGMENTATION,
                profile_id=None,
                token_count=None,
                token_limit=None,
                special_tokens_included=None,
                preprocessing_policy="exact-utf8-v1",
                created_at=created,
            )
            children = _windows_for(conn, data, source_id, paragraph_id, paragraph_text, start, chosen, created)
            window_count += len(children)
            if not children:
                _index_fragment(conn, paragraph_id, source_id, paragraph_text)
        _replace_imported_snapshot(conn, created)
    return {
        "id": source_id,
        "family_id": family,
        "title": title.strip() or filename or "Untitled source",
        "text_sha256": digest,
        "byte_length": len(data),
        "fragment_count": len(paragraphs),
        "window_count": window_count,
        "created_at": created,
    }


def _windows_for(conn, raw: bytes, source_id: str, paragraph_id: str, text: str, base: int, budgets, created: str) -> list[str]:
    created_ids = []
    ordinal = 0
    seen: set[tuple[int, int, str]] = set()
    for budget in budgets:
        spans = window_spans(text, budget.count, budget.limit)
        if spans is None:
            continue
        for start, end in spans:
            byte_start, byte_end = string_span_to_bytes(text, start, end, base)
            key = (byte_start, byte_end, budget.profile_id)
            if key in seen:
                continue
            seen.add(key)
            fragment_id = _new_id()
            piece = text[start:end]
            _insert_fragment(
                conn,
                fragment_id=fragment_id,
                source_id=source_id,
                parent_fragment_id=paragraph_id,
                kind="window",
                ordinal=ordinal,
                start=byte_start,
                end=byte_end,
                raw=raw,
                segmentation_method="window",
                segmentation_version=WINDOW_SEGMENTATION,
                profile_id=budget.profile_id,
                token_count=budget.count(piece),
                token_limit=budget.limit,
                special_tokens_included=1 if budget.special_tokens_included else 0,
                preprocessing_policy=budget.preprocessing_policy,
                created_at=created,
            )
            _index_fragment(conn, fragment_id, source_id, piece)
            created_ids.append(fragment_id)
            ordinal += 1
    return created_ids


def _insert_fragment(conn, *, fragment_id, source_id, parent_fragment_id, kind, ordinal, start, end, raw, segmentation_method, segmentation_version, profile_id, token_count, token_limit, special_tokens_included, preprocessing_policy, created_at) -> None:
    selected = validate_span(raw, start, end)
    conn.execute(
        """INSERT INTO source_fragment(
               id, source_id, parent_fragment_id, kind, ordinal, start_byte, end_byte, slice_sha256,
               source_text_sha256, segmentation_method, segmentation_version, profile_id, token_count,
               token_limit, special_tokens_included, preprocessing_policy, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fragment_id,
            source_id,
            parent_fragment_id,
            kind,
            ordinal,
            start,
            end,
            hashlib.sha256(selected).hexdigest(),
            hashlib.sha256(raw).hexdigest(),
            segmentation_method,
            segmentation_version,
            profile_id,
            token_count,
            token_limit,
            special_tokens_included,
            preprocessing_policy,
            created_at,
        ),
    )


def _index_fragment(conn, fragment_id: str, source_id: str, text: str) -> None:
    conn.execute(
        "INSERT INTO fragment_fts(fragment_id, source_id, body) VALUES (?, ?, ?)",
        (fragment_id, source_id, text),
    )


def _replace_imported_snapshot(conn, created: str) -> None:
    rows = conn.execute(
        """SELECT f.id FROM source_fragment f
           JOIN source_document s ON s.id = f.source_id
           WHERE s.collection = 'imported'
             AND (
               f.kind = 'window'
               OR (f.kind = 'paragraph' AND NOT EXISTS (
                   SELECT 1 FROM source_fragment child WHERE child.parent_fragment_id = f.id
               ))
             )
           ORDER BY f.id"""
    ).fetchall()
    leaf_ids = [row["id"] for row in rows]
    conn.execute(
        """INSERT INTO corpus_snapshot(id, collection, status, fragment_ids_json, profile_fingerprint, created_at)
           VALUES (?, 'imported', 'ready', ?, '', ?)""",
        (_new_id(), json.dumps(leaf_ids), created),
    )


def record_model_windows(project: Project, budget: WindowBudget) -> int:
    """Replace an over-length paragraph leaf with explicit windows.

    The paragraph row stays. Search moves to the windows. Nothing is truncated.
    """
    with project._conn() as conn:
        rows = conn.execute(
            """SELECT f.* FROM source_fragment f
               JOIN source_document s ON s.id = f.source_id
               WHERE s.collection = 'imported' AND f.kind = 'paragraph'
                 AND NOT EXISTS (
                   SELECT 1 FROM source_fragment child WHERE child.parent_fragment_id = f.id
                 )"""
        ).fetchall()
    created = 0
    for row in rows:
        raw = project.read_asset_bytes(row["source_text_sha256"])
        text = raw[row["start_byte"] : row["end_byte"]].decode("utf-8")
        if budget.count(text) <= budget.limit:
            continue
        with project.immediate_transaction() as conn:
            ids = _windows_for(
                conn,
                raw,
                row["source_id"],
                row["id"],
                text,
                row["start_byte"],
                [budget],
                _now(),
            )
            if ids:
                conn.execute("DELETE FROM fragment_fts WHERE fragment_id = ?", (row["id"],))
                created += len(ids)
    if created:
        with project.immediate_transaction() as conn:
            _replace_imported_snapshot(conn, _now())
    return created


def list_sources(project: Project, *, limit: int = 50, cursor: str | None = None) -> dict:
    limit = _bound(limit, 50, 200)
    with project._conn() as conn:
        if cursor:
            created_at, source_id = cursor.split("\t", 1)
            rows = conn.execute(
                """SELECT * FROM source_document
                   WHERE collection = 'imported' AND (created_at > ? OR (created_at = ? AND id > ?))
                   ORDER BY created_at, id LIMIT ?""",
                (created_at, created_at, source_id, limit + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM source_document WHERE collection = 'imported'
                   ORDER BY created_at, id LIMIT ?""",
                (limit + 1,),
            ).fetchall()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = f"{last['created_at']}\t{last['id']}"
    return {"sources": [_source_summary(row) for row in page], "next_cursor": next_cursor}


def get_source(project: Project, source_id: str) -> dict:
    with project._conn() as conn:
        row = conn.execute("SELECT * FROM source_document WHERE id = ?", (source_id,)).fetchone()
    if row is None or row["collection"] != "imported":
        raise ProjectError("NOT_FOUND", "That source is not in this project.", status=404)
    summary = _source_summary(row)
    summary["text"] = project.read_asset_bytes(row["text_sha256"]).decode("utf-8")
    return summary


def list_fragments(project: Project, source_id: str, *, kind: str = "paragraph", limit: int = 30, cursor: int | None = None) -> dict:
    get_source_row(project, source_id)
    limit = _bound(limit, 30, 100)
    start_ordinal = 0 if cursor is None else cursor
    with project._conn() as conn:
        rows = conn.execute(
            """SELECT * FROM source_fragment
               WHERE source_id = ? AND kind = ? AND ordinal >= ?
               ORDER BY ordinal LIMIT ?""",
            (source_id, kind, start_ordinal, limit + 1),
        ).fetchall()
        page = rows[:limit]
        items = []
        for row in page:
            windows = conn.execute(
                "SELECT COUNT(*) FROM source_fragment WHERE parent_fragment_id = ?",
                (row["id"],),
            ).fetchone()[0]
            raw = project.read_asset_bytes(row["source_text_sha256"])
            text = raw[row["start_byte"]:row["end_byte"]].decode("utf-8")
            items.append(_fragment_dict(row, text, windows, raw))
    next_cursor = page[-1]["ordinal"] + 1 if len(rows) > limit and page else None
    return {"fragments": items, "next_cursor": next_cursor}


def context_for(project: Project, source_id: str, start_byte: int, end_byte: int) -> dict:
    source = get_source_row(project, source_id)
    raw = project.read_asset_bytes(source["text_sha256"])
    validate_span(raw, start_byte, end_byte)
    with project._conn() as conn:
        paragraphs = conn.execute(
            """SELECT * FROM source_fragment
               WHERE source_id = ? AND kind = 'paragraph' ORDER BY ordinal""",
            (source_id,),
        ).fetchall()
    focus = None
    for row in paragraphs:
        if row["start_byte"] <= start_byte and end_byte <= row["end_byte"]:
            focus = row
            break
    if focus is None and paragraphs:
        focus = min(paragraphs, key=lambda row: abs(row["start_byte"] - start_byte))
    if focus is None:
        raise ProjectError("NOT_FOUND", "That source has no paragraphs.", status=404)
    by_ordinal = {row["ordinal"]: row for row in paragraphs}
    return {
        "title": source["title"],
        "author": source["author"],
        "source_id": source_id,
        "before": _optional_fragment(project, raw, by_ordinal.get(focus["ordinal"] - 1)),
        "focus": _optional_fragment(project, raw, focus),
        "after": _optional_fragment(project, raw, by_ordinal.get(focus["ordinal"] + 1)),
    }


def occurrences(project: Project, source_id: str, text: str) -> dict:
    source = get_source_row(project, source_id)
    raw = project.read_asset_bytes(source["text_sha256"])
    spans = find_occurrences(raw, text)
    decoded = raw.decode("utf-8")
    items = []
    for start, end in spans:
        anchor = make_anchor("source_version", source_id, raw, start, end)
        prefix = len(raw[:start].decode("utf-8"))
        piece = raw[start:end].decode("utf-8")
        excerpt = decoded[max(0, prefix - 24) : prefix + len(piece) + 24]
        anchor["preview"] = excerpt
        items.append(anchor)
    return {"occurrences": items}


def get_source_row(project: Project, source_id: str):
    with project._conn() as conn:
        row = conn.execute("SELECT * FROM source_document WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise ProjectError("NOT_FOUND", "That source is not in this project.", status=404)
    return row


def leaf_fragments(project: Project, collection: str = "imported") -> list:
    with project._conn() as conn:
        return conn.execute(
            """SELECT f.*, s.title, s.author, s.family_id, s.collection FROM source_fragment f
               JOIN source_document s ON s.id = f.source_id
               WHERE s.collection = ?
                 AND (
                   f.kind = 'window'
                   OR (f.kind = 'paragraph' AND NOT EXISTS (
                       SELECT 1 FROM source_fragment child WHERE child.parent_fragment_id = f.id
                   ))
                 )
               ORDER BY f.id""",
            (collection,),
        ).fetchall()


def latest_snapshot_id(project: Project, collection: str = "imported") -> str | None:
    with project._conn() as conn:
        row = conn.execute(
            """SELECT id FROM corpus_snapshot WHERE collection = ?
               ORDER BY created_at DESC LIMIT 1""",
            (collection,),
        ).fetchone()
    return None if row is None else row["id"]


def _optional_fragment(project: Project, raw: bytes, row) -> dict | None:
    if row is None:
        return None
    text = raw[row["start_byte"]:row["end_byte"]].decode("utf-8")
    return _fragment_dict(row, text, 0, raw)


def _fragment_dict(row, text: str, window_count: int, raw: bytes) -> dict:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "parent_fragment_id": row["parent_fragment_id"],
        "kind": row["kind"],
        "ordinal": row["ordinal"],
        "start_byte": row["start_byte"],
        "end_byte": row["end_byte"],
        "slice_sha256": row["slice_sha256"],
        "text": text,
        "window_count": window_count,
        "token_count": row["token_count"],
        "token_limit": row["token_limit"],
        "profile_id": row["profile_id"],
        "segmentation_version": row["segmentation_version"],
        "anchor": make_anchor("source_version", row["source_id"], raw, row["start_byte"], row["end_byte"]),
    }


def _source_summary(row) -> dict:
    return {
        "id": row["id"],
        "family_id": row["family_id"],
        "title": row["title"],
        "author": row["author"],
        "source_uri": row["source_uri"],
        "source_date": row["source_date"],
        "language": row["language"],
        "edition": row["edition"],
        "notes": row["notes"],
        "filename": row["filename"],
        "media_type": row["media_type"],
        "text_sha256": row["text_sha256"],
        "byte_length": row["byte_length"],
        "created_at": row["created_at"],
        "collection": row["collection"],
    }


def _bound(limit: int, default: int, maximum: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        return default
    return min(limit, maximum)
