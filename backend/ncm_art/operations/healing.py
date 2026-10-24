"""Protected host healing. The model writes surroundings; the server places the donor."""

import json

from ncm_art.corpus.anchors import validate_span
from ncm_art.operations.text import overlaps
from ncm_art.storage.errors import ProjectError

PROMPT_VERSION = "heal-around-protected-graft-v1"
MAX_SIDE_BYTES = 512
TEMPERATURE = 0.7
MAX_TOKENS = 512

SYSTEM_PROMPT = (
    "The user message shows only the text before a protected span and the text after it. "
    "The protected span is not included. "
    "Reply with a JSON object and no other text. "
    "The object has two string fields, before and after, which replace those surroundings."
)

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "protected_host_healing",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["before", "after"],
            "properties": {"before": {"type": "string"}, "after": {"type": "string"}},
        },
    },
}


def validate_healing_spans(passage: bytes, host_start: int, host_end: int, donor_start: int, donor_end: int) -> None:
    """The donor is one nonempty span inside the host region that may be rewritten."""
    if not (0 <= host_start <= donor_start < donor_end <= host_end <= len(passage)):
        raise ProjectError("INVALID_SPAN", "The protected span has to sit inside the rewritten region.")
    validate_span(passage, host_start, host_end)
    validate_span(passage, donor_start, donor_end)


def surroundings_message(before: str, after: str) -> str:
    """The only passage text the provider is allowed to see."""
    return f"Before the protected span:\n{before}\n\nAfter the protected span:\n{after}"


def provider_surroundings(passage: bytes, host_start: int, host_end: int, donor_start: int, donor_end: int) -> str:
    """The host with the donor removed. Another copy of those bytes in the surroundings stays."""
    validate_healing_spans(passage, host_start, host_end, donor_start, donor_end)
    before = passage[host_start:donor_start].decode("utf-8")
    after = passage[donor_end:host_end].decode("utf-8")
    return surroundings_message(before, after)


def repeated_donor(
    passage: bytes,
    host_start: int,
    host_end: int,
    donor_start: int,
    donor_end: int,
    before: bytes,
    after: bytes,
) -> bool:
    """True when the assembled passage would contain an extra copy of the protected span."""
    donor = passage[donor_start:donor_end]
    final, _start, _end = assemble_healing(passage, host_start, host_end, donor_start, donor_end, before, after)
    return final.count(donor) > passage.count(donor)


def surroundings_conflict(start: int, end: int, host_start: int, donor_start: int, donor_end: int, host_end: int) -> bool:
    """A protection conflicts when the rewrite would change its bytes."""
    return overlaps(start, end, host_start, donor_start) or overlaps(start, end, donor_end, host_end)


def assemble_healing(
    passage: bytes,
    host_start: int,
    host_end: int,
    donor_start: int,
    donor_end: int,
    before: bytes,
    after: bytes,
) -> tuple[bytes, int, int]:
    """Keep every byte outside the host, and put the exact donor between the new surroundings."""
    validate_healing_spans(passage, host_start, host_end, donor_start, donor_end)
    donor = passage[donor_start:donor_end]
    final = passage[:host_start] + before + donor + after + passage[host_end:]
    placed = host_start + len(before)
    return final, placed, placed + len(donor)


def build_provider_request(model: str, window: str, seed: int) -> dict:
    return {
        "model": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "seed": seed,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": window},
        ],
        "response_format": RESPONSE_FORMAT,
    }


def parse_healing_response(payload: dict) -> tuple[str, str]:
    """Accept one finished JSON object. The caller checks for an extra protected copy."""
    if not isinstance(payload, dict):
        _malformed()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        _malformed()
    choice = choices[0]
    if choice.get("finish_reason") != "stop":
        raise ProjectError(
            "INVALID_PROVIDER_OUTPUT",
            "The response stopped before it was finished.",
            {"reason": "incomplete"},
            status=422,
        )
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        _malformed()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        _malformed()
    if not isinstance(parsed, dict) or set(parsed) != {"before", "after"}:
        _malformed()
    before = parsed["before"]
    after = parsed["after"]
    if not isinstance(before, str) or not isinstance(after, str):
        _malformed()
    _budget(before)
    _budget(after)
    return before, after


def _budget(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_SIDE_BYTES:
        raise ProjectError(
            "INVALID_PROVIDER_OUTPUT",
            f"A surrounding is longer than {MAX_SIDE_BYTES} bytes.",
            {"reason": "over_budget", "max_side_bytes": MAX_SIDE_BYTES},
            status=422,
        )


def _malformed() -> None:
    raise ProjectError(
        "INVALID_PROVIDER_OUTPUT",
        "The response was not the requested JSON object.",
        {"reason": "malformed"},
        status=422,
    )
