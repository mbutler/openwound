"""Loopback API for the writing desk.

Model requests return a job. The open project is the only one the worker reads.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ncm_art import __version__
from ncm_art.jobs.worker import worker_error, worker_state
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.profile import repo_root
from ncm_art.model_adapter.sampling import validate_sampling
from ncm_art.model_adapter.seeds import candidate_seed
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library
from ncm_art.tokenize import preview_tokens

MAX_CANDIDATES = 8


class CreateProject(BaseModel):
    title: str = "Untitled"


class OpenProject(BaseModel):
    project_id: str


class DraftBody(BaseModel):
    text: str


class AnnotationBody(BaseModel):
    revision_id: str
    kind: str
    value: str


class TokenBody(BaseModel):
    text: str


class JobBody(BaseModel):
    client_request_id: str = Field(min_length=1)
    retained_level_count: int | None = None
    candidate_count: int | None = None
    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    base_seed: int | None = None


def _envelope(code: str, message: str, details: dict, status: int, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"code": code, "message": message, "details": details, "retryable": retryable},
    )


def _desk(project) -> dict:
    selected = project.selected_revision_id()
    return {
        "project": {
            "id": project.manifest()["id"],
            "title": project.manifest()["title"],
            "format_version": project.manifest()["format_version"],
        },
        "draft": project.draft(),
        "selected_revision_id": selected,
        "revisions": project.revisions(),
        "annotations": project.annotations(),
        "latest_job": project.latest_job(),
    }


def create_app(library: Library, token_counter=None) -> FastAPI:
    application = FastAPI(title="Openwound", version=__version__)

    def count_tokens(text: str) -> dict:
        if token_counter is not None:
            return token_counter(text)
        return preview_tokens(text)

    @application.exception_handler(ProjectError)
    async def on_project_error(_request, error: ProjectError):
        return _envelope(error.code, error.message, error.details, error.status, error.code == "JOB_INTERRUPTED")

    @application.exception_handler(AdapterError)
    async def on_adapter_error(_request, error: AdapterError):
        status = 409 if error.code == "INPUT_TOO_LONG" else 400
        if error.code == "MODEL_NOT_READY":
            status = 503
        return _envelope(error.code, error.message, error.details, status, error.code == "MODEL_NOT_READY")

    @application.get("/api/v1/status")
    def status():
        project = library.active_project()
        return {
            "app_version": __version__,
            "project_id": None if project is None else project.manifest()["id"],
            "worker": worker_state(library),
            "worker_error": worker_error(library),
            "model_profile": "tinystories-v1",
            "execution_profile": "cpu-fp32-eager-v1",
        }

    @application.get("/api/v1/projects")
    def list_projects():
        return {"projects": library.list_projects(), "active_project_id": library.active_project_id()}

    @application.post("/api/v1/projects")
    def create_project(body: CreateProject):
        project = library.create_project(body.title)
        opened = False
        try:
            library.open_project(project.manifest()["id"])
            opened = True
        except ProjectError as error:
            if error.code != "JOB_ACTIVE":
                raise
        manifest = project.manifest()
        manifest["opened"] = opened
        return manifest

    @application.post("/api/v1/projects/open")
    def open_project(body: OpenProject):
        project = library.open_project(body.project_id)
        return _desk(project)

    @application.get("/api/v1/desk")
    def desk():
        return _desk(library.require_active())

    @application.put("/api/v1/draft")
    def save_draft(body: DraftBody):
        return library.require_active().set_draft(body.text)

    @application.post("/api/v1/passages")
    def save_passage(body: DraftBody):
        project = library.require_active()
        project.set_draft(body.text)
        return project.ensure_input_revision()

    @application.post("/api/v1/passages/{revision_id}/select")
    def select_passage(revision_id: str):
        return library.require_active().select(revision_id)

    @application.post("/api/v1/passages/{revision_id}/reject")
    def reject_passage(revision_id: str):
        return library.require_active().set_disposition(revision_id, "rejected")

    @application.get("/api/v1/passages/{revision_id}/history")
    def passage_history(revision_id: str):
        project = library.require_active()
        revision = project.revision(revision_id)
        run = None
        if revision["parents"] and revision["parents"][0].get("run_id"):
            run = project.run(revision["parents"][0]["run_id"])
        return {
            "revision": revision,
            "run": run,
            "annotations": project.annotations(revision_id),
        }

    @application.post("/api/v1/annotations")
    def add_annotation(body: AnnotationBody):
        return library.require_active().add_annotation(body.revision_id, body.kind, body.value)

    @application.post("/api/v1/tokenize-preview")
    def tokenize(body: TokenBody):
        return count_tokens(body.text)

    def _queue(operation: str, recipe: dict, client_request_id: str):
        project = library.require_active()
        passage = project.ensure_input_revision()
        counted = count_tokens(passage["text"])
        if counted["token_count"] == 0:
            raise ProjectError("INPUT_EMPTY", "Enter a nonempty passage.")
        if counted["too_long"]:
            raise AdapterError(
                "INPUT_TOO_LONG",
                f"Select a passage of at most {counted['text_length']} BPE tokens. This one is {counted['token_count']}.",
                {"token_count": counted["token_count"], "text_length": counted["text_length"]},
            )
        recipe = dict(recipe)
        recipe["passage_revision_id"] = passage["id"]
        recipe["token_count"] = counted["token_count"]
        job = project.submit_job(operation, recipe, client_request_id)
        return JSONResponse(status_code=202, content=job)

    @application.post("/api/v1/jobs/reconstruct")
    def reconstruct(body: JobBody):
        return _queue(
            "reconstruct",
            {
                "model_profile_id": "tinystories-v1",
                "execution_profile_id": "cpu-fp32-eager-v1",
            },
            body.client_request_id,
        )

    @application.post("/api/v1/jobs/variants")
    def variants(body: JobBody):
        temperature = 1.0 if body.temperature is None else body.temperature
        top_k = 0 if body.top_k is None else body.top_k
        top_p = 1.0 if body.top_p is None else body.top_p
        sampling = validate_sampling(temperature, top_k, top_p)
        retained = 3 if body.retained_level_count is None else body.retained_level_count
        count = 4 if body.candidate_count is None else body.candidate_count
        if isinstance(retained, bool) or not isinstance(retained, int) or not 0 <= retained <= 12:
            raise ProjectError(
                "INVALID_SAMPLING",
                "retained_level_count must be an integer from 0 through 12.",
                {"retained_level_count": retained},
            )
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= MAX_CANDIDATES:
            raise ProjectError(
                "INVALID_SAMPLING",
                f"candidate_count must be an integer from 1 through {MAX_CANDIDATES}.",
                {"candidate_count": count},
            )
        recipe = {
            "model_profile_id": "tinystories-v1",
            "execution_profile_id": "cpu-fp32-eager-v1",
            "retained_level_count": retained,
            "candidate_count": count,
            "sampling": {
                "temperature": sampling.temperature,
                "top_k": sampling.top_k,
                "top_p": sampling.top_p,
            },
        }
        if body.base_seed is not None:
            recipe["base_seed"] = candidate_seed(body.base_seed, 0)
        return _queue("variants", recipe, body.client_request_id)

    @application.get("/api/v1/jobs/{job_id}")
    def get_job(job_id: str):
        return library.require_active().job(job_id)

    @application.post("/api/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return library.require_active().cancel(job_id)

    @application.get("/api/v1/exports/reading.json")
    def export_json():
        project = library.require_active()
        payload = _desk(project)
        return JSONResponse(
            content=payload,
            headers={"Content-Disposition": 'attachment; filename="openwound-reading.json"'},
        )

    @application.get("/api/v1/exports/reading.txt")
    def export_text():
        project = library.require_active()
        lines = [project.manifest()["title"], ""]
        for revision in project.revisions():
            if revision["disposition"] == "rejected":
                continue
            lines.append(f"[{revision['origin_kind']}]")
            lines.append(revision["text"])
            lines.append("")
        return PlainTextResponse(
            "\n".join(lines),
            headers={"Content-Disposition": 'attachment; filename="openwound-reading.txt"'},
        )

    dist = repo_root() / "frontend" / "dist"
    if dist.is_dir():
        application.mount("/", StaticFiles(directory=dist, html=True), name="studio")
    return application


def _default_library() -> Library:
    configured = __import__("os").environ.get("NCM_ART_LIBRARY")
    root = Path(configured) if configured else repo_root() / ".projects"
    return Library(root)


app = create_app(_default_library())
