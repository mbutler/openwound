"""Load the released TinyStories tokenizer, then the generator.

Tied generator heads copy codebook weights into nonpersistent buffers while
the generator is constructed. The tokenizer checkpoint is therefore loaded
and moved to the device before that construction. Calling ``net.to`` does not
move the tokenizer, because upstream stores it in an unregistered tuple.
"""

from dataclasses import dataclass
from pathlib import Path

import torch

from ncm_art.model_adapter.artifacts import bundle_dir, verify_bundle
from ncm_art.model_adapter.bootstrap import ensure_vendor_imports
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.profile import repo_root


@dataclass
class TinyStoriesBundle:
    vqvae: torch.nn.Module
    generator: torch.nn.Module
    pre_tokenizer: object
    level0_unigram: torch.Tensor
    device: torch.device
    file_hashes: dict[str, str]


def load_tinystories(directory: Path | None = None, device: str = "cpu") -> TinyStoriesBundle:
    if device != "cpu":
        raise AdapterError(
            "DEVICE_UNSUPPORTED",
            "The first execution profile is CPU. MPS and CUDA are not enabled yet.",
            {"device": device},
        )
    directory = directory or bundle_dir()
    file_hashes = verify_bundle(directory)
    ensure_vendor_imports()
    from omegaconf import OmegaConf
    from models.next_concept import NextConceptTransformer
    from models.vqvae import VQVAE
    from tokenization.bpe_tokenizer import BPETokenizer

    config = OmegaConf.load(repo_root() / "vendor" / "ncm" / "config" / "eval" / "tinystories.yaml")
    config.tokenizer.vqvae.checkpoint_path = str(directory / "tokenizer.pt")
    config.tokenizer.pre_tokenizer.vocab_file_path = str(directory / "bpe_vocab_8192.pickle")
    config.tokenizer.pre_tokenizer.merges_file_path = str(directory / "bpe_merges_8192.pickle")

    pre_tokenizer = BPETokenizer.from_config(config.tokenizer.pre_tokenizer)
    if pre_tokenizer.eos_token_id is None or pre_tokenizer.pad_token_id is None:
        raise AdapterError("MODEL_NOT_READY", "The BPE tokenizer did not define EOS and PAD.")
    if pre_tokenizer.eos_token_id == pre_tokenizer.pad_token_id:
        raise AdapterError("MODEL_NOT_READY", "EOS and PAD must be different token ids.")

    vqvae = VQVAE(**config.tokenizer.vqvae)
    tokenizer_state = torch.load(directory / "tokenizer.pt", map_location="cpu", weights_only=False)
    vqvae.load_state_dict(tokenizer_state["model"], strict=True)
    vqvae.to(device).eval()
    for parameter in vqvae.parameters():
        parameter.requires_grad_(False)

    generator = NextConceptTransformer(vqvae_local=vqvae, config=config.model)
    generator_state = torch.load(directory / "generator.pt", map_location="cpu", weights_only=False)
    generator.load_state_dict(generator_state["model"], strict=True)
    generator.to(device).eval()
    for parameter in generator.parameters():
        parameter.requires_grad_(False)

    unigram = generator_state["inference"]["level0_unigram"]
    if not isinstance(unigram, torch.Tensor):
        raise AdapterError("MODEL_NOT_READY", "generator.pt has no level-zero unigram tensor.")
    return TinyStoriesBundle(
        vqvae=vqvae,
        generator=generator,
        pre_tokenizer=pre_tokenizer,
        level0_unigram=unigram,
        device=torch.device(device),
        file_hashes=file_hashes,
    )
