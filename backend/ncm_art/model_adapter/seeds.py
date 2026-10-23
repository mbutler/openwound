"""Candidate seeds that round-trip through JSON and JavaScript.

Candidate zero uses the requested base seed. Later candidates take the first
four bytes of SHA-256("ncm-art-seed-v1:<base>:<index>") as a big-endian integer.
"""

import hashlib

from ncm_art.model_adapter.errors import AdapterError

_SEED_MAX = 0xFFFFFFFF


def _as_u32(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterError("INVALID_SAMPLING", f"{label} must be an integer.")
    if value < 0 or value > _SEED_MAX:
        raise AdapterError(
            "INVALID_SAMPLING",
            f"{label} must be an unsigned 32-bit integer.",
            {label: value},
        )
    return value


def candidate_seed(base_seed: int, candidate_index: int) -> int:
    base_seed = _as_u32(base_seed, "base_seed")
    if isinstance(candidate_index, bool) or not isinstance(candidate_index, int):
        raise AdapterError("INVALID_SAMPLING", "candidate_index must be an integer.")
    if candidate_index < 0:
        raise AdapterError(
            "INVALID_SAMPLING",
            "candidate_index must be zero or greater.",
            {"candidate_index": candidate_index},
        )
    if candidate_index == 0:
        return base_seed
    digest = hashlib.sha256(
        f"ncm-art-seed-v1:{base_seed}:{candidate_index}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:4], "big")
