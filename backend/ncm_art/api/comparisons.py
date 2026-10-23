"""Encode selected passages, compare saved hierarchies, and graft codes."""

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ncm_art.comparison.jobs import queue_encode, queue_graft, queue_reconstruction
from ncm_art.comparison.service import compare_hierarchies, get_comparison, list_encodings
from ncm_art.storage.errors import ProjectError


class EncodeBody(BaseModel):
    client_request_id: str
    fragment_ids: list[str] = Field(default_factory=list)
    passage_revision_ids: list[str] = Field(default_factory=list)


class CompareBody(BaseModel):
    query_representation_id: str
    prefix_count: int = 3


class PairBody(BaseModel):
    client_request_id: str
    left_representation_id: str
    right_representation_id: str
    prefix_count: int = 3


class GraftBody(BaseModel):
    client_request_id: str
    base_representation_id: str
    donor_representation_id: str
    prefix_count: int = 3
    positions: list[dict] | None = None


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

    @application.get("/api/v1/projects/{project_id}/comparisons/encodings")
    def encodings(project_id: str):
        return {"encodings": list_encodings(project_for(project_id))}

    @application.post("/api/v1/projects/{project_id}/comparisons/encodings")
    def encode(project_id: str, body: EncodeBody):
        job = queue_encode(project_for(project_id), body.fragment_ids, body.passage_revision_ids, body.client_request_id)
        return JSONResponse(status_code=202, content=job)

    @application.post("/api/v1/projects/{project_id}/comparisons/reconstructions")
    def reconstruct(project_id: str, body: PairBody):
        job = queue_reconstruction(
            project_for(project_id),
            body.left_representation_id,
            body.right_representation_id,
            body.prefix_count,
            body.client_request_id,
        )
        return JSONResponse(status_code=202, content=job)

    @application.post("/api/v1/projects/{project_id}/comparisons/grafts")
    def graft(project_id: str, body: GraftBody):
        result = queue_graft(
            project_for(project_id),
            body.base_representation_id,
            body.donor_representation_id,
            body.prefix_count,
            body.positions,
            body.client_request_id,
        )
        if result.get("queued") is False:
            return result
        return JSONResponse(status_code=202, content=result)

    @application.post("/api/v1/projects/{project_id}/comparisons")
    def create(project_id: str, body: CompareBody):
        return compare_hierarchies(project_for(project_id), body.query_representation_id, body.prefix_count)

    @application.get("/api/v1/projects/{project_id}/comparisons/{comparison_id}")
    def read(project_id: str, comparison_id: str):
        return get_comparison(project_for(project_id), comparison_id)
