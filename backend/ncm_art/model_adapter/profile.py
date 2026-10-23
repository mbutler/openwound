"""Frozen TinyStories profile constants.

One-based level numbers belong in the interface. These lengths and offsets
are zero-based and follow the specification's split of a flat 641-code hierarchy.
"""

import json
from pathlib import Path

LEVELS = [1, 8, 16, 24, 32, 40, 52, 64, 76, 92, 108, 128]
OFFSETS = [0, 1, 9, 25, 49, 81, 121, 173, 237, 313, 405, 513, 641]
TEXT_LENGTH = 128
CODEBOOK_SIZE = 4096
FLAT_CODE_COUNT = 641
PROFILE_ID = "tinystories-v1"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_profile() -> dict:
    path = repo_root() / "model_profiles" / "tinystories-v1.json"
    with path.open(encoding="utf-8") as handle:
        profile = json.load(handle)
    if profile["level_lengths"] != LEVELS or profile["level_offsets"] != OFFSETS:
        raise ValueError(f"{path} does not match the adapter's level tables.")
    if profile["flat_code_count"] != sum(LEVELS) or OFFSETS[-1] != sum(LEVELS):
        raise ValueError("TinyStories level offsets do not cover the flat hierarchy.")
    return profile
