"""Project-scoped work, influence, preview, and commit routes."""

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ncm_art.storage.errors import ProjectError

from ncm_art.works.service import (
    bind_influence,
    commit_prepared_application,
    create_influence,
    create_work,
    edit_candidate,
    edit_entry,
    get_preview,
    get_work,
    list_influences,
    list_works,
    preview_protected_insert,
    preview_return,
    preview_transfer,
    queue_omission_repair,
    reject_preview,
    remove_entry,
    reorder_entries,
    restore_entry,
    retarget_held_name,
    save_entry_draft,
    unbind_influence,
)


class WorkBody(BaseModel):
    title: str


class AnchorBody(BaseModel):
    owner_kind: str
    owner_id: str
    start_byte: int
    end_byte: int
    text_sha256: str | None = None
    slice_sha256: str | None = None
    text: str | None = None


class MarkBody(BaseModel):
    start_byte: int
    end_byte: int


class InfluenceBody(BaseModel):
    name: str
    interpretation: str
    template: str | None = None
    parameters: dict | None = None
    correspondence_id: str | None = None
    influence_id: str | None = None


class BindBody(BaseModel):
    influence_version_id: str
    expected_work_state_version: int


class StateBody(BaseModel):
    expected_work_state_version: int


class ReorderBody(BaseModel):
    entry_ids: list[str]
    expected_work_state_version: int


class EditBody(BaseModel):
    text: str
    expected_work_state_version: int
    release_protection: bool = False


class DraftBody(BaseModel):
    text: str


class TransferBody(BaseModel):
    work_id: str
    position: int
    donor: AnchorBody
    mark: MarkBody | None = None


class ProtectedBody(BaseModel):
    work_id: str
    entry_id: str
    boundary: int
    separator: str = ""
    donor: AnchorBody
    mark: MarkBody | None = None
    release_protection: bool = False


class ReturnBody(BaseModel):
    expected_work_state_version: int
    target_start: int | None = None
    target_end: int | None = None
    release_protection: bool = False


class RetargetBody(BaseModel):
    expected_work_state_version: int
    start_byte: int
    end_byte: int


class CandidateBody(BaseModel):
    text: str
    release_protection: bool = False


class DestinationBody(BaseModel):
    kind: str
    position: int | None = None
    entry_id: str | None = None
    expected_revision_id: str | None = None


class RepairBody(BaseModel):
    client_request_id: str
    passage_revision_id: str
    omission: MarkBody
    context: MarkBody
    destination: DestinationBody
    candidate_count: int = 3
    release_protection: bool = False


class CommitBody(BaseModel):
    client_request_id: str
    preview_id: str
    candidate_id: str
    expected_work_state_version: int


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

    @application.post("/api/v1/projects/{project_id}/works")
    def post_work(project_id: str, body: WorkBody):
        return create_work(project_for(project_id), body.title)

    @application.get("/api/v1/projects/{project_id}/works")
    def get_works(project_id: str):
        return list_works(project_for(project_id))

    @application.get("/api/v1/projects/{project_id}/works/{work_id}")
    def one_work(project_id: str, work_id: str):
        return get_work(project_for(project_id), work_id)

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/entries/reorder")
    def reorder(project_id: str, work_id: str, body: ReorderBody):
        return reorder_entries(
            project_for(project_id), work_id, body.entry_ids, body.expected_work_state_version
        )

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/entries/{entry_id}/remove")
    def remove(project_id: str, work_id: str, entry_id: str, body: StateBody):
        return remove_entry(project_for(project_id), work_id, entry_id, body.expected_work_state_version)

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/entries/{entry_id}/restore")
    def restore(project_id: str, work_id: str, entry_id: str, body: StateBody):
        return restore_entry(project_for(project_id), work_id, entry_id, body.expected_work_state_version)

    @application.put("/api/v1/projects/{project_id}/works/{work_id}/entries/{entry_id}/draft")
    def draft(project_id: str, work_id: str, entry_id: str, body: DraftBody):
        return save_entry_draft(project_for(project_id), work_id, entry_id, body.text)

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/entries/{entry_id}/edit")
    def edit(project_id: str, work_id: str, entry_id: str, body: EditBody):
        return edit_entry(
            project_for(project_id),
            work_id,
            entry_id,
            body.text,
            body.expected_work_state_version,
            body.release_protection,
        )

    @application.get("/api/v1/projects/{project_id}/influences")
    def influences(project_id: str):
        return list_influences(project_for(project_id))

    @application.post("/api/v1/projects/{project_id}/influences")
    def post_influence(project_id: str, body: InfluenceBody):
        return create_influence(
            project_for(project_id),
            body.name,
            body.interpretation,
            body.template,
            body.parameters,
            body.correspondence_id,
            body.influence_id,
        )

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/binding")
    def bind(project_id: str, work_id: str, body: BindBody):
        return bind_influence(
            project_for(project_id), work_id, body.influence_version_id, body.expected_work_state_version
        )

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/binding/unbind")
    def unbind(project_id: str, work_id: str, body: StateBody):
        return unbind_influence(project_for(project_id), work_id, body.expected_work_state_version)

    @application.post("/api/v1/projects/{project_id}/previews/transfer")
    def transfer(project_id: str, body: TransferBody):
        return preview_transfer(
            project_for(project_id),
            body.work_id,
            body.position,
            body.donor.model_dump(),
            None if body.mark is None else body.mark.model_dump(),
        )

    @application.post("/api/v1/projects/{project_id}/previews/protected-insert")
    def protected(project_id: str, body: ProtectedBody):
        return preview_protected_insert(
            project_for(project_id),
            body.work_id,
            body.entry_id,
            body.boundary,
            body.donor.model_dump(),
            body.separator,
            None if body.mark is None else body.mark.model_dump(),
            body.release_protection,
        )

    @application.get("/api/v1/projects/{project_id}/previews/{preview_id}")
    def preview(project_id: str, preview_id: str):
        return get_preview(project_for(project_id), preview_id)

    @application.post("/api/v1/projects/{project_id}/previews/{preview_id}/edit")
    def edit_preview(project_id: str, preview_id: str, body: CandidateBody):
        return edit_candidate(project_for(project_id), preview_id, body.text, body.release_protection)

    @application.post("/api/v1/projects/{project_id}/previews/{preview_id}/reject")
    def reject(project_id: str, preview_id: str):
        return reject_preview(project_for(project_id), preview_id)

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/commit")
    def commit(project_id: str, work_id: str, body: CommitBody):
        return commit_prepared_application(
            project_for(project_id),
            project_id,
            work_id,
            body.client_request_id,
            body.preview_id,
            body.candidate_id,
            body.expected_work_state_version,
        )

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/repairs")
    def repair(project_id: str, work_id: str, body: RepairBody):
        job = queue_omission_repair(
            project_for(project_id),
            library.root,
            work_id,
            body.passage_revision_id,
            body.omission.model_dump(),
            body.context.model_dump(),
            body.destination.model_dump(),
            body.client_request_id,
            body.candidate_count,
            body.release_protection,
        )
        return JSONResponse(status_code=202, content=job)

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/held-names/{held_id}/return")
    def returning(project_id: str, work_id: str, held_id: str, body: ReturnBody):
        return preview_return(
            project_for(project_id),
            work_id,
            held_id,
            body.expected_work_state_version,
            body.target_start,
            body.target_end,
            body.release_protection,
        )

    @application.post("/api/v1/projects/{project_id}/works/{work_id}/held-names/{held_id}/retarget")
    def retarget(project_id: str, work_id: str, held_id: str, body: RetargetBody):
        return retarget_held_name(
            project_for(project_id),
            work_id,
            held_id,
            body.expected_work_state_version,
            body.start_byte,
            body.end_byte,
        )
