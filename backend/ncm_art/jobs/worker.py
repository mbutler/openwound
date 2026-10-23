"""One spawned process that loads TinyStories and runs queued jobs."""

import threading
import time
from pathlib import Path

from ncm_art.jobs.execute import execute_job
from ncm_art.storage.library import Library


def worker_main(library_root: str) -> None:
    root = Path(library_root)
    stop = root / "worker.stop"
    ready = root / "worker.ready"
    beat = root / "worker.heartbeat"
    stop.unlink(missing_ok=True)
    ready.unlink(missing_ok=True)

    def pulse() -> None:
        while not stop.exists():
            beat.write_text(str(time.time()), encoding="utf-8")
            time.sleep(1)

    threading.Thread(target=pulse, daemon=True).start()
    library = Library(root)
    for item in library.list_projects():
        library.project(item["id"]).mark_interrupted()

    from ncm_art.model_adapter.load import load_tinystories

    try:
        bundle = load_tinystories()
    except Exception as error:
        (root / "worker.error").write_text(str(error), encoding="utf-8")
        raise
    (root / "worker.error").unlink(missing_ok=True)
    ready.write_text("cpu-fp32-eager-v1", encoding="utf-8")
    try:
        while not stop.exists():
            project = library.active_project()
            job = project.claim_next_job() if project is not None else None
            if job is None:
                time.sleep(0.25)
                continue
            execute_job(project, bundle, job)
    finally:
        ready.unlink(missing_ok=True)
        beat.unlink(missing_ok=True)


def worker_error(library: Library) -> str | None:
    path = library.root / "worker.error"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def worker_state(library: Library) -> str:
    root = library.root
    beat = root / "worker.heartbeat"
    if not beat.exists() or time.time() - beat.stat().st_mtime > 5:
        return "stopped"
    if not (root / "worker.ready").exists():
        return "starting"
    project = library.active_project()
    active = project.active_job() if project is not None else None
    if active is not None and active["state"] == "running":
        return "running"
    return "ready"
