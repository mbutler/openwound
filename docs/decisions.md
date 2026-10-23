# Implementation decisions

Departures from `ncm_art_studio_openwound_v4_technical_spec.md`, upstream patches, dependency choices, and numerical tolerances. The specification's user-facing behavior, mathematical contracts, and provenance rules stay in force.

## 2026-10-23 Repository layout

The specification proposes an `ncm-art-studio/` project root and a file named `SPEC.md`. This repository is already the v4 working tree, and `legacy-versions/` stays beside the new code, so the application lives at the repository root. The specification keeps the filename it was given.

## 2026-10-23 Upstream pin

`vendor/ncm` is the pinned research source described in `vendor/UPSTREAM.md`. The adapter will call those modules. It will not import `scripts/eval_shard.py`, and it will not copy the public tokenizer wrapper's silent chunking of over-length text.

`idx_to_zhats` appends references to an accumulator that is modified in place. Reconstruction traces will store independent snapshots from `get_next_autoregressive_input`, as in the specification's reference algorithm, rather than patching that upstream function.

## 2026-10-23 Python

The specification asks for Python 3.12. This machine's system Python is 3.9.6. `conda create` stopped because the Anaconda channel terms of service have not been accepted, and those terms were not accepted on the artist's behalf. uv 0.13.5, installed under `~/.local/bin`, provides CPython 3.12.15. The environment lives in `.venv` and is not committed. `uv.lock` records the installed set.

Inference imports from the pinned quantizer require NumPy, so it is a direct dependency. Evaluation packages from the upstream requirements file, including `transformers`, `rouge_score`, and `sacrebleu`, are not installed.

The specification's preparation environment was PyTorch 2.14.1+cpu. This machine installed the macOS wheel `torch==2.14.1` and ran the fixture on CPU, FP32, eager mode. MPS was not used. On the random twelve-level fixture, the incremental full-grid latent matched `idx_to_z_q` exactly, so no floating-point tolerance was introduced.

The package version is `4.0.0.dev0`. In the specification, "version 1" means the first complete studio release. That release is still openwound v4.

Adapter error codes `INPUT_EMPTY`, `INVALID_SAMPLING`, and `PROFILE_MISMATCH` name failures the HTTP list had not yet spelled out. They use the same envelope idea: a code, a readable message, and details.
