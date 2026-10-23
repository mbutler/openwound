"""A short random model with the released TinyStories architectural flags.

Twelve levels exercise the trace and prefix rules without the checkpoint.
The grid is 16 positions wide, not the released 128.
"""

from omegaconf import OmegaConf

from ncm_art.model_adapter.bootstrap import ensure_vendor_imports

ensure_vendor_imports()

import torch
from models.next_concept import NextConceptTransformer
from models.vqvae import VQVAE

LEVELS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16]
CODEBOOK = 16
EMBED_DIM = 32
TEXT_LENGTH = 16


def build_tiny_bundle():
    torch.manual_seed(0)
    vocab = [CODEBOOK] * len(LEVELS)
    quantizer = OmegaConf.create(
        {
            "clss": "multiscale_residual_vector_quantizer",
            "decay": 0.95,
            "epsilon": 1.0e-5,
            "commitment_cost": 0.25,
            "learned_l1_sampling": True,
            "learned_l1_cascade": True,
            "learned_l1_cascade_base": 4,
            "learned_all_sampling": False,
            "quant_resi": {
                "enabled": True,
                "ratio": 0.5,
                "share_mode": 0,
                "learnable_ratio": False,
            },
            "aux": {"fine_drop": {"prob": 0.0, "min_keep": 1}},
            "levels": {"use_manual_levels": True, "manual_levels": LEVELS},
            "learned_l1_cascade_norm": False,
            "learned_l1_cascade_norm_final": False,
            "ema_scale_by_world_size": False,
        }
    )
    vqvae = VQVAE(
        in_vocab_size=32,
        context_length=TEXT_LENGTH,
        embed_dim=EMBED_DIM,
        vqvae_vocab_size=vocab,
        n_layers=4,
        vector_quantizer_config=quantizer,
        compression_factor=1,
        dropout=0.0,
        pre_quant_groupnorm=8,
        use_qk_norm=True,
        pre_quant_dropout=0.0,
    )
    generator_config = OmegaConf.create(
        {
            "n_layer": 1,
            "n_head": 4,
            "bias": True,
            "dropout": 0.0,
            "n_embd": 64,
            "context_length": TEXT_LENGTH + 1,
            "prefix_len": 1,
            "raw_token_prefix": True,
            "prefix_pad_token_id": 1,
            "vocab_size": vocab[1:],
            "predict_level0": False,
            "attn_pattern": "block_diagonal",
            "use_positional_encoding": True,
            "use_level_encoding": True,
            "use_rope": True,
            "rope_base": 100000,
            "use_qk_norm": True,
            "ctx_encoder": {"enabled": False, "n_layer": 1, "vocab_size": 32},
            "use_flex_attention": False,
            "query_level0": False,
            "tie_heads_to_codebook": True,
            "tie_heads_learn_scale": True,
        }
    )
    net = NextConceptTransformer(vqvae_local=vqvae, config=generator_config)
    vqvae.eval()
    net.eval()
    for parameter in list(vqvae.parameters()) + list(net.parameters()):
        parameter.requires_grad_(False)
    return vqvae, net
