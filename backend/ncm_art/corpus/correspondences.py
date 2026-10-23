"""Saved correspondences.

A correspondence keeps exact anchors and a history of interpretations.
Resemblance does not create a generated-from edge.
"""

import uuid
from datetime import datetime, timezone

from ncm_art.corpus.anchors import make_anchor
from ncm_art.corpus.sources import get_source_row
from ncm_art.storage.errors import ProjectError

PRODUCERS = {"artist", "model", "adapted"}
DISPOSITIONS = {"open", "retained", "set_aside", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_correspondence(
    project,
    *,
    members: list[dict],
    title: str = "",
    interpretation: str = "",
    producer: str = "artist",
    encounter_id: str | None = None,
) -> dict:
    if len(members) < 2:
        raise ProjectError("INVALID_SPAN", "A correspondence needs at least two passages.")
    _check_producer(producer)
    anchors = [_resolve(project, member) for member in members]
    created = _now()
    correspondence_id = str(uuid.uuid4())
    with project.immediate_transaction() as conn:
        if encounter_id:
            found = conn.execute("SELECT id FROM encounter WHERE id = ?", (encounter_id,)).fetchone()
            if found is None:
                raise ProjectError("NOT_FOUND", "That encounter is not in this project.", status=404)
        conn.execute(
            """INSERT INTO correspondence(id, title, disposition, encounter_id, created_at, updated_at)
               VALUES (?, ?, 'open', ?, ?, ?)""",
            (correspondence_id, title.strip(), encounter_id, created, created),
        )
        for ordinal, anchor in enumerate(anchors):
            conn.execute(
                """INSERT INTO correspondence_member(
                       id, correspondence_id, ordinal, owner_kind, owner_id, text_sha256,
                       start_byte, end_byte, slice_sha256
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    correspondence_id,
                    ordinal,
                    anchor["owner_kind"],
                    anchor["owner_id"],
                    anchor["text_sha256"],
                    anchor["start_byte"],
                    anchor["end_byte"],
                    anchor["slice_sha256"],
                ),
            )
        if interpretation.strip():
            conn.execute(
                """INSERT INTO interpretation_revision(id, correspondence_id, body, producer, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), correspondence_id, interpretation.strip(), producer, created),
            )
    return get_correspondence(project, correspondence_id)


def revise_interpretation(project, correspondence_id: str, body: str, producer: str = "artist") -> dict:
    _check_producer(producer)
    if not body.strip():
        raise ProjectError("INVALID_TEXT", "The interpretation is empty.")
    created = _now()
    with project.immediate_transaction() as conn:
        row = conn.execute("SELECT id FROM correspondence WHERE id = ?", (correspondence_id,)).fetchone()
        if row is None:
            raise ProjectError("NOT_FOUND", "That correspondence is not in this project.", status=404)
        conn.execute(
            """INSERT INTO interpretation_revision(id, correspondence_id, body, producer, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), correspondence_id, body.strip(), producer, created),
        )
        conn.execute(
            "UPDATE correspondence SET updated_at = ? WHERE id = ?",
            (created, correspondence_id),
        )
    return get_correspondence(project, correspondence_id)


def set_disposition(project, correspondence_id: str, disposition: str) -> dict:
    if disposition not in DISPOSITIONS:
        raise ProjectError("INVALID_TEXT", "That disposition is not one of the activity labels.", {"disposition": disposition})
    with project.immediate_transaction() as conn:
        row = conn.execute("SELECT id FROM correspondence WHERE id = ?", (correspondence_id,)).fetchone()
        if row is None:
            raise ProjectError("NOT_FOUND", "That correspondence is not in this project.", status=404)
        conn.execute(
            "UPDATE correspondence SET disposition = ?, updated_at = ? WHERE id = ?",
            (disposition, _now(), correspondence_id),
        )
    return get_correspondence(project, correspondence_id)


def list_correspondences(project, limit: int = 50) -> dict:
    limit = 50 if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 else min(limit, 100)
    with project._conn() as conn:
        rows = conn.execute(
            "SELECT * FROM correspondence ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = []
        for row in rows:
            current = conn.execute(
                """SELECT body, producer FROM interpretation_revision
                   WHERE correspondence_id = ? ORDER BY created_at DESC LIMIT 1""",
                (row["id"],),
            ).fetchone()
            items.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "disposition": row["disposition"],
                    "updated_at": row["updated_at"],
                    "interpretation": None if current is None else current["body"],
                    "producer": None if current is None else current["producer"],
                }
            )
    return {"correspondences": items}


def get_correspondence(project, correspondence_id: str) -> dict:
    with project._conn() as conn:
        row = conn.execute("SELECT * FROM correspondence WHERE id = ?", (correspondence_id,)).fetchone()
        if row is None:
            raise ProjectError("NOT_FOUND", "That correspondence is not in this project.", status=404)
        members = conn.execute(
            "SELECT * FROM correspondence_member WHERE correspondence_id = ? ORDER BY ordinal",
            (correspondence_id,),
        ).fetchall()
        revisions = conn.execute(
            """SELECT * FROM interpretation_revision
               WHERE correspondence_id = ? ORDER BY created_at, rowid""",
            (correspondence_id,),
        ).fetchall()
    return {
        "id": row["id"],
        "title": row["title"],
        "disposition": row["disposition"],
        "encounter_id": row["encounter_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "members": [_member(project, member) for member in members],
        "interpretations": [
            {
                "id": revision["id"],
                "body": revision["body"],
                "producer": revision["producer"],
                "created_at": revision["created_at"],
            }
            for revision in revisions
        ],
    }


def _member(project, row) -> dict:
    raw = _owner_bytes(project, row["owner_kind"], row["owner_id"])
    anchor = make_anchor(row["owner_kind"], row["owner_id"], raw, row["start_byte"], row["end_byte"])
    if anchor["slice_sha256"] != row["slice_sha256"] or anchor["text_sha256"] != row["text_sha256"]:
        raise ProjectError("SPAN_MISMATCH", "A saved passage no longer matches its source bytes.")
    title = None
    if row["owner_kind"] == "source_version":
        title = get_source_row(project, row["owner_id"])["title"]
    return {
        "ordinal": row["ordinal"],
        "title": title,
        "text": raw[row["start_byte"] : row["end_byte"]].decode("utf-8"),
        "anchor": anchor,
    }


def _resolve(project, member: dict) -> dict:
    owner_kind = member["owner_kind"]
    owner_id = member["owner_id"]
    raw = _owner_bytes(project, owner_kind, owner_id)
    anchor = make_anchor(owner_kind, owner_id, raw, int(member["start_byte"]), int(member["end_byte"]))
    if member.get("text") is not None:
        actual = raw[anchor["start_byte"] : anchor["end_byte"]].decode("utf-8")
        if actual != member["text"]:
            raise ProjectError("INVALID_SPAN", "The selected text does not match this revision.")
    if member.get("text_sha256") and member["text_sha256"] != anchor["text_sha256"]:
        raise ProjectError("SPAN_MISMATCH", "That passage hash does not match the saved text.")
    if member.get("slice_sha256") and member["slice_sha256"] != anchor["slice_sha256"]:
        raise ProjectError("SPAN_MISMATCH", "That passage hash does not match the saved text.")
    return anchor


def _owner_bytes(project, owner_kind: str, owner_id: str) -> bytes:
    if owner_kind == "source_version":
        source = get_source_row(project, owner_id)
        return project.read_asset_bytes(source["text_sha256"])
    if owner_kind == "passage_revision":
        revision = project.revision(owner_id)
        return revision["text"].encode("utf-8")
    raise ProjectError("INVALID_SPAN", "That anchor does not name a source or a passage.")


def _check_producer(producer: str) -> None:
    if producer not in PRODUCERS:
        raise ProjectError(
            "INVALID_TEXT",
            "An interpretation is written by the artist, proposed by a model, or adapted from a model.",
            {"producer": producer},
        )
