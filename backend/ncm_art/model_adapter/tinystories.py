"""TinyStories encode, reconstruct, prefix-branch, and graft operations.

The accumulation and prefix control follow the specification's reference
algorithms. Upstream ``idx_to_zhats`` is not used for traces, because it stores
references to one accumulator that later levels overwrite.
"""

from dataclasses import dataclass

from ncm_art.model_adapter.bootstrap import ensure_vendor_imports

ensure_vendor_imports()

import torch

from ncm_art.model_adapter.display import (
    DISPLAY_POLICY_CUT_AT_EOS,
    displayed_text,
)
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.sampling import Sampling


@dataclass(frozen=True)
class BranchResult:
    codes: torch.Tensor
    prediction_count: int


@dataclass(frozen=True)
class GraftReplacement:
    level_index: int
    position: int
    original_code: int
    replacement_code: int
    donor_position: int


@dataclass(frozen=True)
class GraftResult:
    codes: torch.Tensor
    replacements: tuple[GraftReplacement, ...]

    @property
    def changed(self) -> bool:
        return any(item.original_code != item.replacement_code for item in self.replacements)


def _module_device(module: torch.nn.Module, name: str) -> torch.device:
    if module.training:
        raise AdapterError(
            "MODEL_NOT_READY",
            f"{name} must be in evaluation mode before inference.",
        )
    devices = {tensor.device for tensor in list(module.parameters()) + list(module.buffers())}
    if len(devices) != 1:
        raise AdapterError(
            "MODEL_NOT_READY",
            f"{name} parameters and buffers must share one device.",
            {"devices": sorted(str(device) for device in devices)},
        )
    return devices.pop()


def assert_released_generator(net) -> None:
    """The initial adapter accepts only the released TinyStories generator shape."""
    reasons = []
    if net.prefix_len != 1 or not net.use_rope:
        reasons.append("prefix length 1 and RoPE")
    config = net.config
    if not bool(getattr(config, "raw_token_prefix", False)) or not bool(config.use_level_encoding):
        reasons.append("a raw-token prefix and level embeddings")
    if net.query_level0 or net.predict_level0:
        reasons.append("no level-zero query or predicted level-zero head")
    if net.use_ctx_encoder or net.use_post_upsample_conv:
        reasons.append("no context encoder and no post-upsample convolution")
    if getattr(config, "attn_pattern", None) != "block_diagonal":
        reasons.append("block-diagonal attention")
    if reasons:
        raise AdapterError(
            "PROFILE_MISMATCH",
            "This generator is not the released TinyStories configuration: "
            + "; ".join(reasons)
            + ".",
        )


def validate_hierarchy(codes: torch.Tensor, levels: list[int], codebook_sizes: list[int]) -> None:
    if not isinstance(codes, torch.Tensor) or codes.ndim != 2:
        raise AdapterError("INVALID_CODE_INDEX", "A hierarchy must be a rank-2 integer tensor.")
    if codes.dtype != torch.long:
        raise AdapterError("INVALID_CODE_INDEX", "Hierarchy codes must use torch.long.")
    expected = sum(levels)
    if codes.shape[1] != expected:
        raise AdapterError(
            "INVALID_CODE_INDEX",
            f"Expected {expected} codes and found {codes.shape[1]}.",
            {"expected": expected, "actual": int(codes.shape[1])},
        )
    if len(levels) != len(codebook_sizes):
        raise AdapterError("INCOMPATIBLE_ENCODING", "Level lengths and codebook sizes disagree.")
    parts = torch.split(codes, levels, dim=1)
    for level_index, part in enumerate(parts):
        if part.numel() == 0:
            continue
        lowest = int(part.min())
        highest = int(part.max())
        limit = int(codebook_sizes[level_index])
        if lowest < 0 or highest >= limit:
            raise AdapterError(
                "INVALID_CODE_INDEX",
                f"Level {level_index} has a code outside 0..{limit - 1}.",
                {"level_index": level_index, "min": lowest, "max": highest, "codebook_size": limit},
            )


def prepare_token_ids(token_ids: list[int], pad_id: int, text_length: int) -> list[int]:
    if not token_ids:
        raise AdapterError("INPUT_EMPTY", "Enter a nonempty passage.")
    if len(token_ids) > text_length:
        raise AdapterError(
            "INPUT_TOO_LONG",
            f"Select a passage of at most {text_length} BPE tokens. This one is {len(token_ids)}.",
            {"token_count": len(token_ids), "text_length": text_length},
        )
    return list(token_ids) + [pad_id] * (text_length - len(token_ids))


@torch.inference_mode()
def encode_source(text: str, pre_tokenizer, vqvae) -> tuple[torch.Tensor, torch.Tensor, int]:
    """Return padded token ids, flat codes, and the unpadded token count."""
    token_ids = list(pre_tokenizer.encode(text))
    padded = prepare_token_ids(token_ids, pre_tokenizer.pad_token_id, vqvae.context_length)
    device = _module_device(vqvae, "tokenizer")
    token_tensor = torch.tensor([padded], dtype=torch.long, device=device)
    codes = vqvae.encode(token_tensor)
    if codes.shape != (1, sum(vqvae.vq.levels)):
        raise AdapterError(
            "INVALID_CODE_INDEX",
            f"Encoder returned shape {tuple(codes.shape)}.",
        )
    return token_tensor, codes, len(token_ids)


@torch.inference_mode()
def reconstruct_trace(vqvae, flat_codes: torch.Tensor) -> list[dict]:
    """Decode the cumulative full-grid state after every level."""
    _module_device(vqvae, "tokenizer")
    levels = [int(level) for level in vqvae.vq.levels]
    codebook_sizes = [int(size) for size in vqvae.vq.vqvae_vocab_sizes]
    validate_hierarchy(flat_codes, levels, codebook_sizes)
    flat_codes = flat_codes.to(device=next(vqvae.parameters()).device)
    parts = torch.split(flat_codes, levels, dim=1)
    state = torch.zeros(
        flat_codes.shape[0],
        levels[-1],
        vqvae.embed_dim,
        device=flat_codes.device,
        dtype=torch.float32,
    )
    trace = []
    for level_index, codes in enumerate(parts):
        embedding = vqvae.vq.embeddings[level_index](codes)
        state, _next_generator_input = vqvae.vq.get_next_autoregressive_input(
            level_index, state, embedding
        )
        snapshot = state.detach().clone()
        logits = vqvae.decoder(snapshot)
        raw_ids = logits.argmax(dim=-1)
        trace.append(
            {
                "completed_levels": level_index + 1,
                "latent": snapshot,
                "raw_token_ids": raw_ids.detach().cpu().clone(),
            }
        )
    return trace


def _validate_unigram(level0_unigram: torch.Tensor, codebook_size: int) -> torch.Tensor:
    if not isinstance(level0_unigram, torch.Tensor):
        raise AdapterError("MODEL_NOT_READY", "The level-zero unigram must be a tensor.")
    weights = level0_unigram.detach()
    if weights.ndim == 2 and weights.shape[0] == 1:
        weights = weights.view(-1)
    if weights.ndim != 1 or weights.shape[0] != codebook_size:
        raise AdapterError(
            "MODEL_NOT_READY",
            f"The level-zero unigram must contain {codebook_size} weights.",
            {"shape": list(weights.shape), "codebook_size": codebook_size},
        )
    weights = weights.float().cpu()
    if not torch.isfinite(weights).all() or bool((weights < 0).any()) or float(weights.sum()) <= 0:
        raise AdapterError(
            "MODEL_NOT_READY",
            "The level-zero unigram must be finite, nonnegative, and have a positive total.",
        )
    return weights


@torch.inference_mode()
def branch_tinystories(
    net,
    vqvae,
    source_codes: torch.Tensor | None,
    retained_level_count: int,
    eos_id: int,
    level0_unigram: torch.Tensor | None,
    sampling: Sampling,
    on_level=None,
) -> BranchResult:
    """Retain ``retained_level_count`` complete levels and sample the rest.

    A count of zero draws level zero from the empirical unigram and inherits
    no source codes. A count equal to the number of levels returns the source
    hierarchy and does not call the generator.
    """
    if isinstance(retained_level_count, bool) or not isinstance(retained_level_count, int):
        raise AdapterError("INVALID_SAMPLING", "retained_level_count must be an integer.")
    levels = [int(level) for level in vqvae.vq.levels]
    level_count = len(levels)
    if retained_level_count < 0 or retained_level_count > level_count:
        raise AdapterError(
            "INVALID_SAMPLING",
            f"retained_level_count must be from 0 through {level_count}.",
            {"retained_level_count": retained_level_count},
        )
    codebook_sizes = [int(size) for size in vqvae.vq.vqvae_vocab_sizes]
    device = _module_device(vqvae, "tokenizer")

    if retained_level_count == 0:
        if level0_unigram is None:
            raise AdapterError("MODEL_NOT_READY", "A level-zero unigram is required to retain nothing.")
        weights = _validate_unigram(level0_unigram, codebook_sizes[0])
    else:
        if source_codes is None:
            raise AdapterError("INCOMPATIBLE_ENCODING", "Retaining levels requires a source hierarchy.")
        validate_hierarchy(source_codes, levels, codebook_sizes)
        if source_codes.shape[0] != 1:
            raise AdapterError(
                "INVALID_CODE_INDEX",
                "The first execution profile branches one hierarchy at a time.",
                {"batch": int(source_codes.shape[0])},
            )

    if retained_level_count == level_count:
        return BranchResult(codes=source_codes.detach().clone(), prediction_count=0)

    assert_released_generator(net)
    generator_device = _module_device(net, "generator")
    if generator_device != device:
        raise AdapterError(
            "MODEL_NOT_READY",
            "The tokenizer and generator must be on the same device.",
            {"tokenizer": str(device), "generator": str(generator_device)},
        )
    if not isinstance(eos_id, int) or isinstance(eos_id, bool):
        raise AdapterError("MODEL_NOT_READY", "EOS must be an integer token id.")
    if eos_id < 0 or eos_id >= int(vqvae.in_vocab_size):
        raise AdapterError(
            "MODEL_NOT_READY",
            "EOS is outside the tokenizer vocabulary.",
            {"eos_id": eos_id, "vocab_size": int(vqvae.in_vocab_size)},
        )

    fixed = None
    if retained_level_count > 0:
        fixed = torch.split(source_codes.to(device), levels, dim=1)
        code = fixed[0].clone()
    else:
        drawn = torch.multinomial(weights, levels[0], replacement=True)
        code = drawn.reshape(1, levels[0]).to(device)

    prefix_tokens = torch.full((1, 1), eos_id, dtype=torch.long, device=device)
    prefix_emb = net.transformer.wte(vqvae.encoder.wte(prefix_tokens))
    level_pos_embed = net.transformer.wle(net.lvl_1L)
    state = torch.zeros(1, levels[-1], vqvae.embed_dim, dtype=torch.float32, device=device)
    result = []
    target_offset = 0
    prediction_count = 0
    net._cfg = None
    try:
        for level_index in range(level_count):
            if level_index > 0:
                if level_index < retained_level_count:
                    code = fixed[level_index].clone()
                else:
                    hidden = net.transformer.wte(next_input)
                    hidden = hidden + level_pos_embed[
                        :, target_offset : target_offset + levels[level_index], :
                    ]
                    logits = net._decode_level_logits(
                        hidden,
                        prefix_emb,
                        level_idx=level_index - 1,
                        pad_bias=None,
                        hidx=level_index - 1,
                    )
                    prediction_count += 1
                    code = net._sample_level(
                        logits, sampling.temperature, sampling.top_k, sampling.top_p
                    )
                target_offset += levels[level_index]

            result.append(code.clone())
            embedding = vqvae.vq.embeddings[level_index](code)
            state, next_input = vqvae.vq.get_next_autoregressive_input(
                level_index, state, embedding
            )
            if on_level is not None:
                on_level(
                    level_index + 1,
                    code.detach().clone(),
                    state.detach().clone(),
                )
    finally:
        net._cfg = None

    return BranchResult(codes=torch.cat(result, dim=1), prediction_count=prediction_count)


@torch.inference_mode()
def apply_graft(
    base_codes: torch.Tensor,
    donor_codes: torch.Tensor,
    positions: list[tuple[int, int]],
    retained_level_count: int,
    levels: list[int],
    codebook_sizes: list[int],
) -> GraftResult:
    """Replace selected base codes with the donor code at the same level and position.

    ``retained_level_count`` must be greater than every modified zero-based level.
    The base and donor tensors are not modified.
    """
    validate_hierarchy(base_codes, levels, codebook_sizes)
    validate_hierarchy(donor_codes, levels, codebook_sizes)
    if base_codes.shape[0] != 1 or donor_codes.shape[0] != 1:
        raise AdapterError("INVALID_CODE_INDEX", "A graft reads one base hierarchy and one donor.")
    if isinstance(retained_level_count, bool) or not isinstance(retained_level_count, int):
        raise AdapterError("INVALID_SAMPLING", "retained_level_count must be an integer.")
    if not positions:
        raise AdapterError("INVALID_CODE_INDEX", "A graft needs at least one code position.")

    grafted = base_codes.detach().clone()
    records = []
    for level_index, position in positions:
        if isinstance(level_index, bool) or not isinstance(level_index, int):
            raise AdapterError("INVALID_CODE_INDEX", "A graft level must be an integer.")
        if isinstance(position, bool) or not isinstance(position, int):
            raise AdapterError("INVALID_CODE_INDEX", "A graft position must be an integer.")
        if level_index < 0 or level_index >= len(levels):
            raise AdapterError(
                "INVALID_CODE_INDEX",
                f"Level {level_index} is outside this hierarchy.",
            )
        if retained_level_count <= level_index:
            raise AdapterError(
                "INVALID_SAMPLING",
                "retained_level_count must be greater than the highest modified level.",
                {"retained_level_count": retained_level_count, "level_index": level_index},
            )
        width = levels[level_index]
        if position < 0 or position >= width:
            raise AdapterError(
                "INVALID_CODE_INDEX",
                f"Position {position} is outside level {level_index}, which has length {width}.",
            )
        offset = sum(levels[:level_index]) + position
        original = int(grafted[0, offset])
        replacement = int(donor_codes[0, offset])
        grafted[0, offset] = replacement
        records.append(
            GraftReplacement(
                level_index=level_index,
                position=position,
                original_code=original,
                replacement_code=replacement,
                donor_position=position,
            )
        )
    return GraftResult(codes=grafted, replacements=tuple(records))


def decode_displayed(raw_ids, eos_id: int, pad_id: int, pre_tokenizer, policy: str = DISPLAY_POLICY_CUT_AT_EOS) -> str:
    ids = raw_ids.tolist() if isinstance(raw_ids, torch.Tensor) else raw_ids
    if isinstance(ids[0], list):
        ids = ids[0]
    return displayed_text(ids, eos_id, pad_id, pre_tokenizer.decode, policy)
