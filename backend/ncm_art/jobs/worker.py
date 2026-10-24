"""One spawned process that runs queued jobs.

The heartbeat and ready file mean the worker is alive. TinyStories is a
separate capability and is loaded only when a job needs it. A missing
checkpoint leaves the worker up and the archive readable.
"""

import json
import threading
import time
from pathlib import Path

from ncm_art.jobs.execute import NCM_OPERATIONS, execute_job
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library

CAPABILITY_PROFILE = "tinystories-v1"


def write_capabilities(root: Path, state: str, message: str | None = None, *, capability: str = "ncm", profile: str | None = None) -> None:
    path = root / "worker.capabilities"
    payload: dict = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {}
    payload[capability] = {
        "profile": profile or (CAPABILITY_PROFILE if capability == "ncm" else "minilm-l6-v2"),
        "state": state,
        "message": message,
    }
    temporary = root / ".worker.capabilities.tmp"
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def read_capabilities(library: Library) -> dict:
    from ncm_art.providers.instruction import capability

    unknown = {
        "ncm": {"profile": CAPABILITY_PROFILE, "state": "unknown", "message": None},
        "embedding": {"profile": "minilm-l6-v2", "state": "unknown", "message": None},
        "instruction": capability(library.root),
    }
    if worker_liveness(library) == "stopped":
        return unknown
    path = library.root / "worker.capabilities"
    if not path.is_file():
        unknown["ncm"]["state"] = "unloaded"
        unknown["embedding"]["state"] = "unloaded"
        return unknown
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return unknown
    if not isinstance(payload, dict) or "ncm" not in payload:
        return unknown
    payload.setdefault("embedding", {"profile": "minilm-l6-v2", "state": "unloaded", "message": None})
    payload["instruction"] = capability(library.root)
    return payload


def dispatch_job(project, job: dict, load_ncm, library_root=None) -> None:
    if job["operation"] == "embed_encounter":
        from ncm_art.retrieval.embed_job import execute_embed

        execute_embed(project, job, library_root)
        return
    if job["operation"] == "omit_repair":
        from ncm_art.providers.repair_job import execute_repair

        try:
            execute_repair(project, job, library_root)
        except ProjectError as error:
            project.fail(job["id"], error.code, error.message, error.details)
        except Exception as error:
            project.fail(job["id"], "JOB_FAILED", str(error))
        return
    if job["operation"] == "heal_graft":
        from ncm_art.providers.healing_job import execute_healing

        try:
            execute_healing(project, job, library_root)
        except ProjectError as error:
            project.fail(job["id"], error.code, error.message, error.details)
        except Exception as error:
            project.fail(job["id"], "JOB_FAILED", str(error))
        return
    try:
        project.ensure_current()
        bundle = None
        if job["operation"] in NCM_OPERATIONS:
            bundle = load_ncm()
            if bundle is None:
                project.fail(
                    job["id"],
                    "MODEL_NOT_READY",
                    "The TinyStories checkpoint is not available.",
                )
                return
        execute_job(project, bundle, job)
    except ProjectError as error:
        project.fail(job["id"], error.code, error.message, error.details)
    except Exception as error:
        project.fail(job["id"], "JOB_FAILED", str(error))


def worker_main(library_root: str) -> None:
    root = Path(library_root)
    stop = root / "worker.stop"
    ready = root / "worker.ready"
    beat = root / "worker.heartbeat"
    stop.unlink(missing_ok=True)
    ready.unlink(missing_ok=True)
    (root / "worker.error").unlink(missing_ok=True)

    def pulse() -> None:
        while not stop.exists():
            beat.write_text(str(time.time()), encoding="utf-8")
            time.sleep(1)

    threading.Thread(target=pulse, daemon=True).start()
    library = Library(root)
    for item in library.list_projects():
        try:
            library.project(item["id"]).mark_interrupted()
        except ProjectError:
            continue
    write_capabilities(root, "unloaded")
    write_capabilities(root, "unloaded", capability="embedding", profile="minilm-l6-v2")
    ready.write_text("alive", encoding="utf-8")
    bundle_box: list = []

    def load_ncm():
        if bundle_box:
            return bundle_box[0]
        from ncm_art.model_adapter.load import load_tinystories

        try:
            bundle = load_tinystories()
        except Exception as error:
            message = getattr(error, "message", None) or str(error)
            write_capabilities(root, "unavailable", message)
            return None
        write_capabilities(root, "ready")
        bundle_box.append(bundle)
        return bundle

    try:
        while not stop.exists():
            try:
                project = library.active_project()
            except ProjectError:
                time.sleep(0.5)
                continue
            try:
                job = project.claim_next_job() if project is not None else None
                if job is None:
                    time.sleep(0.25)
                    continue
                dispatch_job(project, job, load_ncm, root)
            except Exception as error:
                (root / "worker.error").write_text(str(error), encoding="utf-8")
                time.sleep(0.5)
    finally:
        ready.unlink(missing_ok=True)
        beat.unlink(missing_ok=True)
        (root / "worker.capabilities").unlink(missing_ok=True)


def worker_error(library: Library) -> str | None:
    path = library.root / "worker.error"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def worker_liveness(library: Library) -> str:
    root = library.root
    beat = root / "worker.heartbeat"
    if not beat.exists() or time.time() - beat.stat().st_mtime > 5:
        return "stopped"
    if not (root / "worker.ready").exists():
        return "starting"
    return "ready"


def worker_state(library: Library) -> str:
    liveness = worker_liveness(library)
    if liveness != "ready":
        return liveness
    try:
        project = library.active_project()
    except ProjectError:
        return "ready"
    active = project.active_job() if project is not None else None
    if active is not None and active["state"] == "running":
        return "running"
    return "ready"
