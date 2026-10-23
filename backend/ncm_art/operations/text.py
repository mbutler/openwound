"""Exact byte edits. These functions do not write a project or call a model."""

import hashlib

from ncm_art.corpus.anchors import validate_span
from ncm_art.storage.errors import ProjectError


def overlaps(start: int, end: int, other_start: int, other_end: int) -> bool:
    return start < other_end and other_start < end


def displace(donor: bytes, start: int, end: int, replacement: str) -> tuple[bytes, int, int]:
    """Replace one relative span. Other copies of the same bytes stay."""
    replacement_bytes = replacement.encode("utf-8")
    final = donor[:start] + replacement_bytes + donor[end:]
    return final, start, start + len(replacement_bytes)


def assemble(host: bytes, boundary: int, donor: bytes, separator: str) -> tuple[bytes, int, int]:
    validate_span(host, boundary, boundary)
    separator_bytes = separator.encode("utf-8")
    prefix = host[:boundary]
    suffix = host[boundary:]
    final = prefix + separator_bytes + donor + suffix
    donor_start = len(prefix) + len(separator_bytes)
    return final, donor_start, donor_start + len(donor)


def splice(host: bytes, start: int, end: int, replacement: bytes) -> bytes:
    validate_span(host, start, end)
    return host[:start] + replacement + host[end:]


def plan_protections(old: bytes, new: bytes, protections: list[dict], release: bool) -> list[dict]:
    """Carry protections whose bytes still match. Drop them only when release is explicit."""
    carried = []
    for protection in protections:
        start = protection["start_byte"]
        end = protection["end_byte"]
        if not 0 <= start < end <= len(old):
            _false_label()
        needle = old[start:end]
        if hashlib.sha256(needle).hexdigest() != protection["slice_sha256"]:
            _false_label()
        if end <= len(new) and new[start:end] == needle:
            carried.append(_moved(protection, start, end))
            continue
        places = _find_all(new, needle)
        if len(places) == 1:
            found = places[0]
            carried.append(_moved(protection, found, found + len(needle)))
            continue
        if not release:
            raise ProjectError(
                "PROTECTED_RANGE",
                "That change would alter a protected passage. Release the protection to continue.",
                status=409,
            )
    return carried


def _moved(protection: dict, start: int, end: int) -> dict:
    return {
        "start_byte": start,
        "end_byte": end,
        "slice_sha256": protection["slice_sha256"],
        "role": protection["role"],
    }


def _find_all(haystack: bytes, needle: bytes) -> list[int]:
    found = []
    cursor = 0
    while needle:
        index = haystack.find(needle, cursor)
        if index < 0:
            return found
        found.append(index)
        cursor = index + len(needle)
    return found


def _false_label() -> None:
    raise ProjectError(
        "PROTECTED_RANGE",
        "A protection label no longer matches its passage.",
        status=409,
    )
