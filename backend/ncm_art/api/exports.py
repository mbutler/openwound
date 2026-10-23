"""Readable work text and a portable project archive."""

import base64

from fastapi import Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from ncm_art.exports.archive import export_project_archive, export_work_text, import_project_archive
from ncm_art.storage.errors import ProjectError


class ImportArchive(BaseModel):
    content_base64: str


def register(application, library) -> None:
    def project_for(project_id: str):
        project = library.require_active()
        if project.manifest()["id"] != project_id:
            raise ProjectError(
                "PROJECT_NOT_ACTIVE",
                "Open that project before changing it.",
                {"project_id": project_id},
                status=409,
            )
        return project

    @application.get("/api/v1/projects/{project_id}/works/{work_id}/export")
    def work_export(project_id: str, work_id: str, form: str = Query("markdown"), appendix: int = Query(0)):
        text = export_work_text(project_for(project_id), work_id, form, bool(appendix))
        filename = "work.txt" if form == "text" else "work.md"
        return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @application.post("/api/v1/projects/{project_id}/export")
    def project_export(project_id: str):
        payload = export_project_archive(project_for(project_id))
        return Response(
            content=payload,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="openwound-project.zip"'},
        )

    @application.post("/api/v1/projects/import")
    def project_import(body: ImportArchive):
        try:
            data = base64.b64decode(body.content_base64, validate=True)
        except Exception as error:
            raise ProjectError("INVALID_TEXT", "That archive was not valid base64.") from error
        project = import_project_archive(library, data)
        manifest = project.manifest()
        return {
            "id": manifest["id"],
            "title": manifest["title"],
            "created_at": manifest["created_at"],
            "format_version": manifest["format_version"],
            "copied_from_project_id": manifest.get("copied_from_project_id"),
        }
