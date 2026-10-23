"""Sampling settings for one TinyStories candidate.

Invalid values are rejected. They are not clamped to a nearby legal setting.
"""

from dataclasses import dataclass

from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.profile import CODEBOOK_SIZE


@dataclass(frozen=True)
class Sampling:
    temperature: float
    top_k: int
    top_p: float


def validate_sampling(
    temperature: float,
    top_k: int,
    top_p: float,
    codebook_size: int = CODEBOOK_SIZE,
) -> Sampling:
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise AdapterError("INVALID_SAMPLING", "Temperature must be a number.")
    if isinstance(top_k, bool) or not isinstance(top_k, int):
        raise AdapterError("INVALID_SAMPLING", "top_k must be an integer.")
    if isinstance(top_p, bool) or not isinstance(top_p, (int, float)):
        raise AdapterError("INVALID_SAMPLING", "top_p must be a number.")

    temperature = float(temperature)
    top_p = float(top_p)
    if temperature != temperature or temperature < 0:
        raise AdapterError(
            "INVALID_SAMPLING",
            "Temperature must be finite and greater than or equal to zero.",
            {"temperature": temperature},
        )
    if top_k < 0 or top_k > codebook_size:
        raise AdapterError(
            "INVALID_SAMPLING",
            f"top_k must be an integer from 0 through {codebook_size}.",
            {"top_k": top_k, "codebook_size": codebook_size},
        )
    if top_p != top_p or top_p <= 0 or top_p > 1:
        raise AdapterError(
            "INVALID_SAMPLING",
            "top_p must be finite, greater than zero, and no larger than one.",
            {"top_p": top_p},
        )
    return Sampling(temperature=temperature, top_k=top_k, top_p=top_p)
