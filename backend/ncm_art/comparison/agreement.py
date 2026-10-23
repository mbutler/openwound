"""Categorical slot agreement and a common-code baseline.

Slots are weighted equally, so a longer level contributes more. An average of
per-level rates would be a different metric. Code numbers are categories:
nothing here treats them as distances.
"""

from collections import Counter
from fractions import Fraction

from ncm_art.storage.errors import ProjectError

METRIC_ID = "slot-agreement-v1"
BAND_POLICY = "unpadded-token-length-bands-16-v1"
BAND_WIDTH = 16
SPARSE_BELOW = 8
PREPROCESSING = "tinystories-bpe-pad-to-128-v1"


def require_prefix(level_count: int, prefix_count: int) -> None:
    if prefix_count == 0:
        raise ProjectError(
            "COMPARISON_UNDEFINED",
            "Agreement at zero retained levels is not defined.",
            status=409,
        )
    if isinstance(prefix_count, bool) or not isinstance(prefix_count, int) or not 1 <= prefix_count <= level_count:
        raise ProjectError("INVALID_TEXT", "Choose a prefix from 1 through the number of levels.")


def profiles_match(left: dict, right: dict) -> bool:
    return (
        left.get("tokenizer_fingerprint") == right.get("tokenizer_fingerprint")
        and left.get("model_profile") == right.get("model_profile")
        and left.get("preprocessing_policy") == right.get("preprocessing_policy")
        and list(left.get("level_lengths") or []) == list(right.get("level_lengths") or [])
        and list(left.get("codebook_sizes") or []) == list(right.get("codebook_sizes") or [])
    )


def require_compatible(left: dict, right: dict) -> None:
    if profiles_match(left, right):
        return
    raise ProjectError(
        "PROFILE_MISMATCH",
        "Those hierarchies were not made with the same tokenizer, checkpoint, preprocessing, and level layout.",
        status=409,
    )


def prefix_width(level_lengths: list[int], prefix_count: int) -> int:
    require_prefix(len(level_lengths), prefix_count)
    return sum(level_lengths[:prefix_count])


def prefix_agreement(left_codes: list[int], right_codes: list[int], level_lengths: list[int], prefix_count: int) -> dict:
    width = prefix_width(level_lengths, prefix_count)
    if len(left_codes) < width or len(right_codes) < width:
        raise ProjectError("INVALID_REPRESENTATION", "A hierarchy is shorter than the selected prefix.")
    matches = sum(1 for index in range(width) if left_codes[index] == right_codes[index])
    return {
        "agreement": Fraction(matches, width),
        "shared_prefix": matches == width,
        "slot_count": width,
    }


def band_for(token_count: int | None) -> dict | None:
    if isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 1:
        return None
    index = (token_count - 1) // BAND_WIDTH
    start = index * BAND_WIDTH + 1
    return {
        "policy": BAND_POLICY,
        "width": BAND_WIDTH,
        "index": index,
        "start": start,
        "end": start + BAND_WIDTH - 1,
    }


def diagnose_baseline(population: list[list[int]], level_lengths: list[int], prefix_count: int) -> dict:
    """Estimate common-code agreement inside one recorded stratum.

    ``population`` is already deduplicated. N below 2 leaves the baseline
    unavailable. N below ``SPARSE_BELOW`` is still computed and labeled sparse.
    The adjustment is undefined when every slot is unanimous.
    """
    width = prefix_width(level_lengths, prefix_count)
    count = len(population)
    if count < 2:
        return {"state": "unavailable", "value": None, "count": count}
    for codes in population:
        if len(codes) < width:
            raise ProjectError("INVALID_REPRESENTATION", "A baseline hierarchy is shorter than the selected prefix.")
    total = Fraction(0)
    denominator = count * (count - 1)
    for slot in range(width):
        counts = Counter(codes[slot] for codes in population)
        numerator = sum(amount * (amount - 1) for amount in counts.values())
        total += Fraction(numerator, denominator)
    value = total / width
    if value == 1:
        return {"state": "degenerate", "value": value, "count": count}
    state = "sparse" if count < SPARSE_BELOW else "available"
    return {"state": state, "value": value, "count": count}


def adjust(agreement: Fraction, baseline: Fraction | None, state: str) -> Fraction | None:
    if state in {"unavailable", "degenerate"} or baseline is None or baseline == 1:
        return None
    return (agreement - baseline) / (1 - baseline)


def as_float(value: Fraction | None) -> float | None:
    if value is None:
        return None
    return float(value)
