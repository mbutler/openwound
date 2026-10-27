"""The live engine: encode, trace, and vary without a job.

One bundle is loaded lazily in the API process and every model call runs
under one lock, because the pinned sampler uses PyTorch's global RNG. Results
are returned, not stored. ``api/live.py`` commits a result only on "keep".
"""

import random
import threading
import time

import torch

from ncm_art.model_adapter.display import DISPLAY_POLICY_CUT_AT_EOS
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.sampling import Sampling, validate_sampling
from ncm_art.model_adapter.tinystories import (
    branch_tinystories,
    decode_displayed,
    encode_source,
    reconstruct_trace,
    validate_hierarchy,
)

MODEL_PROFILE = "tinystories-v1"
EXECUTION_PROFILE = "cpu-fp32-eager-v1"
SEED_MAX = 0xFFFFFFFF


def _default_loader():
    from ncm_art.model_adapter.load import load_tinystories

    return load_tinystories()


class LiveEngine:
    def __init__(self, loader=None):
        self._loader = loader or _default_loader
        self._bundle = None
        self._error: str | None = None
        self._lock = threading.Lock()

    # Readiness -----------------------------------------------------------

    def state(self) -> dict:
        if self._bundle is not None:
            return {"profile": MODEL_PROFILE, "state": "ready", "message": None}
        if self._error is not None:
            return {"profile": MODEL_PROFILE, "state": "unavailable", "message": self._error}
        return {"profile": MODEL_PROFILE, "state": "unloaded", "message": None}

    def load(self):
        with self._lock:
            if self._bundle is not None:
                return self._bundle
            try:
                self._bundle = self._loader()
            except Exception as error:  # the message is shown in the interface
                self._error = getattr(error, "message", None) or str(error)
                raise AdapterError("MODEL_NOT_READY", self._error) from error
            self._error = None
            return self._bundle

    def _ready(self):
        if self._bundle is None:
            return self.load()
        return self._bundle

    # Layout ------------------------------------------------------------------

    def layout(self) -> dict:
        bundle = self._ready()
        return {
            "levels": [int(level) for level in bundle.vqvae.vq.levels],
            "codebook_sizes": [int(size) for size in bundle.vqvae.vq.vqvae_vocab_sizes],
            "text_length": int(bundle.vqvae.context_length),
            "model_profile": MODEL_PROFILE,
            "execution_profile": EXECUTION_PROFILE,
            "display_policy": DISPLAY_POLICY_CUT_AT_EOS,
        }

    def fingerprints(self) -> tuple[str, str]:
        hashes = getattr(self._ready(), "file_hashes", None) or {}
        return hashes.get("tokenizer.pt", ""), hashes.get("generator.pt", "")

    def _show(self, raw_ids) -> str:
        bundle = self._ready()
        return decode_displayed(
            raw_ids,
            bundle.pre_tokenizer.eos_token_id,
            bundle.pre_tokenizer.pad_token_id,
            bundle.pre_tokenizer,
        )

    # Operations ------------------------------------------------------------

    def trace(self, text: str) -> dict:
        """Encode a passage and decode the cumulative state after every pass."""
        bundle = self._ready()
        started = time.perf_counter()
        with self._lock:
            tokens, codes, count = encode_source(text, bundle.pre_tokenizer, bundle.vqvae)
            frames = reconstruct_trace(bundle.vqvae, codes)
        shown = [
            {
                "level": frame["completed_levels"],
                "text": self._show(frame["raw_token_ids"]),
                "raw_token_ids": frame["raw_token_ids"][0].tolist(),
            }
            for frame in frames
        ]
        return {
            **self.layout(),
            "text": text,
            "token_count": count,
            "padded_token_ids": tokens[0].detach().cpu().tolist(),
            "codes": codes[0].detach().cpu().tolist(),
            "frames": shown,
            "ms": int((time.perf_counter() - started) * 1000),
        }

    def vary(
        self,
        *,
        text: str | None = None,
        codes: list[int] | None = None,
        keep: int,
        seed: int | None = None,
        sampling: Sampling | None = None,
        trim: bool = False,
    ) -> dict:
        """Keep ``keep`` passes of the source and sample the rest.

        The source is either ``codes`` from an earlier trace or ``text``, which
        is encoded first. The encoding is returned so a kept result can record
        its exact input. With ``trim``, a text longer than the window is cut
        to the window at a token boundary and the cut text is returned as
        ``source_text``; the result says so in ``trimmed``.
        """
        bundle = self._ready()
        levels = [int(level) for level in bundle.vqvae.vq.levels]
        sizes = [int(size) for size in bundle.vqvae.vq.vqvae_vocab_sizes]
        if isinstance(keep, bool) or not isinstance(keep, int) or not 0 <= keep <= len(levels):
            raise AdapterError(
                "INVALID_SAMPLING",
                f"keep must be an integer from 0 through {len(levels)}.",
                {"keep": keep},
            )
        if seed is None:
            seed = random.SystemRandom().randint(0, SEED_MAX)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= SEED_MAX:
            raise AdapterError("INVALID_SAMPLING", "The seed must be an unsigned 32-bit integer.", {"seed": seed})
        sampling = sampling or validate_sampling(1.0, 0, 1.0, codebook_size=sizes[0])
        started = time.perf_counter()
        with self._lock:
            token_count = None
            padded = None
            trimmed = False
            if codes is None:
                if text is None:
                    raise AdapterError("INPUT_EMPTY", "Enter a nonempty passage.")
                if trim:
                    text, trimmed = self._trim_to_window(text)
                tokens, source, token_count = encode_source(text, bundle.pre_tokenizer, bundle.vqvae)
                padded = tokens[0].detach().cpu().tolist()
            else:
                source = torch.tensor([[int(code) for code in codes]], dtype=torch.long)
                validate_hierarchy(source, levels, sizes)
            torch.manual_seed(seed)
            branched = branch_tinystories(
                None if keep == len(levels) else bundle.generator,
                bundle.vqvae,
                None if keep == 0 else source,
                keep,
                bundle.pre_tokenizer.eos_token_id,
                None if keep else bundle.level0_unigram,
                sampling,
            )
            raw = bundle.vqvae.decode(branched.codes).argmax(dim=-1)
        source_list = source[0].tolist()
        out_list = branched.codes[0].tolist()
        return {
            "text": self._show(raw),
            "codes": out_list,
            "raw_token_ids": raw[0].tolist(),
            "changed": "".join("1" if a != b else "0" for a, b in zip(source_list, out_list)),
            "keep": keep,
            "seed": seed,
            "prediction_count": branched.prediction_count,
            "sampling": {
                "temperature": sampling.temperature,
                "top_k": sampling.top_k,
                "top_p": sampling.top_p,
            },
            "source_codes": source_list,
            "source_text": text,
            "source_token_count": token_count,
            "source_padded_token_ids": padded,
            "trimmed": trimmed,
            "ms": int((time.perf_counter() - started) * 1000),
        }

    def _trim_to_window(self, text: str) -> tuple[str, bool]:
        """Cut a text to the window at a token boundary. Returns the text used and whether it was cut."""
        bundle = self._ready()
        limit = int(bundle.vqvae.context_length)
        ids = list(bundle.pre_tokenizer.encode(text))
        if len(ids) <= limit:
            return text, False
        keep = limit
        while keep > 0:
            candidate = bundle.pre_tokenizer.decode(ids[:keep])
            if len(list(bundle.pre_tokenizer.encode(candidate))) <= limit and candidate.strip():
                return candidate, True
            keep -= 1
        raise AdapterError("INPUT_TOO_LONG", "This text could not be cut to the window.")
