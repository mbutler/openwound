"""Exact UTF-8 spans over an immutable text.

Offsets are half-open byte positions. A span is one occurrence, never the
first copy of a repeated string.
"""

import hashlib

from ncm_art.storage.errors import ProjectError


def validate_span(raw: bytes, start: int, end: int, expected: str | None = None) -> bytes:
    if not 0 <= start <= end <= len(raw):
        raise ProjectError("INVALID_SPAN", "That range is outside the immutable text.")
    try:
        raw[:start].decode("utf-8")
        raw[:end].decode("utf-8")
        selected = raw[start:end]
        decoded = selected.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ProjectError(
            "INVALID_SPAN",
            "That range splits a UTF-8 character.",
            {"reason": str(error)},
        ) from error
    if expected is not None and decoded != expected:
        raise ProjectError("INVALID_SPAN", "The selected text does not match this revision.")
    return selected


def make_anchor(owner_kind: str, owner_id: str, raw: bytes, start: int, end: int) -> dict:
    selected = validate_span(raw, start, end)
    return {
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "text_sha256": hashlib.sha256(raw).hexdigest(),
        "start_byte": start,
        "end_byte": end,
        "slice_sha256": hashlib.sha256(selected).hexdigest(),
    }


def find_occurrences(raw: bytes, needle: str) -> list[tuple[int, int]]:
    if needle == "":
        raise ProjectError("INVALID_SPAN", "The search text is empty.")
    encoded = needle.encode("utf-8")
    spans = []
    cursor = 0
    while True:
        found = raw.find(encoded, cursor)
        if found < 0:
            return spans
        spans.append((found, found + len(encoded)))
        cursor = found + len(encoded)


def string_span_to_bytes(text: str, start: int, end: int, base: int) -> tuple[int, int]:
    prefix = text[:start].encode("utf-8")
    piece = text[start:end].encode("utf-8")
    return base + len(prefix), base + len(prefix) + len(piece)
