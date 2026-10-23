"""Project-scoped import, encounter, and correspondence routes."""

import base64
import uuid

from fastapi import Query
from pydantic import BaseModel, Field

from ncm_art.corpus.correspondences import (
    create_correspondence,
    get_correspondence,
    list_correspondences,
    revise_interpretation,
    set_disposition,
)
from ncm_art.corpus.sources import (
    context_for,
    get_source,
    import_bytes,
    list_fragments,
    list_sources,
    occurrences,
)
from ncm_art.retrieval.encounters import another_passage, get_encounter, run_encounter
from ncm_art.storage.errors import ProjectError


class ImportBody(BaseModel):
    title: str = ""
    text: str | None = None
    content_base64: str | None = None
    filename: str | None = None
    author: str | None = None
    source_uri: str | None = None
    source_date: str | None = None
    language: str | None = None
    edition: str | None = None
    notes: str = ""
    family_id: str | None = None


class AnchorBody(BaseModel):
    owner_kind: str
    owner_id: str
    start_byte: int
    end_byte: int
    text_sha256: str | None = None
    slice_sha256: str | None = None
    text: str | None = None


class CorrespondenceBody(BaseModel):
    title: str = ""
    interpretation: str = ""
    producer: str = "artist"
    encounter_id: str | None = None
    members: list[AnchorBody] = Field(min_length=2)


class InterpretationBody(BaseModel):
    body: str
    producer: str = "artist"


class DispositionBody(BaseModel):
    disposition: str


class EncounterBody(BaseModel):
    text: str = Field(min_length=1)
    source_id: str | None = None
    start_byte: int | None = None
    end_byte: int | None = None
    views: list[str] = ["lexical", "semantic"]
    limit: int = 6
    include_same_document: bool = False
    include_same_family: bool = False


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

    @application.post("/api/v1/projects/{project_id}/sources")
    def import_source(project_id: str, body: ImportBody):
        project = project_for(project_id)
        return import_bytes(project, _source_bytes(body), **_import_fields(body))

    @application.get("/api/v1/projects/{project_id}/sources")
    def sources(project_id: str, limit: int = 50, cursor: str | None = None):
        return list_sources(project_for(project_id), limit=limit, cursor=cursor)

    @application.get("/api/v1/projects/{project_id}/sources/{source_id}")
    def source(project_id: str, source_id: str):
        return get_source(project_for(project_id), source_id)

    @application.get("/api/v1/projects/{project_id}/sources/{source_id}/fragments")
    def fragments(project_id: str, source_id: str, kind: str = "paragraph", limit: int = 30, cursor: int | None = None):
        return list_fragments(project_for(project_id), source_id, kind=kind, limit=limit, cursor=cursor)

    @application.get("/api/v1/projects/{project_id}/sources/{source_id}/context")
    def context(project_id: str, source_id: str, start_byte: int = Query(), end_byte: int = Query()):
        return context_for(project_for(project_id), source_id, start_byte, end_byte)

    @application.get("/api/v1/projects/{project_id}/sources/{source_id}/occurrences")
    def find_occurrences(project_id: str, source_id: str, text: str = Query(min_length=1)):
        return occurrences(project_for(project_id), source_id, text)

    @application.post("/api/v1/projects/{project_id}/encounters")
    def encounter(project_id: str, body: EncounterBody):
        project = project_for(project_id)
        result = run_encounter(
            project,
            text=body.text,
            source_id=body.source_id,
            start_byte=body.start_byte,
            end_byte=body.end_byte,
            views=body.views,
            limit=body.limit,
            include_same_document=body.include_same_document,
            include_same_family=body.include_same_family,
        )
        if result["semantic"]["state"] == "missing":
            result["semantic"] = _follow_embedding(project, body.text)
        return result

    @application.get("/api/v1/projects/{project_id}/encounters/{encounter_id}")
    def read_encounter(project_id: str, encounter_id: str):
        return get_encounter(project_for(project_id), encounter_id)

    @application.post("/api/v1/projects/{project_id}/encounters/browse")
    def browse(project_id: str):
        return another_passage(project_for(project_id))

    @application.post("/api/v1/projects/{project_id}/correspondences")
    def save_correspondence(project_id: str, body: CorrespondenceBody):
        return create_correspondence(
            project_for(project_id),
            members=[member.model_dump() for member in body.members],
            title=body.title,
            interpretation=body.interpretation,
            producer=body.producer,
            encounter_id=body.encounter_id,
        )

    @application.get("/api/v1/projects/{project_id}/correspondences")
    def correspondences(project_id: str, limit: int = 50):
        return list_correspondences(project_for(project_id), limit=limit)

    @application.get("/api/v1/projects/{project_id}/correspondences/{correspondence_id}")
    def correspondence(project_id: str, correspondence_id: str):
        return get_correspondence(project_for(project_id), correspondence_id)

    @application.post("/api/v1/projects/{project_id}/correspondences/{correspondence_id}/interpretation")
    def interpretation(project_id: str, correspondence_id: str, body: InterpretationBody):
        return revise_interpretation(project_for(project_id), correspondence_id, body.body, body.producer)

    @application.post("/api/v1/projects/{project_id}/correspondences/{correspondence_id}/disposition")
    def disposition(project_id: str, correspondence_id: str, body: DispositionBody):
        return set_disposition(project_for(project_id), correspondence_id, body.disposition)


def _follow_embedding(project, text: str) -> dict:
    active = project.active_job()
    if active is not None:
        if active["operation"] == "embed_encounter":
            return {"state": "queued", "job_id": active["id"], "message": "Related meaning is being prepared."}
        return {
            "state": "waiting",
            "message": "A job is already running. Related meaning waits until it finishes.",
        }
    latest = project.latest_succeeded("embed_encounter")
    if latest and latest["request"].get("query_text") == text and latest["result"].get("query_embedded") is False:
        return {
            "state": "unavailable",
            "message": latest["result"].get("message") or "That passage was not embedded.",
        }
    failed = project.latest_job()
    if (
        failed
        and failed["operation"] == "embed_encounter"
        and failed["state"] == "failed"
        and failed["request"].get("query_text") == text
        and failed["error"]
        and failed["error"].get("code") == "CAPABILITY_UNAVAILABLE"
    ):
        return {
            "state": "unavailable",
            "message": failed["error"].get("message") or "The embedding model is not available.",
        }
    job = project.submit_job(
        "embed_encounter",
        {"query_text": text, "collection": "imported"},
        str(uuid.uuid4()),
    )
    return {"state": "queued", "job_id": job["id"], "message": "Related meaning is being prepared."}


def _source_bytes(body: ImportBody) -> bytes:
    if body.content_base64 is not None and body.text is not None:
        raise ProjectError("INVALID_TEXT", "Send the file bytes or the pasted text, not both.")
    if body.content_base64 is not None:
        try:
            return base64.b64decode(body.content_base64, validate=True)
        except Exception as error:
            raise ProjectError("INVALID_TEXT", "Those file bytes could not be read.") from error
    if body.text is not None:
        return body.text.encode("utf-8")
    raise ProjectError("INVALID_TEXT", "Paste text or choose a UTF-8 file.")


def _import_fields(body: ImportBody) -> dict:
    return {
        "title": body.title,
        "author": body.author,
        "source_uri": body.source_uri,
        "source_date": body.source_date,
        "language": body.language,
        "edition": body.edition,
        "notes": body.notes,
        "family_id": body.family_id,
        "filename": body.filename,
    }
