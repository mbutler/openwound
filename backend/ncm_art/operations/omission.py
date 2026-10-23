"""Marked omission. The provider sees one window; the passage keeps every other byte."""

import json

from ncm_art.corpus.anchors import validate_span
from ncm_art.storage.errors import ProjectError

GAP_MARKER = "_____"
PROMPT_VERSION = "omit-span-v1"
MAX_REPLACEMENT_BYTES = 512
TEMPERATURE = 0.7
MAX_TOKENS = 256

SYSTEM_PROMPT = (
    "The user message is a passage with one gap marked by _____. "
    "Reply with a JSON object and no other text. "
    "The object has one field, replacement_text, containing only the text that fills that gap."
)

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "omission_repair",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["replacement_text"],
            "properties": {"replacement_text": {"type": "string"}},
        },
    },
}


def provider_window(passage: bytes, context_start: int, context_end: int, omission_start: int, omission_end: int) -> bytes:
    """The declared window with one occurrence removed. Other copies of that text stay."""
    if not (context_start <= omission_start < omission_end <= context_end):
        raise ProjectError("INVALID_SPAN", "The context window must contain the omitted span.")
    validate_span(passage, context_start, context_end)
    validate_span(passage, omission_start, omission_end)
    gap = GAP_MARKER.encode("utf-8")
    return passage[context_start:omission_start] + gap + passage[omission_end:context_end]


def assemble_repair(passage: bytes, omission_start: int, omission_end: int, replacement: bytes) -> bytes:
    """Put the replacement between the exact bytes that were not omitted."""
    if omission_start >= omission_end:
        raise ProjectError("INVALID_SPAN", "Mark a nonempty omission.")
    validate_span(passage, omission_start, omission_end)
    try:
        replacement.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError("INVALID_TEXT", "The replacement is not valid UTF-8.") from error
    return passage[:omission_start] + replacement + passage[omission_end:]


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


def parse_provider_response(payload: dict) -> str:
    """Accept one finished JSON object. Anything else is refused, not repaired by guessing."""
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
    if not isinstance(parsed, dict) or set(parsed) != {"replacement_text"} or not isinstance(parsed["replacement_text"], str):
        _malformed()
    text = parsed["replacement_text"]
    if text == "":
        _malformed()
    if len(text.encode("utf-8")) > MAX_REPLACEMENT_BYTES:
        raise ProjectError(
            "INVALID_PROVIDER_OUTPUT",
            f"The replacement is longer than {MAX_REPLACEMENT_BYTES} bytes.",
            {"reason": "over_budget", "max_replacement_bytes": MAX_REPLACEMENT_BYTES},
            status=422,
        )
    return text


def _malformed() -> None:
    raise ProjectError(
        "INVALID_PROVIDER_OUTPUT",
        "The response was not the requested JSON object.",
        {"reason": "malformed"},
        status=422,
    )
