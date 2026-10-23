"""Count BPE tokens without loading the generator.

The two vocabulary files are verified once per process, then reused for the
live token count in the editor.
"""

from ncm_art.model_adapter.artifacts import bundle_dir, verify_file
from ncm_art.model_adapter.bootstrap import ensure_vendor_imports
from ncm_art.model_adapter.profile import TEXT_LENGTH, load_profile

POLICY = "tinystories-bpe-no-eos-v1"
_tokenizer = None


def get_bpe():
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    ensure_vendor_imports()
    from omegaconf import OmegaConf
    from tokenization.bpe_tokenizer import BPETokenizer

    from ncm_art.model_adapter.profile import repo_root

    profile = load_profile()
    directory = bundle_dir()
    for name in ("bpe_vocab_8192.pickle", "bpe_merges_8192.pickle"):
        meta = profile["artifacts"][f"tinystories/{name}"]
        verify_file(directory / name, meta["bytes"], meta["sha256"])
    config = OmegaConf.load(repo_root() / "vendor" / "ncm" / "config" / "eval" / "tinystories.yaml")
    config.tokenizer.pre_tokenizer.vocab_file_path = str(directory / "bpe_vocab_8192.pickle")
    config.tokenizer.pre_tokenizer.merges_file_path = str(directory / "bpe_merges_8192.pickle")
    _tokenizer = BPETokenizer.from_config(config.tokenizer.pre_tokenizer)
    return _tokenizer


def preview_tokens(text: str) -> dict:
    token_ids = list(get_bpe().encode(text))
    return {
        "token_count": len(token_ids),
        "text_length": TEXT_LENGTH,
        "too_long": len(token_ids) > TEXT_LENGTH,
        "policy": POLICY,
    }
