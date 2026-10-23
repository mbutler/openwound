"""Numerical fixture for the TinyStories adapter.

These checks use a random short hierarchy. They do not load the released checkpoint.
"""

from pathlib import Path

import pytest
import torch

from ncm_art.model_adapter.bootstrap import ensure_vendor_imports, vendor_ncm_root
from ncm_art.model_adapter.display import (
    DISPLAY_POLICY_CUT_AT_EOS,
    DISPLAY_POLICY_KEEP_AFTER_EOS,
    select_display_ids,
)
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.profile import FLAT_CODE_COUNT, LEVELS, OFFSETS, load_profile
from ncm_art.model_adapter.sampling import validate_sampling
from ncm_art.model_adapter.seeds import candidate_seed
from ncm_art.model_adapter.tinystories import (
    apply_graft,
    branch_tinystories,
    encode_source,
    reconstruct_trace,
)
from tests.adapter.tiny_bundle import CODEBOOK, LEVELS as TINY_LEVELS, build_tiny_bundle


class _Tokens:
    pad_token_id = 0
    eos_token_id = 1

    def encode(self, text: str) -> list[int]:
        if text == "":
            return []
        if text == "too long":
            return [2] * 17
        return [2, 3, 4]


@pytest.fixture(scope="module")
def bundle():
    return build_tiny_bundle()


def _hierarchy(fill: int = 1) -> torch.Tensor:
    parts = []
    for length in TINY_LEVELS:
        column = torch.arange(length, dtype=torch.long) % CODEBOOK
        parts.append(((column + fill) % CODEBOOK).view(1, length))
    codes = torch.cat(parts, dim=1)
    codes[0, 0] = 0
    return codes


def _one_hot_unigram(index: int) -> torch.Tensor:
    weights = torch.zeros(CODEBOOK)
    weights[index] = 1
    return weights


def test_profile_tables_match_the_released_schedule():
    assert sum(LEVELS) == FLAT_CODE_COUNT == 641
    assert OFFSETS[-1] == 641
    assert [sum(LEVELS[:index]) for index in range(len(LEVELS) + 1)] == OFFSETS
    profile = load_profile()
    assert profile["id"] == "tinystories-v1"
    assert profile["upstream_revision"] == "c70274273f489abc73832b2b98584a8483b6b203"


def test_vendor_modules_come_from_the_pin():
    root = ensure_vendor_imports()
    assert root == vendor_ncm_root()
    import models.vqvae as vqvae_module

    assert Path(vqvae_module.__file__).resolve().is_relative_to(root.resolve())


def test_sampling_rejects_illegal_values_without_clamping():
    released = validate_sampling(1, 0, 1)
    assert (released.temperature, released.top_k, released.top_p) == (1.0, 0, 1.0)
    assert validate_sampling(0, 4096, 1.0).top_k == 4096
    for arguments in ((-0.1, 0, 1), (float("nan"), 0, 1), (1, -1, 1), (1, 4097, 1), (1, 0, 0), (1, 0, 1.1)):
        with pytest.raises(AdapterError) as caught:
            validate_sampling(*arguments)
        assert caught.value.code == "INVALID_SAMPLING"


def test_candidate_seeds_are_stable_unsigned_32_bit_values():
    assert candidate_seed(42, 0) == 42
    first = candidate_seed(42, 1)
    second = candidate_seed(42, 2)
    assert first != second
    assert 0 <= first <= 0xFFFFFFFF
    assert candidate_seed(42, 1) == first
    with pytest.raises(AdapterError):
        candidate_seed(-1, 0)


def test_display_policy_cuts_at_eos_only_when_asked():
    raw = [5, 6, 1, 7, 0, 8]
    assert select_display_ids(raw, eos_id=1, pad_id=0) == [5, 6]
    assert select_display_ids(raw, 1, 0, DISPLAY_POLICY_KEEP_AFTER_EOS) == [5, 6, 7, 8]
    assert select_display_ids(raw, 1, 0, DISPLAY_POLICY_CUT_AT_EOS) == [5, 6]


def test_encode_reports_empty_and_overlong_passages(bundle):
    vqvae, _net = bundle
    with pytest.raises(AdapterError) as empty:
        encode_source("", _Tokens(), vqvae)
    assert empty.value.code == "INPUT_EMPTY"
    with pytest.raises(AdapterError) as overlong:
        encode_source("too long", _Tokens(), vqvae)
    assert overlong.value.code == "INPUT_TOO_LONG"
    assert overlong.value.details["token_count"] == 17

    tokens, codes, count = encode_source("ok", _Tokens(), vqvae)
    assert count == 3
    assert tokens.shape == (1, 16)
    assert int(tokens[0, 3]) == _Tokens.pad_token_id
    assert codes.shape == (1, sum(TINY_LEVELS))


def test_reconstruction_snapshots_do_not_alias_and_match_direct_decode(bundle):
    vqvae, _net = bundle
    codes = _hierarchy()
    trace = reconstruct_trace(vqvae, codes)
    assert [frame["completed_levels"] for frame in trace] == list(range(1, 13))
    assert trace[0]["latent"].shape == (1, 16, 32)
    storages = [frame["latent"].untyped_storage().data_ptr() for frame in trace]
    assert len(set(storages)) == len(storages)

    direct = vqvae.vq.idx_to_z_q(codes)
    torch.testing.assert_close(trace[-1]["latent"], direct, atol=0, rtol=0)
    direct_tokens = vqvae.decode(codes).argmax(dim=-1).cpu()
    assert torch.equal(trace[-1]["raw_token_ids"], direct_tokens)


def test_prefix_retention_and_prediction_counts(bundle):
    vqvae, net = bundle
    source = _hierarchy(fill=2)
    unigram = _one_hot_unigram(7)
    sampling = validate_sampling(1, 0, 1, codebook_size=CODEBOOK)
    level_count = len(TINY_LEVELS)

    for retained in range(level_count + 1):
        torch.manual_seed(1234)
        result = branch_tinystories(
            None if retained == level_count else net,
            vqvae,
            None if retained == 0 else source,
            retained,
            eos_id=1,
            level0_unigram=None if retained else unigram,
            sampling=sampling,
        )
        assert result.prediction_count == level_count - max(retained, 1)
        if retained == 0:
            assert int(result.codes[0, 0]) == 7
            assert int(source[0, 0]) != 7
        else:
            offset = 0
            for level_index, length in enumerate(TINY_LEVELS[:retained]):
                assert torch.equal(
                    result.codes[:, offset : offset + length],
                    source[:, offset : offset + length],
                ), level_index
                offset += length
        if retained == level_count:
            assert torch.equal(result.codes, source)


def test_preview_decoding_does_not_change_sampled_codes(bundle):
    vqvae, net = bundle
    source = _hierarchy(fill=4)
    sampling = validate_sampling(1, 0, 1, codebook_size=CODEBOOK)

    def preview(_level, _code, state):
        vqvae.decoder(state).argmax(dim=-1)

    torch.manual_seed(99)
    plain = branch_tinystories(net, vqvae, source, 3, 1, None, sampling)
    torch.manual_seed(99)
    previewed = branch_tinystories(net, vqvae, source, 3, 1, None, sampling, on_level=preview)
    assert torch.equal(plain.codes, previewed.codes)
    assert plain.prediction_count == 9


def test_graft_changes_only_the_declared_positions(bundle):
    _vqvae, _net = bundle
    base = _hierarchy(fill=1)
    donor = _hierarchy(fill=5)
    base_before = base.clone()
    donor_before = donor.clone()
    grafted = apply_graft(base, donor, [(1, 0), (2, 1)], retained_level_count=3, levels=TINY_LEVELS, codebook_sizes=[CODEBOOK] * 12)
    assert torch.equal(base, base_before)
    assert torch.equal(donor, donor_before)
    changed = (grafted.codes != base).nonzero(as_tuple=False).tolist()
    assert changed == [[0, 1], [0, 4]]
    assert grafted.changed

    same = apply_graft(base, base, [(1, 0)], 2, TINY_LEVELS, [CODEBOOK] * 12)
    assert not same.changed
    assert torch.equal(same.codes, base)

    with pytest.raises(AdapterError) as too_shallow:
        apply_graft(base, donor, [(2, 0)], retained_level_count=2, levels=TINY_LEVELS, codebook_sizes=[CODEBOOK] * 12)
    assert too_shallow.value.code == "INVALID_SAMPLING"
