"""Ask for surroundings around a protected span. Nothing here adopts them."""

from pathlib import Path

from ncm_art.operations.healing import (
    PROMPT_VERSION,
    build_provider_request,
    parse_healing_response,
    provider_surroundings,
    repeated_donor,
)
from ncm_art.providers.instruction import chat_completion, load_profile
from ncm_art.storage.errors import ProjectError
from ncm_art.works.service import record_healing_candidate


def execute_healing(project, job: dict, library_root, transport=None) -> None:
    job_id = job["id"]
    recipe = job["request"]
    try:
        profile = load_profile(Path(library_root)) if library_root else None
    except ProjectError as error:
        project.fail(job_id, error.code, error.message, error.details)
        return
    if profile is None:
        project.fail(
            job_id,
            "CAPABILITY_UNAVAILABLE",
            "No instruction provider is configured. Import, transfer, and returning a name still work.",
        )
        return
    sender = transport or (lambda body: chat_completion(profile, body))
    raw = _passage(project, recipe)
    host = recipe["host"]
    donor = recipe["donor"]
    window = provider_surroundings(raw, host["start_byte"], host["end_byte"], donor["start_byte"], donor["end_byte"])
    attempts = []
    preview_ids = []
    count = len(recipe["seeds"])
    for index, seed in enumerate(recipe["seeds"]):
        if project.cancel_requested(job_id):
            project.finish_cancelled(job_id, {"preview_ids": preview_ids, "attempts": attempts})
            return
        project.update_progress(
            job_id,
            {"stage": f"preparing healing {index + 1}", "candidate": index + 1, "candidate_count": count},
        )
        status, attempt, preview_id = _candidate(
            project, job_id, recipe, profile, window, raw, seed, index, sender
        )
        if attempt:
            attempts.append(attempt)
        if status == "cancel":
            project.finish_cancelled(job_id, {"preview_ids": preview_ids, "attempts": attempts})
            return
        if status == "unavailable":
            project.fail(
                job_id,
                "CAPABILITY_UNAVAILABLE",
                attempt["message"],
                {"preview_ids": preview_ids, "attempts": attempts},
            )
            return
        if preview_id:
            preview_ids.append(preview_id)
    if not preview_ids:
        project.fail(
            job_id,
            "INVALID_PROVIDER_OUTPUT",
            "The instruction provider did not return usable surroundings. Nothing was added to the work.",
            {"attempts": attempts},
        )
        return
    project.succeed(job_id, {"preview_ids": preview_ids, "attempts": attempts, "prompt_version": PROMPT_VERSION})


def _candidate(project, job_id, recipe, profile, window, raw, seed, index, sender):
    last = None
    for attempt_number in (1, 2):
        if project.cancel_requested(job_id):
            return "cancel", last, None
        body = build_provider_request(profile["model"], window, seed)
        try:
            payload = sender(body)
        except ProjectError as error:
            if error.code == "CAPABILITY_UNAVAILABLE":
                return "unavailable", _attempt(index, attempt_number, seed, body, None, "unavailable", error.message), None
            payload = {"error": error.message}
            last = _attempt(index, attempt_number, seed, body, payload, "malformed", error.message)
            continue
        try:
            before, after = parse_healing_response(payload)
            if repeated_donor(
                raw,
                recipe["host"]["start_byte"],
                recipe["host"]["end_byte"],
                recipe["donor"]["start_byte"],
                recipe["donor"]["end_byte"],
                before.encode("utf-8"),
                after.encode("utf-8"),
            ):
                raise ProjectError(
                    "INVALID_PROVIDER_OUTPUT",
                    "The response repeated the protected span. That span stays only where the server places it.",
                    {"reason": "duplicate_protected"},
                    status=422,
                )
        except ProjectError as error:
            last = _attempt(index, attempt_number, seed, body, payload, error.details.get("reason", "malformed"), error.message)
            continue
        call = _call(profile, body, payload)
        try:
            preview_id = record_healing_candidate(project, recipe, before, after, call)
        except ProjectError as error:
            last = _attempt(index, attempt_number, seed, body, payload, "conflict", error.message)
            return "failed", last, None
        accepted = _attempt(index, attempt_number, seed, body, payload, "accepted", None)
        accepted["preview_id"] = preview_id
        accepted["actual_model"] = payload.get("model") if isinstance(payload.get("model"), str) else None
        return "accepted", accepted, preview_id
    return "failed", last, None


def _passage(project, recipe) -> bytes:
    with project._conn() as conn:
        row = conn.execute(
            "SELECT text_sha256 FROM passage_revision WHERE id=?",
            (recipe["passage_revision_id"],),
        ).fetchone()
    if row is None:
        raise ProjectError("NOT_FOUND", "That passage is not in this project.", status=404)
    return project.read_asset_bytes(row["text_sha256"])


def _call(profile, body, payload) -> dict:
    return {
        "endpoint_kind": profile["endpoint_kind"],
        "model": profile["model"],
        "actual_model": payload.get("model") if isinstance(payload.get("model"), str) else None,
        "prompt_version": PROMPT_VERSION,
        "temperature": body["temperature"],
        "max_tokens": body["max_tokens"],
        "seed": body["seed"],
        "messages": body["messages"],
        "response_format": body["response_format"],
        "finish_reason": payload.get("choices", [{}])[0].get("finish_reason") if payload.get("choices") else None,
    }


def _attempt(index, number, seed, body, payload, status, message):
    return {
        "index": index,
        "attempt": number,
        "seed": seed,
        "request": {
            "model": body["model"],
            "temperature": body["temperature"],
            "max_tokens": body["max_tokens"],
            "seed": seed,
            "messages": body["messages"],
            "response_format": body["response_format"],
        },
        "response": payload,
        "status": status,
        "message": message,
    }
