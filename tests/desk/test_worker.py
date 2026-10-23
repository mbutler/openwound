"""The worker can be alive while the TinyStories checkpoint is missing."""

import threading
import time

from ncm_art.jobs.worker import dispatch_job, read_capabilities, worker_main, worker_state
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.storage.library import Library


def _queued(tmp_path):
    library = Library(tmp_path)
    project = library.create_project("Desk")
    library.open_project(project.manifest()["id"])
    project.set_draft("Hello")
    revision = project.ensure_input_revision()
    job = project.submit_job("variants", {"passage_revision_id": revision["id"]}, "missing-model")
    return library, project, job


def test_dispatch_fails_the_job_when_the_checkpoint_is_missing(tmp_path):
    _library, project, job = _queued(tmp_path)
    claimed = project.claim_next_job()
    dispatch_job(project, claimed, lambda: None)
    finished = project.job(job["id"])
    assert finished["state"] == "failed"
    assert finished["error"]["code"] == "MODEL_NOT_READY"
    assert project.draft()["text"] == "Hello"
    assert project.selected_revision_id() is not None
    assert project.revision(project.selected_revision_id())["text"] == "Hello"


def test_the_worker_stays_alive_without_the_checkpoint(tmp_path, monkeypatch):
    def missing(*_args, **_kwargs):
        raise AdapterError("MODEL_NOT_READY", "Missing model file tokenizer.pt.")

    monkeypatch.setattr("ncm_art.model_adapter.load.load_tinystories", missing)
    library, project, job = _queued(tmp_path)
    thread = threading.Thread(target=worker_main, args=(str(tmp_path),))
    thread.start()
    stop = tmp_path / "worker.stop"
    try:
        deadline = time.time() + 5
        finished = None
        while time.time() < deadline:
            finished = project.job(job["id"])
            if finished["state"] == "failed":
                break
            time.sleep(0.05)
        assert finished is not None
        assert finished["state"] == "failed"
        assert finished["error"]["code"] == "MODEL_NOT_READY"
        assert thread.is_alive()
        assert worker_state(library) == "ready"
        assert read_capabilities(library)["ncm"]["state"] == "unavailable"
        assert "tokenizer.pt" in read_capabilities(library)["ncm"]["message"]
        assert not (tmp_path / "worker.error").exists()
        assert project.draft()["text"] == "Hello"
    finally:
        stop.write_text("stop", encoding="utf-8")
        thread.join(2)
        if thread.is_alive():
            stop.write_text("stop", encoding="utf-8")
            thread.join(3)
    assert not thread.is_alive()
