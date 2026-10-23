"""Inference adapter for the pinned TinyStories Next-Concept model.

The public operations are tokenize, encode, reconstruct, branch, and graft.
Tokenize against the released BPE assets arrives with the checkpoint loader.
This package does not import the upstream evaluation script.
"""

from ncm_art.model_adapter.display import (
    DISPLAY_POLICY_CUT_AT_EOS,
    DISPLAY_POLICY_KEEP_AFTER_EOS,
    displayed_text,
    select_display_ids,
)
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.sampling import Sampling, validate_sampling
from ncm_art.model_adapter.seeds import candidate_seed
from ncm_art.model_adapter.tinystories import (
    BranchResult,
    GraftResult,
    apply_graft,
    branch_tinystories,
    encode_source,
    reconstruct_trace,
)

__all__ = [
    "DISPLAY_POLICY_CUT_AT_EOS",
    "DISPLAY_POLICY_KEEP_AFTER_EOS",
    "AdapterError",
    "BranchResult",
    "GraftResult",
    "Sampling",
    "apply_graft",
    "branch_tinystories",
    "candidate_seed",
    "displayed_text",
    "encode_source",
    "reconstruct_trace",
    "select_display_ids",
    "validate_sampling",
]
