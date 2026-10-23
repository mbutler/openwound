"""A project archive keeps committed history and does not replay it."""

import hashlib
import io
import json
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ncm_art import __version__
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.migrate import SCHEMA_VERSION
from ncm_art.works.service import get_work

EXPORT_SCHEMA = 1
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_ASSET = "assets/"


def export_work_text(project, work_id: str, form: str = "markdown", appendix: bool = False) -> str:
    work = get_work(project, work_id)
    entries = [entry["text"] for entry in work["entries"] if not entry["removed"]]
    if form == "text":
        lines = [work["title"], ""]
        lines.extend(_separated(entries))
        if appendix:
            lines.extend(["", *_appendix_lines(project, work)])
        return "\n".join(lines).rstrip() + "\n"
    if form != "markdown":
        raise ProjectError("INVALID_TEXT", "Export the work as text or markdown.")
    lines = [f"# {work['title']}", ""]
    lines.extend(_separated(entries))
    if appendix:
        lines.extend(["", "## Appendix", ""])
        lines.extend(_appendix_lines(project, work))
    return "\n".join(lines).rstrip() + "\n"


def export_project_archive(project) -> bytes:
    manifest = _public_manifest(project.manifest())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        database = _snapshot(project)
        assets = _assets(project, database)
        files = [("project.json", json.dumps(manifest, indent=2).encode("utf-8") + b"\n"), ("project.sqlite", database)]
        files.extend((f"assets/{digest}", data) for digest, data in assets)
        listing = []
        for path, data in files:
            _reject_path(path)
            listing.append({"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
            archive.writestr(path, data)
        description = {
            "export_schema": EXPORT_SCHEMA,
            "kind": "openwound-project",
            "format_version": manifest["format_version"],
            "source_project_id": manifest["id"],
            "created_at": _now(),
            "app_version": __version__,
            "files": listing,
        }
        archive.writestr("export.json", json.dumps(description, indent=2).encode("utf-8") + b"\n")
    result = buffer.getvalue()
    if len(result) > MAX_ARCHIVE_BYTES:
        raise ProjectError("INVALID_TEXT", "That project archive is too large to export.")
    return result


def import_project_archive(library, data: bytes):
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProjectError("INVALID_TEXT", "That project archive is too large to import.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ProjectError("INVALID_TEXT", "That file is not a project archive.") from error
    names = archive.namelist()
    if any(_unsafe(name) for name in names):
        raise ProjectError("INVALID_TEXT", "That archive contains an unsafe path.")
    if "export.json" not in names:
        raise ProjectError("INVALID_TEXT", "That archive has no export manifest.")
    try:
        description = json.loads(archive.read("export.json").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProjectError("INVALID_TEXT", "That export manifest could not be read.") from error
    if not isinstance(description, dict) or description.get("export_schema") != EXPORT_SCHEMA:
        raise ProjectError("INVALID_TEXT", "That export manifest is not a supported Openwound archive.")
    if int(description.get("format_version") or 0) > SCHEMA_VERSION:
        raise ProjectError(
            "UNSUPPORTED_FORMAT",
            f"This archive uses format {description.get('format_version')}. This version of Openwound supports format {SCHEMA_VERSION}.",
            status=409,
        )
    files = description.get("files")
    if not isinstance(files, list) or not files:
        raise ProjectError("INVALID_TEXT", "That export manifest lists no files.")
    expected = {item["path"] for item in files}
    present = {name for name in names if name != "export.json"}
    if present != expected:
        raise ProjectError("INVALID_TEXT", "That archive does not match its manifest.")
    extracted = {}
    total = 0
    for item in files:
        path = item.get("path")
        _reject_path(path)
        payload = archive.read(path)
        total += len(payload)
        if total > MAX_ARCHIVE_BYTES:
            raise ProjectError("INVALID_TEXT", "That project archive is too large to import.")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != item.get("sha256") or len(payload) != item.get("bytes"):
            raise ProjectError("INVALID_TEXT", "A file in that archive does not match its recorded hash.")
        extracted[path] = payload
    _require_archive_schema(extracted["project.sqlite"])
    project_manifest = json.loads(extracted["project.json"].decode("utf-8"))
    source_id = project_manifest.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise ProjectError("INVALID_TEXT", "That project manifest has no id.")
    new_id = str(uuid.uuid4())
    project_manifest = _public_manifest(project_manifest)
    project_manifest["id"] = new_id
    project_manifest["copied_from_project_id"] = source_id
    project_manifest["copied_at"] = _now()
    temporary = library.root / f".import-{new_id}"
    temporary.mkdir()
    try:
        (temporary / "project.json").write_text(json.dumps(project_manifest, indent=2) + "\n", encoding="utf-8")
        (temporary / "project.sqlite").write_bytes(extracted["project.sqlite"])
        asset_dir = temporary / "assets"
        asset_dir.mkdir()
        for path, payload in extracted.items():
            if path.startswith(_ASSET):
                (asset_dir / path.removeprefix(_ASSET)).write_bytes(payload)
        destination = library.root / new_id
        temporary.rename(destination)
    except Exception:
        if temporary.exists():
            _remove(temporary)
        raise
    return library.project(new_id)


def _snapshot(project) -> bytes:
    source = sqlite3.connect(project.db_path)
    handle = tempfile.NamedTemporaryFile(prefix="openwound-export-", suffix=".sqlite", delete=False)
    temporary = Path(handle.name)
    handle.close()
    try:
        dest = sqlite3.connect(temporary)
        try:
            source.backup(dest)
            dest.execute("DELETE FROM embedding")
            now = _now()
            error = json.dumps(
                {
                    "code": "JOB_INTERRUPTED",
                    "message": "This job was exported while it was unfinished. Start it again to retry. It was not resumed.",
                }
            )
            dest.execute(
                """UPDATE job SET state='interrupted', error_json=?, updated_at=?
                   WHERE state IN ('queued', 'running')""",
                (error, now),
            )
            dest.commit()
        finally:
            dest.close()
        return temporary.read_bytes()
    finally:
        source.close()
        temporary.unlink(missing_ok=True)


def _assets(project, database: bytes) -> list[tuple[str, bytes]]:
    found = set()
    with _memory(database) as connection:
        for table, column in (
            ("passage_revision", "text_sha256"),
            ("source_document", "text_sha256"),
            ("annotation", "text_sha256"),
            ("correspondence_member", "text_sha256"),
            ("representation", "displayed_text_sha256"),
        ):
            for row in connection.execute(f"SELECT {column} FROM {table}"):
                if row[0]:
                    found.add(row[0])
    assets = []
    for digest in sorted(found):
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ProjectError("INVALID_TEXT", "A saved text hash is not an asset id.")
        path = project.asset_dir / digest
        if not path.is_file():
            raise ProjectError("INVALID_TEXT", "A saved passage is missing its text.")
        assets.append((digest, path.read_bytes()))
    return assets


def _require_archive_schema(database: bytes) -> None:
    with _memory(database) as connection:
        row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None or int(row[0]) > SCHEMA_VERSION:
        found = None if row is None else int(row[0])
        raise ProjectError(
            "UNSUPPORTED_FORMAT",
            f"This archive uses format {found}. This version of Openwound supports format {SCHEMA_VERSION}.",
            status=409,
        )


def _public_manifest(manifest: dict) -> dict:
    kept = {
        "id": manifest["id"],
        "format_version": int(manifest["format_version"]),
        "app_version": manifest.get("app_version") or __version__,
        "created_at": manifest.get("created_at"),
        "title": manifest.get("title") or "Untitled",
        "database": "project.sqlite",
    }
    for key, value in kept.items():
        if isinstance(value, str) and (value.startswith("/") or value.startswith("\\")):
            raise ProjectError("INVALID_TEXT", "The project manifest contains a machine path.")
    return kept


def _appendix_lines(project, work: dict) -> list[str]:
    lines = ["Sources", ""]
    titles = []
    for event in work["events"]:
        donor = event["detail"].get("donor") if isinstance(event["detail"], dict) else None
        if isinstance(donor, dict) and donor.get("owner_kind") == "source_version":
            title = _source_title(project, donor["owner_id"])
            if title and title not in titles:
                titles.append(title)
    for name in work["held_names"]:
        if name.get("source_title") and name["source_title"] not in titles:
            titles.append(name["source_title"])
    lines.extend(titles or ["None recorded."])
    lines.extend(["", "Influences", ""])
    if work["binding"]:
        lines.append(work["binding"]["name"])
        lines.append(work["binding"]["interpretation"])
    else:
        lines.append("No influence is bound.")
    lines.extend(["", "Held names", ""])
    if work["held_names"]:
        for name in work["held_names"]:
            origin = f" from {name['source_title']}" if name.get("source_title") else ""
            lines.append(f"{name['text']} — {name['status']}{origin}")
    else:
        lines.append("No names are held.")
    lines.extend(["", "History", ""])
    for event in reversed(work["events"]):
        lines.append(_history_line(event))
        if event.get("earlier_text"):
            lines.append(event["earlier_text"])
    return lines


def _history_line(event: dict) -> str:
    detail = event["detail"] if isinstance(event.get("detail"), dict) else {}
    action = event["action"]
    if action == "create":
        return "Work opened."
    if action == "bind":
        return f"Bound “{detail.get('name', '')}”."
    if action == "unbind":
        return "Unbound the influence. Earlier names stay held."
    if action == "transfer":
        marked = detail.get("mark_text")
        return f"Added a passage. Held the name “{marked}”." if marked else "Added a passage."
    if action == "protected_insert":
        return "Inserted a protected passage."
    if action == "return":
        return f"Returned the name “{detail.get('text', '')}”."
    if action == "edit":
        return "Edited an entry."
    if action == "remove":
        return "Removed an entry."
    if action == "restore":
        return "Restored an entry."
    if action == "reorder":
        return "Reordered the entries."
    if action == "retarget":
        return "Chose a current place for a held name."
    if action == "repair":
        return f"Adopted a repair. “{detail.get('omitted_text', '')}” became “{detail.get('replacement_text', '')}”."
    return action


def _source_title(project, source_id: str) -> str | None:
    with project._conn() as conn:
        row = conn.execute("SELECT title FROM source_document WHERE id=?", (source_id,)).fetchone()
    return None if row is None else row["title"]


def _separated(entries: list[str]) -> list[str]:
    lines = []
    for text in entries:
        lines.append(text)
        lines.append("")
    return lines


def _reject_path(path: str) -> None:
    if not isinstance(path, str) or _unsafe(path):
        raise ProjectError("INVALID_TEXT", "That archive contains an unsafe path.")
    allowed = path in {"project.json", "project.sqlite"} or (
        path.startswith(_ASSET) and len(path.removeprefix(_ASSET)) == 64 and "/" not in path.removeprefix(_ASSET)
    )
    if not allowed:
        raise ProjectError("INVALID_TEXT", "That archive contains an unexpected file.")


def _unsafe(name: str) -> bool:
    if not isinstance(name, str) or not name or name.endswith("/"):
        return True
    parts = Path(name).parts
    return name.startswith("/") or name.startswith("\\") or ".." in parts or "\\" in name or ":" in parts


def _remove(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()


@contextmanager
def _memory(database: bytes):
    handle = tempfile.NamedTemporaryFile(prefix="openwound-read-", suffix=".sqlite", delete=False)
    path = Path(handle.name)
    handle.close()
    path.write_bytes(database)
    connection = sqlite3.connect(path)
    try:
        yield connection
    finally:
        connection.close()
        path.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
