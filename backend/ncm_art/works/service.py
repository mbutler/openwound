"""Work state, previews, and one atomic adoption.

Preview writes candidates only. Live entries, held names, and receipts are
written together in commit_prepared_application.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from ncm_art.corpus.anchors import validate_span
from ncm_art.corpus.correspondences import _owner_bytes
from ncm_art.influences.preset import (
    TEMPLATE,
    TRIGGER,
    apply_to_donor,
    conflicting_protection,
    validate_definition,
)
from ncm_art.operations.text import assemble, overlaps, plan_protections, splice
from ncm_art.storage.errors import ProjectError

TRANSFER = "transfer_fragment_v1"
PROTECTED = "protected_insert_v1"
RETURN = "return_held_name_v1"
OPERATION_VERSION = "1"

STALE = "The work changed after this preview. Prepare it again. The current work was kept."
STALE_ENTRY = "That entry changed after this preview. The current work was kept."
CHANGED = "The receiving passage has changed since this name was taken."
DETACHED = "Restore the entry before returning this name."
DETACHED_PLACE = "Choose the current place for this name. It was detached when the entry was removed."


def create_work(project, title: str) -> dict:
    cleaned = title.strip()
    if not cleaned:
        raise ProjectError("INVALID_TEXT", "Give the work a title.")
    work_id = _new_id()
    now = _now()
    with project.immediate_transaction() as conn:
        conn.execute(
            """INSERT INTO work(id, title, state_version, binding_id, created_at, updated_at)
               VALUES (?, ?, 0, NULL, ?, ?)""",
            (work_id, cleaned, now, now),
        )
        _event(conn, work_id, "create", None, 0, {"title": cleaned}, now)
    return get_work(project, work_id)


def list_works(project) -> dict:
    with project._conn() as conn:
        rows = conn.execute("SELECT * FROM work ORDER BY updated_at, rowid").fetchall()
    return {
        "works": [
            {
                "id": row["id"],
                "title": row["title"],
                "state_version": row["state_version"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }


def get_work(project, work_id: str) -> dict:
    with project._conn() as conn:
        work = _lock_work(conn, work_id)
        binding = _active_binding(conn, work)
        entries = conn.execute(
            "SELECT * FROM work_entry WHERE work_id=? ORDER BY removed_at IS NOT NULL, ordinal, rowid",
            (work_id,),
        ).fetchall()
        drafts = {
            row["entry_id"]: row["body"]
            for row in conn.execute("SELECT * FROM work_entry_draft WHERE work_id=?", (work_id,))
        }
        names = conn.execute(
            "SELECT * FROM held_name WHERE work_id=? ORDER BY created_at, rowid",
            (work_id,),
        ).fetchall()
        previews = conn.execute(
            """SELECT * FROM operation_preview
               WHERE work_id=? AND status='prepared'
               ORDER BY created_at DESC, rowid DESC LIMIT 20""",
            (work_id,),
        ).fetchall()
        events = conn.execute(
            """SELECT * FROM work_event
               WHERE work_id=? ORDER BY created_at DESC, rowid DESC LIMIT 40""",
            (work_id,),
        ).fetchall()
        entry_payloads = [_entry_payload(project, conn, row, drafts) for row in entries]
        name_payloads = [_name_payload(conn, row, entries) for row in names]
        preview_payloads = [_preview_payload(project, conn, row) for row in previews]
        event_payloads = [_event_payload(project, conn, row) for row in events]
    return {
        "id": work["id"],
        "title": work["title"],
        "state_version": work["state_version"],
        "binding": binding,
        "entries": entry_payloads,
        "held_names": name_payloads,
        "previews": preview_payloads,
        "events": event_payloads,
    }


def reorder_entries(project, work_id: str, entry_ids: list[str], expected_state: int) -> dict:
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        active = conn.execute(
            """SELECT id FROM work_entry
               WHERE work_id=? AND removed_at IS NULL ORDER BY ordinal, rowid""",
            (work_id,),
        ).fetchall()
        current = [row["id"] for row in active]
        if sorted(entry_ids) != sorted(current) or len(entry_ids) != len(set(entry_ids)):
            raise ProjectError("STALE_TARGET", STALE_ENTRY, status=409)
        if entry_ids == current:
            changed = False
        else:
            changed = True
            for ordinal, entry_id in enumerate(entry_ids):
                conn.execute("UPDATE work_entry SET ordinal=? WHERE id=?", (ordinal, entry_id))
            version = _advance(conn, work_id, work["state_version"], now)
            _event(conn, work_id, "reorder", work["state_version"], version, {"entry_ids": entry_ids}, now)
        _ = changed
    return get_work(project, work_id)


def remove_entry(project, work_id: str, entry_id: str, expected_state: int) -> dict:
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        entry = _live_entry(conn, work_id, entry_id)
        conn.execute("UPDATE work_entry SET removed_at=? WHERE id=?", (now, entry_id))
        conn.execute(
            """UPDATE held_name SET target_state='detached', updated_at=?
               WHERE entry_id=? AND status='held'""",
            (now, entry_id),
        )
        remaining = conn.execute(
            """SELECT id FROM work_entry
               WHERE work_id=? AND removed_at IS NULL ORDER BY ordinal, rowid""",
            (work_id,),
        ).fetchall()
        for ordinal, row in enumerate(remaining):
            conn.execute("UPDATE work_entry SET ordinal=? WHERE id=?", (ordinal, row["id"]))
        version = _advance(conn, work_id, work["state_version"], now)
        _event(
            conn,
            work_id,
            "remove",
            work["state_version"],
            version,
            {"entry_id": entry_id, "revision_id": entry["passage_revision_id"]},
            now,
        )
    return get_work(project, work_id)


def restore_entry(project, work_id: str, entry_id: str, expected_state: int) -> dict:
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        entry = _entry(conn, work_id, entry_id)
        if entry["removed_at"] is None:
            raise ProjectError("INVALID_DESTINATION", "That entry is already in the work.")
        nxt = conn.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM work_entry WHERE work_id=? AND removed_at IS NULL",
            (work_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE work_entry SET removed_at=NULL, ordinal=? WHERE id=?",
            (nxt, entry_id),
        )
        version = _advance(conn, work_id, work["state_version"], now)
        _event(conn, work_id, "restore", work["state_version"], version, {"entry_id": entry_id}, now)
    return get_work(project, work_id)


def save_entry_draft(project, work_id: str, entry_id: str, text: str) -> dict:
    now = _now()
    with project.immediate_transaction() as conn:
        _lock_work(conn, work_id)
        _entry(conn, work_id, entry_id)
        conn.execute(
            """INSERT INTO work_entry_draft(work_id, entry_id, body, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(work_id, entry_id) DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at""",
            (work_id, entry_id, text, now),
        )
    return get_work(project, work_id)


def edit_entry(
    project,
    work_id: str,
    entry_id: str,
    text: str,
    expected_state: int,
    release_protection: bool = False,
) -> dict:
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        entry = _live_entry(conn, work_id, entry_id)
        old, source_id = _revision_bytes(conn, project, entry["passage_revision_id"])
        new = text.encode("utf-8")
        if new != old:
            _replace_edited_entry(
                project, conn, work, entry, old, new, text, source_id, release_protection, now
            )
    return get_work(project, work_id)


def _replace_edited_entry(project, conn, work, entry, old, new, text, source_id, release_protection, now) -> None:
    carried = plan_protections(old, new, _protection_rows(conn, entry["passage_revision_id"]), release_protection)
    revision_id = _insert_candidate(project, conn, text, source_id, now)
    _insert_protections(conn, revision_id, carried, now)
    conn.execute(
        "UPDATE work_entry SET passage_revision_id=? WHERE id=?",
        (revision_id, entry["id"]),
    )
    conn.execute(
        """UPDATE held_name
           SET target_state='unresolved', target_start=NULL, target_end=NULL, updated_at=?
           WHERE entry_id=? AND status='held'""",
        (now, entry["id"]),
    )
    version = _advance(conn, work["id"], work["state_version"], now)
    _event(
        conn,
        work["id"],
        "edit",
        work["state_version"],
        version,
        {
            "entry_id": entry["id"],
            "revision_id": revision_id,
            "base_revision_id": entry["passage_revision_id"],
            "released_protection": bool(release_protection),
        },
        now,
    )
    _derive(
        project,
        conn,
        revision_id,
        {"host_revision_id": entry["passage_revision_id"]},
        "edit_entry_v1",
        now,
        [(entry["passage_revision_id"], "edited_from")],
    )


def create_influence(
    project,
    name: str,
    interpretation: str,
    template: str | None = None,
    parameters: dict | None = None,
    correspondence_id: str | None = None,
    influence_id: str | None = None,
) -> dict:
    cleaned_name = name.strip()
    cleaned_interpretation = interpretation.strip()
    if not cleaned_name or not cleaned_interpretation:
        raise ProjectError("INVALID_TEXT", "An influence needs a name and an interpretation.")
    stored = validate_definition(template, parameters)
    now = _now()
    with project.immediate_transaction() as conn:
        if correspondence_id:
            found = conn.execute("SELECT id FROM correspondence WHERE id=?", (correspondence_id,)).fetchone()
            if found is None:
                raise ProjectError("NOT_FOUND", "That correspondence is not in this project.", status=404)
        if influence_id is None:
            influence_id = _new_id()
            version_number = 1
            conn.execute("INSERT INTO influence(id, created_at) VALUES (?, ?)", (influence_id, now))
        else:
            current = conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) FROM influence_version WHERE influence_id=?",
                (influence_id,),
            ).fetchone()[0]
            if current == 0:
                raise ProjectError("NOT_FOUND", "That influence is not in this project.", status=404)
            version_number = current + 1
        version_id = _new_id()
        conn.execute(
            """INSERT INTO influence_version(
                   id, influence_id, version_number, name, interpretation, template,
                   parameters_json, correspondence_id, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                version_id,
                influence_id,
                version_number,
                cleaned_name,
                cleaned_interpretation,
                template,
                json.dumps(stored),
                correspondence_id,
                now,
            ),
        )
    return _version_from_id(project, version_id)


def list_influences(project) -> dict:
    with project._conn() as conn:
        influences = conn.execute("SELECT * FROM influence ORDER BY created_at, rowid").fetchall()
        versions = conn.execute(
            "SELECT * FROM influence_version ORDER BY version_number, rowid"
        ).fetchall()
    grouped: dict[str, list] = {}
    for row in versions:
        grouped.setdefault(row["influence_id"], []).append(_version_row(row))
    return {
        "templates": [{"template": TEMPLATE, "trigger": TRIGGER, "mark_role": "name"}],
        "influences": [{"id": row["id"], "versions": grouped.get(row["id"], [])} for row in influences],
    }


def bind_influence(project, work_id: str, influence_version_id: str, expected_state: int) -> dict:
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        version = conn.execute(
            "SELECT * FROM influence_version WHERE id=?",
            (influence_version_id,),
        ).fetchone()
        if version is None:
            raise ProjectError("NOT_FOUND", "That influence version is not in this project.", status=404)
        if version["template"] != TEMPLATE:
            raise ProjectError("NOT_OPERATIVE", "That influence is an idea. It does not govern the work.")
        current = _active_binding(conn, work)
        if not (current and current["influence_version_id"] == influence_version_id):
            _replace_binding(conn, work, current, influence_version_id, version["name"], now)
    return get_work(project, work_id)


def _replace_binding(conn, work, current, influence_version_id: str, name: str, now: str) -> None:
    work_id = work["id"]
    conn.execute(
        "UPDATE work_binding SET active=0, unbound_at=? WHERE work_id=? AND active=1",
        (now, work_id),
    )
    binding_id = _new_id()
    conn.execute(
        """INSERT INTO work_binding(id, work_id, influence_version_id, active, created_at, unbound_at)
           VALUES (?, ?, ?, 1, ?, NULL)""",
        (binding_id, work_id, influence_version_id, now),
    )
    version_number = _advance(conn, work_id, work["state_version"], now)
    conn.execute("UPDATE work SET binding_id=? WHERE id=?", (binding_id, work_id))
    _event(
        conn,
        work_id,
        "bind",
        work["state_version"],
        version_number,
        {
            "binding_id": binding_id,
            "influence_version_id": influence_version_id,
            "name": name,
            "replaced_binding_id": current["id"] if current else None,
        },
        now,
    )


def unbind_influence(project, work_id: str, expected_state: int) -> dict:
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        current = _active_binding(conn, work)
        if current is None:
            raise ProjectError("NOT_BOUND", "No influence is bound to this work.")
        conn.execute(
            "UPDATE work_binding SET active=0, unbound_at=? WHERE id=?",
            (now, current["id"]),
        )
        version = _advance(conn, work_id, work["state_version"], now)
        conn.execute("UPDATE work SET binding_id=NULL WHERE id=?", (work_id,))
        _event(
            conn,
            work_id,
            "unbind",
            work["state_version"],
            version,
            {"binding_id": current["id"], "name": current["name"]},
            now,
        )
    return get_work(project, work_id)


def preview_transfer(project, work_id: str, position: int, donor: dict, mark: dict | None = None) -> dict:
    raw, donor_record, donor_bytes = _donor(project, donor)
    marked = _mark(raw, donor_record, mark)
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        binding = _active_binding(conn, work)
        final, effects, replacement = _governed_transfer(donor_bytes, marked, binding)
        position = _check_position(conn, work_id, position)
        source_id = _donor_source(conn, donor_record)
        base_text = donor_bytes.decode("utf-8")
        base_id = _insert_candidate(project, conn, base_text, source_id, now)
        final_id = _insert_candidate(project, conn, final.decode("utf-8"), source_id, now)
        preview_id = _insert_preview(
            conn,
            work=work,
            binding=binding,
            operation=TRANSFER,
            request={
                "donor": donor_record,
                "mark": marked if effects else None,
                "position": position,
                "entry_count": _active_count(conn, work_id),
                "replacement_text": replacement,
            },
            base_id=base_id,
            final_id=final_id,
            destination={
                "kind": "insert_entry",
                "position": position,
                "entry_id": None,
                "expected_revision_id": None,
                "label": "Add to work",
            },
            effects=effects,
            now=now,
        )
    return get_preview(project, preview_id)


def preview_protected_insert(
    project,
    work_id: str,
    entry_id: str,
    boundary: int,
    donor: dict,
    separator: str = "",
    mark: dict | None = None,
    release_protection: bool = False,
) -> dict:
    if not isinstance(separator, str):
        raise ProjectError("INVALID_TEXT", "The separator has to be text.")
    raw, donor_record, donor_bytes = _donor(project, donor)
    marked = _mark(raw, donor_record, mark)
    boundary = _whole(boundary, "The insertion point is not a byte offset.")
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        binding = _active_binding(conn, work)
        entry = _live_entry(conn, work_id, entry_id)
        host, source_id = _revision_bytes(conn, project, entry["passage_revision_id"])
        final, donor_start, donor_end = assemble(host, boundary, donor_bytes, separator)
        _refuse_governed_graft(binding, marked, donor_start, donor_end)
        carried = plan_protections(
            host,
            final,
            _protection_rows(conn, entry["passage_revision_id"]),
            release_protection,
        )
        donor_range = {
            "start_byte": donor_start,
            "end_byte": donor_end,
            "slice_sha256": hashlib.sha256(final[donor_start:donor_end]).hexdigest(),
            "role": "donor",
        }
        for item in carried:
            if overlaps(donor_start, donor_end, item["start_byte"], item["end_byte"]):
                raise ProjectError(
                    "PROTECTED_RANGE",
                    "That insertion would cover a passage that is already protected.",
                    status=409,
                )
        carried.append(donor_range)
        base_id = _insert_candidate(project, conn, host.decode("utf-8"), source_id, now)
        final_id = _insert_candidate(project, conn, final.decode("utf-8"), source_id, now)
        _insert_protections(conn, final_id, carried, now)
        preview_id = _insert_preview(
            conn,
            work=work,
            binding=None,
            operation=PROTECTED,
            request={
                "donor": donor_record,
                "mark": None,
                "entry_id": entry_id,
                "host_revision_id": entry["passage_revision_id"],
                "boundary": boundary,
                "separator": separator,
                "entry_count": _active_count(conn, work_id),
                "release_protection": release_protection,
            },
            base_id=base_id,
            final_id=final_id,
            destination={
                "kind": "replace_entry",
                "position": None,
                "entry_id": entry_id,
                "expected_revision_id": entry["passage_revision_id"],
                "label": "Replace this entry",
            },
            effects=[
                {
                    "kind": "protected_range",
                    "start_byte": donor_start,
                    "end_byte": donor_end,
                    "text": donor_bytes.decode("utf-8"),
                }
            ],
            now=now,
        )
    return get_preview(project, preview_id)


def preview_return(
    project,
    work_id: str,
    held_id: str,
    expected_state: int,
    target_start: int | None = None,
    target_end: int | None = None,
    release_protection: bool = False,
) -> dict:
    explicit = target_start is not None or target_end is not None
    if explicit and (target_start is None or target_end is None):
        raise ProjectError("INVALID_SPAN", "Choose both ends of the current target.")
    if explicit:
        target_start = _whole(target_start, "The return target is not a byte offset.")
        target_end = _whole(target_end, "The return target is not a byte offset.")
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        held = _held(conn, work_id, held_id)
        entry = _entry(conn, work_id, held["entry_id"])
        _return_precondition(held, entry, explicit)
        current, source_id = _revision_bytes(conn, project, entry["passage_revision_id"])
        start, end = _return_span(held, entry, current, explicit, target_start, target_end)
        name = held["donor_text"].encode("utf-8")
        protections = _protection_rows(conn, entry["passage_revision_id"])
        if any(overlaps(start, end, item["start_byte"], item["end_byte"]) for item in protections):
            if not release_protection:
                raise ProjectError(
                    "PROTECTED_RANGE",
                    "That change would alter a protected passage. Release the protection to continue.",
                    status=409,
                )
        final = splice(current, start, end, name)
        carried = plan_protections(current, final, protections, release_protection)
        base_id = _insert_candidate(project, conn, current.decode("utf-8"), source_id, now)
        final_id = _insert_candidate(project, conn, final.decode("utf-8"), source_id, now)
        _insert_protections(conn, final_id, carried, now)
        preview_id = _insert_preview(
            conn,
            work=work,
            binding=_active_binding(conn, work),
            operation=RETURN,
            request={
                "held_name_id": held_id,
                "entry_id": entry["id"],
                "host_revision_id": entry["passage_revision_id"],
                "target_start": start,
                "target_end": end,
                "replacement_text": held["donor_text"],
                "release_protection": release_protection,
            },
            base_id=base_id,
            final_id=final_id,
            destination={
                "kind": "replace_entry",
                "position": None,
                "entry_id": entry["id"],
                "expected_revision_id": entry["passage_revision_id"],
                "label": "Return this name",
            },
            effects=[
                {
                    "kind": "return_name",
                    "held_name_id": held_id,
                    "text": held["donor_text"],
                    "target_start": start,
                    "target_end": end,
                }
            ],
            now=now,
        )
    return get_preview(project, preview_id)


def retarget_held_name(
    project,
    work_id: str,
    held_id: str,
    expected_state: int,
    start_byte: int,
    end_byte: int,
) -> dict:
    start_byte = _whole(start_byte, "The return target is not a byte offset.")
    end_byte = _whole(end_byte, "The return target is not a byte offset.")
    now = _now()
    with project.immediate_transaction() as conn:
        work = _lock_work(conn, work_id)
        _require_state(work, expected_state)
        held = _held(conn, work_id, held_id)
        if held["status"] != "held":
            raise ProjectError("CONFLICT", "That name has already been returned.", status=409)
        entry = _entry(conn, work_id, held["entry_id"])
        if entry["removed_at"] is not None or held["target_state"] == "detached" and entry["removed_at"] is not None:
            raise ProjectError("TARGET_DETACHED", DETACHED, status=409)
        if entry["removed_at"] is not None:
            raise ProjectError("TARGET_DETACHED", DETACHED, status=409)
        current, _source = _revision_bytes(conn, project, entry["passage_revision_id"])
        validate_span(current, start_byte, end_byte)
        conn.execute(
            """UPDATE held_name
               SET target_state='resolved', target_start=?, target_end=?, receiving_revision_id=?, updated_at=?
               WHERE id=?""",
            (start_byte, end_byte, entry["passage_revision_id"], now, held_id),
        )
        version = _advance(conn, work_id, work["state_version"], now)
        _event(
            conn,
            work_id,
            "retarget",
            work["state_version"],
            version,
            {"held_name_id": held_id, "entry_id": entry["id"], "start_byte": start_byte, "end_byte": end_byte},
            now,
        )
    return get_work(project, work_id)


def edit_candidate(project, preview_id: str, text: str, release_protection: bool = False) -> dict:
    now = _now()
    new = text.encode("utf-8")
    with project.immediate_transaction() as conn:
        preview = _preview_row(conn, preview_id)
        if preview["status"] != "prepared":
            raise ProjectError("STALE_PREVIEW", "That preview is no longer current. The current work was kept.", status=409)
        work = _lock_work(conn, preview["work_id"])
        if work["state_version"] != preview["work_state_version"] or work["binding_id"] != preview["binding_id"]:
            raise ProjectError("STALE_PREVIEW", STALE, status=409)
        old, source_id = _revision_bytes(conn, project, preview["final_revision_id"])
        effects = json.loads(preview["effects_json"])
        carried = plan_protections(old, new, _protection_rows(conn, preview["final_revision_id"]), release_protection)
        _require_effect_bytes(new, effects)
        final_id = _insert_candidate(project, conn, text, source_id, now)
        _insert_protections(conn, final_id, carried, now)
        kept = [effect for effect in effects if effect["kind"] != "protected_range"]
        for item in carried:
            if item["role"] == "donor":
                kept.append(
                    {
                        "kind": "protected_range",
                        "start_byte": item["start_byte"],
                        "end_byte": item["end_byte"],
                        "text": new[item["start_byte"] : item["end_byte"]].decode("utf-8"),
                    }
                )
        conn.execute("UPDATE operation_preview SET status='superseded' WHERE id=?", (preview_id,))
        replacement = _insert_preview(
            conn,
            work=work,
            binding=_active_binding(conn, work) if preview["binding_id"] else None,
            operation=preview["operation"],
            request=json.loads(preview["request_json"]),
            base_id=preview["base_revision_id"],
            final_id=final_id,
            destination=json.loads(preview["destination_json"]),
            effects=kept,
            now=now,
        )
    return get_preview(project, replacement)


def reject_preview(project, preview_id: str) -> dict:
    with project.immediate_transaction() as conn:
        preview = _preview_row(conn, preview_id)
        if preview["status"] != "prepared":
            raise ProjectError("STALE_PREVIEW", "That preview is no longer current. The current work was kept.", status=409)
        conn.execute("UPDATE operation_preview SET status='rejected' WHERE id=?", (preview_id,))
        work_id = preview["work_id"]
    return get_work(project, work_id)


def get_preview(project, preview_id: str) -> dict:
    with project._conn() as conn:
        return _preview_payload(project, conn, _preview_row(conn, preview_id))


def commit_prepared_application(
    project,
    project_id: str,
    work_id: str,
    client_request_id: str,
    preview_id: str,
    candidate_id: str,
    expected_state: int,
) -> dict:
    if not isinstance(client_request_id, str) or not client_request_id.strip():
        raise ProjectError("INVALID_TEXT", "A request id is required.")
    digest = _application_hash(project_id, work_id, preview_id, candidate_id, expected_state)
    existing = _read_receipt(project, client_request_id)
    if existing is not None:
        return _receipt_result(existing, digest)
    with project.immediate_transaction() as conn:
        existing = _read_receipt_conn(conn, client_request_id)
        if existing is not None:
            return _receipt_result(existing, digest)
        result = _commit_new(
            project,
            conn,
            work_id,
            client_request_id,
            preview_id,
            candidate_id,
            expected_state,
            digest,
        )
    return result


def _commit_new(project, conn, work_id, client_request_id, preview_id, candidate_id, expected_state, digest) -> dict:
    preview = _preview_row(conn, preview_id)
    if preview["work_id"] != work_id:
        raise ProjectError("CONFLICT", "That preview is not for this work.", status=409)
    if candidate_id != preview["final_revision_id"]:
        raise ProjectError("CONFLICT", "That candidate is not part of this preview.", status=409)
    if preview["status"] != "prepared":
        raise ProjectError("STALE_PREVIEW", "That preview is no longer current. The current work was kept.", status=409)
    work = _lock_work(conn, work_id)
    if work["state_version"] != expected_state or preview["work_state_version"] != expected_state:
        raise ProjectError("STALE_PREVIEW", STALE, status=409)
    if work["binding_id"] != preview["binding_id"]:
        raise ProjectError("STALE_PREVIEW", STALE, status=409)
    request = json.loads(preview["request_json"])
    effects = json.loads(preview["effects_json"])
    destination = json.loads(preview["destination_json"])
    final, _source = _revision_bytes(conn, project, preview["final_revision_id"])
    _require_effect_bytes(final, effects)
    _require_saved_inputs(project, conn, request)
    now = _now()
    receipt_id = _new_id()
    if preview["operation"] == TRANSFER:
        entry_id, held_ids, event_id = _commit_transfer(
            project, conn, work, preview, request, effects, destination, final, receipt_id, now
        )
    elif preview["operation"] == PROTECTED:
        entry_id, held_ids, event_id = _commit_protected(
            project, conn, work, preview, request, destination, receipt_id, now
        )
    elif preview["operation"] == RETURN:
        entry_id, held_ids, event_id = _commit_return(
            project, conn, work, preview, request, effects, destination, final, receipt_id, now
        )
    else:
        raise ProjectError("UNSUPPORTED_TEMPLATE", "That operation is not available.")
    version = _advance(conn, work_id, work["state_version"], now)
    result = {
        "application_id": receipt_id,
        "work_id": work_id,
        "work_state_version": version,
        "entry_id": entry_id,
        "revision_id": preview["final_revision_id"],
        "event_id": event_id,
        "held_name_ids": held_ids,
        "preview_id": preview_id,
    }
    conn.execute(
        """INSERT INTO application_receipt(id, client_request_id, request_hash, preview_id, result_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (receipt_id, client_request_id, digest, preview_id, json.dumps(result), now),
    )
    updated = conn.execute(
        "UPDATE operation_preview SET status='adopted' WHERE id=? AND status='prepared'",
        (preview_id,),
    )
    if updated.rowcount != 1:
        raise ProjectError("STALE_PREVIEW", "That preview is no longer current. The current work was kept.", status=409)
    return result


def _commit_transfer(project, conn, work, preview, request, effects, destination, final, receipt_id, now):
    if work["binding_id"] and not any(effect["kind"] == "held_name" for effect in effects):
        raise ProjectError("RULE_CONFLICT", "The bound influence has no recorded effect on this preview.", status=409)
    if destination["kind"] != "insert_entry":
        raise ProjectError("INVALID_DESTINATION", "An ordinary transfer adds an entry.")
    if request.get("entry_count") != _active_count(conn, work["id"]):
        raise ProjectError("STALE_PREVIEW", STALE, status=409)
    position = request["position"]
    if position < 0 or position > _active_count(conn, work["id"]):
        raise ProjectError("STALE_PREVIEW", STALE, status=409)
    conn.execute(
        """UPDATE work_entry SET ordinal=ordinal+1
           WHERE work_id=? AND removed_at IS NULL AND ordinal>=?""",
        (work["id"], position),
    )
    entry_id = _new_id()
    conn.execute(
        """INSERT INTO work_entry(id, work_id, ordinal, passage_revision_id, removed_at)
           VALUES (?, ?, ?, ?, NULL)""",
        (entry_id, work["id"], position, preview["final_revision_id"]),
    )
    held_ids = []
    planned = []
    for effect in effects:
        if effect["kind"] != "held_name":
            continue
        held_id = _new_id()
        held_ids.append(held_id)
        planned.append((held_id, effect))
    event_id = _new_id()
    detail = {
        "operation": TRANSFER,
        "entry_id": entry_id,
        "revision_id": preview["final_revision_id"],
        "base_revision_id": preview["base_revision_id"],
        "held_name_ids": held_ids,
        "donor": request["donor"],
        "mark_text": request["mark"]["text"] if request.get("mark") else None,
    }
    conn.execute(
        """INSERT INTO work_event(
               id, work_id, action, preview_id, receipt_id, old_state_version, new_state_version, detail_json, created_at
           ) VALUES (?, ?, 'transfer', ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            work["id"],
            preview["id"],
            receipt_id,
            work["state_version"],
            work["state_version"] + 1,
            json.dumps(detail),
            now,
        ),
    )
    mark = request.get("mark")
    for held_id, effect in planned:
        conn.execute(
            """INSERT INTO held_name(
                   id, work_id, entry_id, status, target_state, donor_owner_kind, donor_owner_id,
                   donor_start, donor_end, donor_text, donor_text_sha256, receiving_revision_id,
                   placeholder_start, placeholder_end, placeholder_text, influence_version_id,
                   event_id, returned_revision_id, target_start, target_end, created_at, updated_at
               ) VALUES (?, ?, ?, 'held', 'resolved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)""",
            (
                held_id,
                work["id"],
                entry_id,
                request["donor"]["owner_kind"],
                request["donor"]["owner_id"],
                mark["start_byte"],
                mark["end_byte"],
                effect["text"],
                effect["text_sha256"],
                preview["final_revision_id"],
                effect["placeholder_start"],
                effect["placeholder_end"],
                effect["placeholder"],
                preview["influence_version_id"],
                event_id,
                now,
                now,
            ),
        )
    parents = []
    if request["donor"]["owner_kind"] == "passage_revision":
        parents.append((request["donor"]["owner_id"], "transferred_from"))
    _derive(project, conn, preview["final_revision_id"], request, TRANSFER, now, parents)
    _ = final
    return entry_id, held_ids, event_id


def _commit_protected(project, conn, work, preview, request, destination, receipt_id, now):
    if destination["kind"] != "replace_entry":
        raise ProjectError("INVALID_DESTINATION", "A protected insertion replaces the selected entry.")
    entry = _live_entry(conn, work["id"], destination["entry_id"])
    if entry["passage_revision_id"] != destination["expected_revision_id"]:
        raise ProjectError("STALE_TARGET", STALE_ENTRY, status=409)
    _require_ranges(conn, project, preview["final_revision_id"])
    conn.execute(
        "UPDATE work_entry SET passage_revision_id=? WHERE id=?",
        (preview["final_revision_id"], entry["id"]),
    )
    host = request["host_revision_id"]
    old, _source = _revision_bytes(conn, project, host)
    final, _source = _revision_bytes(conn, project, preview["final_revision_id"])
    _rebase_held_names(
        conn,
        entry["id"],
        host,
        preview["final_revision_id"],
        request["boundary"],
        request["boundary"],
        len(final) - len(old),
        now,
    )
    event_id = _event(
        conn,
        work["id"],
        "protected_insert",
        work["state_version"],
        work["state_version"] + 1,
        {
            "operation": PROTECTED,
            "entry_id": entry["id"],
            "revision_id": preview["final_revision_id"],
            "base_revision_id": preview["base_revision_id"],
            "host_revision_id": host,
            "donor": request["donor"],
            "separator": request["separator"],
        },
        now,
        preview_id=preview["id"],
        receipt_id=receipt_id,
    )
    parents = [(host, "host")]
    if request["donor"]["owner_kind"] == "passage_revision":
        parents.append((request["donor"]["owner_id"], "transferred_from"))
    _derive(project, conn, preview["final_revision_id"], request, PROTECTED, now, parents)
    return entry["id"], [], event_id


def _commit_return(project, conn, work, preview, request, effects, destination, final, receipt_id, now):
    effect = next(item for item in effects if item["kind"] == "return_name")
    entry = _entry(conn, work["id"], destination["entry_id"])
    if entry["removed_at"] is not None:
        raise ProjectError("TARGET_DETACHED", DETACHED, status=409)
    if entry["passage_revision_id"] != destination["expected_revision_id"]:
        raise ProjectError("STALE_TARGET", STALE_ENTRY, status=409)
    held = _held(conn, work["id"], effect["held_name_id"])
    if held["status"] != "held":
        raise ProjectError("CONFLICT", "That name has already been returned.", status=409)
    name = effect["text"].encode("utf-8")
    if final[effect["target_start"] : effect["target_start"] + len(name)] != name:
        raise ProjectError("SPAN_MISMATCH", "The returned name is not in this candidate.", status=409)
    _require_ranges(conn, project, preview["final_revision_id"])
    old_revision = entry["passage_revision_id"]
    conn.execute(
        "UPDATE work_entry SET passage_revision_id=? WHERE id=?",
        (preview["final_revision_id"], entry["id"]),
    )
    _rebase_held_names(
        conn,
        entry["id"],
        old_revision,
        preview["final_revision_id"],
        effect["target_start"],
        effect["target_end"],
        len(name) - (effect["target_end"] - effect["target_start"]),
        now,
        skip_id=held["id"],
    )
    written_end = effect["target_start"] + len(name)
    conn.execute(
        """UPDATE held_name
           SET status='returned', target_state='resolved', returned_revision_id=?,
               target_start=?, target_end=?, updated_at=?
           WHERE id=? AND status='held'""",
        (preview["final_revision_id"], effect["target_start"], written_end, now, held["id"]),
    )
    event_id = _event(
        conn,
        work["id"],
        "return",
        work["state_version"],
        work["state_version"] + 1,
        {
            "operation": RETURN,
            "entry_id": entry["id"],
            "revision_id": preview["final_revision_id"],
            "base_revision_id": old_revision,
            "held_name_id": held["id"],
            "text": effect["text"],
        },
        now,
        preview_id=preview["id"],
        receipt_id=receipt_id,
    )
    _derive(project, conn, preview["final_revision_id"], request, RETURN, now, [(old_revision, "returned_name")])
    _ = final
    return entry["id"], [held["id"]], event_id


def _governed_transfer(donor: bytes, marked: dict | None, binding: dict | None):
    if binding is None:
        return donor, [], None
    if binding["template"] != TEMPLATE:
        raise ProjectError("UNSUPPORTED_TEMPLATE", "That influence template is not available.")
    if marked is None:
        raise ProjectError("MARK_REQUIRED", "Mark the name this passage must leave behind.", status=409)
    replacement = binding["parameters"]["replacement_text"]
    final, start, end = apply_to_donor(donor, marked["rel_start"], marked["rel_end"], replacement)
    effect = {
        "kind": "held_name",
        "text": marked["text"],
        "text_sha256": marked["slice_sha256"],
        "placeholder": replacement,
        "placeholder_start": start,
        "placeholder_end": end,
    }
    return final, [effect], replacement


def _refuse_governed_graft(binding, marked, donor_start: int, donor_end: int) -> None:
    if binding is None:
        return
    if binding["template"] != TEMPLATE:
        raise ProjectError("UNSUPPORTED_TEMPLATE", "That influence template is not available.")
    if marked is None:
        raise ProjectError("MARK_REQUIRED", "Mark the name this passage must leave behind.", status=409)
    mark_start = donor_start + marked["rel_start"]
    mark_end = donor_start + marked["rel_end"]
    conflicting_protection(mark_start, mark_end, [(donor_start, donor_end)])


def _return_precondition(held, entry, explicit: bool) -> None:
    if held["status"] != "held":
        raise ProjectError("CONFLICT", "That name has already been returned.", status=409)
    if entry["removed_at"] is not None:
        raise ProjectError("TARGET_DETACHED", DETACHED, status=409)
    if explicit:
        return
    if held["target_state"] == "detached":
        raise ProjectError("TARGET_DETACHED", DETACHED_PLACE, status=409)
    if held["target_state"] != "resolved":
        raise ProjectError("TARGET_UNRESOLVED", CHANGED, status=409)


def _return_span(held, entry, current: bytes, explicit: bool, target_start, target_end) -> tuple[int, int]:
    if explicit:
        validate_span(current, target_start, target_end)
        return target_start, target_end
    if held["receiving_revision_id"] != entry["passage_revision_id"]:
        raise ProjectError("TARGET_UNRESOLVED", CHANGED, status=409)
    if held["target_start"] is not None:
        validate_span(current, held["target_start"], held["target_end"])
        return held["target_start"], held["target_end"]
    start = held["placeholder_start"]
    end = held["placeholder_end"]
    try:
        piece = validate_span(current, start, end)
    except ProjectError as error:
        raise ProjectError("TARGET_UNRESOLVED", CHANGED, status=409) from error
    if piece.decode("utf-8") != held["placeholder_text"]:
        raise ProjectError("TARGET_UNRESOLVED", CHANGED, status=409)
    return start, end


def _rebase_held_names(
    conn,
    entry_id: str,
    old_revision_id: str,
    new_revision_id: str,
    edit_start: int,
    edit_end: int,
    delta: int,
    now: str,
    skip_id: str | None = None,
) -> None:
    rows = conn.execute(
        "SELECT * FROM held_name WHERE entry_id=? AND status='held'",
        (entry_id,),
    ).fetchall()
    for row in rows:
        if skip_id and row["id"] == skip_id:
            continue
        if row["target_state"] != "resolved" or row["receiving_revision_id"] != old_revision_id:
            _unresolve(conn, row["id"], now)
            continue
        placeholder = _shift(row["placeholder_start"], row["placeholder_end"], edit_start, edit_end, delta)
        target = None
        if row["target_start"] is not None:
            target = _shift(row["target_start"], row["target_end"], edit_start, edit_end, delta)
        if placeholder is None or target is None and row["target_start"] is not None:
            _unresolve(conn, row["id"], now)
            continue
        conn.execute(
            """UPDATE held_name
               SET receiving_revision_id=?, placeholder_start=?, placeholder_end=?,
                   target_start=?, target_end=?, updated_at=?
               WHERE id=?""",
            (
                new_revision_id,
                placeholder[0],
                placeholder[1],
                None if target is None else target[0],
                None if target is None else target[1],
                now,
                row["id"],
            ),
        )


def _shift(start: int, end: int, edit_start: int, edit_end: int, delta: int):
    if end <= edit_start:
        return start, end
    if start >= edit_end:
        return start + delta, end + delta
    return None


def _unresolve(conn, held_id: str, now: str) -> None:
    conn.execute(
        """UPDATE held_name SET target_state='unresolved', target_start=NULL, target_end=NULL, updated_at=?
           WHERE id=?""",
        (now, held_id),
    )


def _require_effect_bytes(final: bytes, effects: list[dict]) -> None:
    for effect in effects:
        if effect["kind"] == "held_name":
            start = effect["placeholder_start"]
            end = effect["placeholder_end"]
            if final[start:end] != effect["placeholder"].encode("utf-8"):
                raise ProjectError("SPAN_MISMATCH", "The marked placeholder is not in this candidate.", status=409)
        if effect["kind"] == "return_name":
            name = effect["text"].encode("utf-8")
            start = effect["target_start"]
            if final[start : start + len(name)] != name:
                raise ProjectError("SPAN_MISMATCH", "The returned name is not in this candidate.", status=409)


def _require_saved_inputs(project, conn, request: dict) -> None:
    donor = request.get("donor")
    if donor:
        _donor(project, donor)
    host_id = request.get("host_revision_id")
    if host_id:
        _revision_bytes(conn, project, host_id)


def _require_ranges(conn, project, revision_id: str) -> None:
    raw, _source = _revision_bytes(conn, project, revision_id)
    for row in _protection_rows(conn, revision_id):
        piece = raw[row["start_byte"] : row["end_byte"]]
        if hashlib.sha256(piece).hexdigest() != row["slice_sha256"]:
            raise ProjectError("PROTECTED_RANGE", "A protection label no longer matches its passage.", status=409)


def _donor(project, anchor: dict):
    raw = _owner_bytes(project, anchor["owner_kind"], anchor["owner_id"])
    start = _whole(anchor["start_byte"], "The passage range is not a byte offset.")
    end = _whole(anchor["end_byte"], "The passage range is not a byte offset.")
    if start == end:
        raise ProjectError("INVALID_SPAN", "Select a nonempty passage.")
    selected = validate_span(raw, start, end)
    text_sha = hashlib.sha256(raw).hexdigest()
    slice_sha = hashlib.sha256(selected).hexdigest()
    if anchor.get("text_sha256") and anchor["text_sha256"] != text_sha:
        raise ProjectError("SPAN_MISMATCH", "That passage hash does not match the saved text.", status=409)
    if anchor.get("slice_sha256") and anchor["slice_sha256"] != slice_sha:
        raise ProjectError("SPAN_MISMATCH", "That passage hash does not match the saved text.", status=409)
    if anchor.get("text") is not None and selected.decode("utf-8") != anchor["text"]:
        raise ProjectError("INVALID_SPAN", "The selected text does not match this revision.")
    record = {
        "owner_kind": anchor["owner_kind"],
        "owner_id": anchor["owner_id"],
        "start_byte": start,
        "end_byte": end,
        "text_sha256": text_sha,
        "slice_sha256": slice_sha,
    }
    return raw, record, selected


def _mark(raw: bytes, donor: dict, mark: dict | None) -> dict | None:
    if mark is None:
        return None
    start = _whole(mark["start_byte"], "The mark is not a byte offset.")
    end = _whole(mark["end_byte"], "The mark is not a byte offset.")
    if not (donor["start_byte"] <= start < end <= donor["end_byte"]):
        raise ProjectError("INVALID_SPAN", "The mark must lie inside the selected passage.")
    selected = validate_span(raw, start, end)
    return {
        "start_byte": start,
        "end_byte": end,
        "rel_start": start - donor["start_byte"],
        "rel_end": end - donor["start_byte"],
        "text": selected.decode("utf-8"),
        "slice_sha256": hashlib.sha256(selected).hexdigest(),
    }


def _insert_candidate(project, conn, text: str, source_id: str | None, created: str) -> str:
    digest = project.write_asset_bytes(text.encode("utf-8"))
    revision_id = _new_id()
    project.insert_revision(
        conn,
        revision_id=revision_id,
        text_sha256=digest,
        origin_kind="candidate",
        source_id=source_id,
        created_at=created,
    )
    return revision_id


def _insert_protections(conn, revision_id: str, protections: list[dict], created: str) -> None:
    for protection in protections:
        conn.execute(
            """INSERT INTO protected_range(
                   id, passage_revision_id, start_byte, end_byte, slice_sha256, role, released, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (
                _new_id(),
                revision_id,
                protection["start_byte"],
                protection["end_byte"],
                protection["slice_sha256"],
                protection["role"],
                created,
            ),
        )


def _insert_preview(
    conn,
    *,
    work,
    binding,
    operation,
    request,
    base_id,
    final_id,
    destination,
    effects,
    now,
) -> str:
    preview_id = _new_id()
    conn.execute(
        """INSERT INTO operation_preview(
               id, work_id, operation, operation_version, request_json, work_state_version,
               binding_id, influence_version_id, base_revision_id, final_revision_id,
               destination_json, effects_json, status, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', ?)""",
        (
            preview_id,
            work["id"],
            operation,
            OPERATION_VERSION,
            json.dumps(request),
            work["state_version"],
            None if binding is None else binding["id"],
            None if binding is None else binding["influence_version_id"],
            base_id,
            final_id,
            json.dumps(destination),
            json.dumps(effects),
            now,
        ),
    )
    return preview_id


def _derive(project, conn, child_id: str, request: dict, operation: str, created: str, parents: list[tuple[str, str]]) -> None:
    run_id = _new_id()
    parameters = {
        "operation": operation,
        "donor": request.get("donor"),
        "mark": request.get("mark"),
        "host_revision_id": request.get("host_revision_id"),
        "separator": request.get("separator"),
    }
    parameters = {key: value for key, value in parameters.items() if value is not None}
    project.insert_run(conn, run_id, operation, child_id, parameters, created)
    for parent_id, relationship in parents:
        project.insert_provenance(
            conn,
            child_id=child_id,
            parent_id=parent_id,
            relationship=relationship,
            run_id=run_id,
        )


def _preview_payload(project, conn, row) -> dict:
    request = json.loads(row["request_json"])
    effects = json.loads(row["effects_json"])
    destination = json.loads(row["destination_json"])
    base = _revision_bytes(conn, project, row["base_revision_id"])[0].decode("utf-8")
    final = _revision_bytes(conn, project, row["final_revision_id"])[0].decode("utf-8")
    binding = None
    if row["influence_version_id"]:
        version = conn.execute(
            "SELECT * FROM influence_version WHERE id=?",
            (row["influence_version_id"],),
        ).fetchone()
        if version is not None:
            binding = _version_row(version)
            binding["id"] = row["binding_id"]
            binding["influence_version_id"] = version["id"]
    applies = any(effect["kind"] == "held_name" for effect in effects)
    donor_text = None
    if request.get("donor"):
        donor_text = _owner_bytes(project, request["donor"]["owner_kind"], request["donor"]["owner_id"])[
            request["donor"]["start_byte"] : request["donor"]["end_byte"]
        ].decode("utf-8")
    protected = [
        {"start_byte": effect["start_byte"], "end_byte": effect["end_byte"], "text": effect["text"]}
        for effect in effects
        if effect["kind"] == "protected_range"
    ]
    return {
        "id": row["id"],
        "operation": row["operation"],
        "operation_version": row["operation_version"],
        "work_id": row["work_id"],
        "work_state_version": row["work_state_version"],
        "status": row["status"],
        "binding_applies": applies,
        "exact_donor_copy": row["operation"] == TRANSFER and base == final,
        "binding": binding,
        "destination": destination,
        "base": {"revision_id": row["base_revision_id"], "text": base},
        "final": {"revision_id": row["final_revision_id"], "text": final},
        "candidate_id": row["final_revision_id"],
        "effects": effects,
        "donor_text": donor_text,
        "separator": request.get("separator"),
        "protected": protected,
        "created_at": row["created_at"],
    }


def _entry_payload(project, conn, row, drafts: dict) -> dict:
    text, _source = _revision_bytes(conn, project, row["passage_revision_id"])
    protected = []
    for item in _protection_rows(conn, row["passage_revision_id"]):
        piece = text[item["start_byte"] : item["end_byte"]]
        if hashlib.sha256(piece).hexdigest() != item["slice_sha256"]:
            conn.execute("UPDATE protected_range SET released=1 WHERE id=?", (item["id"],))
            continue
        protected.append(
            {
                "start_byte": item["start_byte"],
                "end_byte": item["end_byte"],
                "text": piece.decode("utf-8"),
            }
        )
    return {
        "id": row["id"],
        "ordinal": row["ordinal"],
        "revision_id": row["passage_revision_id"],
        "text": text.decode("utf-8"),
        "removed": row["removed_at"] is not None,
        "draft": drafts.get(row["id"]),
        "protected": protected,
    }


def _name_payload(conn, row, entries) -> dict:
    entry = next((item for item in entries if item["id"] == row["entry_id"]), None)
    removed = entry is None or entry["removed_at"] is not None
    source_title = None
    if row["donor_owner_kind"] == "source_version":
        source = conn.execute(
            "SELECT title FROM source_document WHERE id=?",
            (row["donor_owner_id"],),
        ).fetchone()
        source_title = source["title"] if source else None
    message = None
    if row["status"] == "held" and removed:
        message = DETACHED
    elif row["status"] == "held" and row["target_state"] == "detached":
        message = DETACHED_PLACE
    elif row["status"] == "held" and row["target_state"] == "unresolved":
        message = CHANGED
    return {
        "id": row["id"],
        "text": row["donor_text"],
        "status": row["status"],
        "target_state": row["target_state"],
        "entry_id": row["entry_id"],
        "entry_removed": removed,
        "placeholder": row["placeholder_text"],
        "placeholder_start": row["placeholder_start"],
        "placeholder_end": row["placeholder_end"],
        "donor_owner_kind": row["donor_owner_kind"],
        "donor_owner_id": row["donor_owner_id"],
        "donor_start": row["donor_start"],
        "donor_end": row["donor_end"],
        "source_title": source_title,
        "message": message,
    }


def _event_payload(project, conn, row) -> dict:
    detail = json.loads(row["detail_json"])
    earlier = None
    if detail.get("base_revision_id"):
        earlier = _revision_bytes(conn, project, detail["base_revision_id"])[0].decode("utf-8")
    return {
        "id": row["id"],
        "action": row["action"],
        "created_at": row["created_at"],
        "detail": detail,
        "earlier_text": earlier,
    }


def _active_binding(conn, work) -> dict | None:
    if not work["binding_id"]:
        return None
    row = conn.execute(
        """SELECT b.id AS binding_id, v.*
           FROM work_binding b
           JOIN influence_version v ON v.id = b.influence_version_id
           WHERE b.id=? AND b.active=1""",
        (work["binding_id"],),
    ).fetchone()
    if row is None:
        return None
    payload = _version_row(row)
    payload["id"] = row["binding_id"]
    payload["influence_version_id"] = row["id"]
    return payload


def _version_row(row) -> dict:
    return {
        "id": row["id"],
        "influence_id": row["influence_id"],
        "version_number": row["version_number"],
        "name": row["name"],
        "interpretation": row["interpretation"],
        "template": row["template"],
        "parameters": json.loads(row["parameters_json"]),
        "operative": row["template"] == TEMPLATE,
        "created_at": row["created_at"],
    }


def _version_from_id(project, version_id: str) -> dict:
    with project._conn() as conn:
        row = conn.execute("SELECT * FROM influence_version WHERE id=?", (version_id,)).fetchone()
    return _version_row(row)


def _protection_rows(conn, revision_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM protected_range
           WHERE passage_revision_id=? AND released=0 ORDER BY start_byte""",
        (revision_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _revision_bytes(conn, project, revision_id: str) -> tuple[bytes, str | None]:
    row = conn.execute(
        "SELECT text_sha256, source_id FROM passage_revision WHERE id=?",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise ProjectError("NOT_FOUND", "That passage revision is not in this project.", status=404)
    return project.read_asset_bytes(row["text_sha256"]), row["source_id"]


def _donor_source(conn, donor: dict) -> str | None:
    if donor["owner_kind"] == "source_version":
        return donor["owner_id"]
    if donor["owner_kind"] == "passage_revision":
        row = conn.execute(
            "SELECT source_id FROM passage_revision WHERE id=?",
            (donor["owner_id"],),
        ).fetchone()
        return None if row is None else row["source_id"]
    return None


def _lock_work(conn, work_id: str):
    row = conn.execute("SELECT * FROM work WHERE id=?", (work_id,)).fetchone()
    if row is None:
        raise ProjectError("NOT_FOUND", "That work is not in this project.", status=404)
    return row


def _entry(conn, work_id: str, entry_id: str):
    row = conn.execute(
        "SELECT * FROM work_entry WHERE id=? AND work_id=?",
        (entry_id, work_id),
    ).fetchone()
    if row is None:
        raise ProjectError("NOT_FOUND", "That entry is not in this work.", status=404)
    return row


def _live_entry(conn, work_id: str, entry_id: str):
    row = _entry(conn, work_id, entry_id)
    if row["removed_at"] is not None:
        raise ProjectError("STALE_TARGET", STALE_ENTRY, status=409)
    return row


def _held(conn, work_id: str, held_id: str):
    row = conn.execute(
        "SELECT * FROM held_name WHERE id=? AND work_id=?",
        (held_id, work_id),
    ).fetchone()
    if row is None:
        raise ProjectError("NOT_FOUND", "That held name is not in this work.", status=404)
    return row


def _preview_row(conn, preview_id: str):
    row = conn.execute("SELECT * FROM operation_preview WHERE id=?", (preview_id,)).fetchone()
    if row is None:
        raise ProjectError("NOT_FOUND", "That preview is not in this project.", status=404)
    return row


def _active_count(conn, work_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM work_entry WHERE work_id=? AND removed_at IS NULL",
        (work_id,),
    ).fetchone()[0]


def _check_position(conn, work_id: str, position: int) -> int:
    position = _whole(position, "The destination is not a position in the work.")
    if position < 0 or position > _active_count(conn, work_id):
        raise ProjectError("INVALID_DESTINATION", "That position is outside the work.")
    return position


def _advance(conn, work_id: str, old_version: int, now: str) -> int:
    new_version = old_version + 1
    cursor = conn.execute(
        "UPDATE work SET state_version=?, updated_at=? WHERE id=? AND state_version=?",
        (new_version, now, work_id, old_version),
    )
    if cursor.rowcount != 1:
        raise ProjectError("STALE_PREVIEW", STALE, status=409)
    return new_version


def _require_state(work, expected: int) -> None:
    if work["state_version"] != expected:
        raise ProjectError("STALE_PREVIEW", STALE, status=409)


def _event(conn, work_id, action, old_version, new_version, detail, now, preview_id=None, receipt_id=None) -> str:
    event_id = _new_id()
    conn.execute(
        """INSERT INTO work_event(
               id, work_id, action, preview_id, receipt_id, old_state_version, new_state_version, detail_json, created_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event_id, work_id, action, preview_id, receipt_id, old_version, new_version, json.dumps(detail), now),
    )
    return event_id


def _read_receipt(project, client_request_id: str):
    with project._conn() as conn:
        return _read_receipt_conn(conn, client_request_id)


def _read_receipt_conn(conn, client_request_id: str):
    return conn.execute(
        "SELECT * FROM application_receipt WHERE client_request_id=?",
        (client_request_id,),
    ).fetchone()


def _receipt_result(row, digest: str) -> dict:
    if row["request_hash"] != digest:
        raise ProjectError(
            "IDEMPOTENCY_CONFLICT",
            "That request id was already used for a different change.",
            status=409,
        )
    return json.loads(row["result_json"])


def _application_hash(project_id: str, work_id: str, preview_id: str, candidate_id: str, expected_state: int) -> str:
    payload = {
        "route": f"/api/v1/projects/{project_id}/works/{work_id}/commit",
        "preview_id": preview_id,
        "candidate_id": candidate_id,
        "expected_work_state_version": expected_state,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _whole(value, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProjectError("INVALID_SPAN", message)
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())
