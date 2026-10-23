"""Local commands for model installation and the inference smoke check."""

import argparse
import json
import platform
import sys
from pathlib import Path

import torch

from ncm_art import __version__
from ncm_art.model_adapter.artifacts import install_tinystories, verify_bundle
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.load import load_tinystories
from ncm_art.model_adapter.sampling import validate_sampling
from ncm_art.model_adapter.seeds import candidate_seed
from ncm_art.model_adapter.tinystories import branch_tinystories, decode_displayed, encode_source, reconstruct_trace


def _models_install(args) -> int:
    if args.profile != "tinystories-v1":
        raise AdapterError("MODEL_NOT_READY", "The only installable profile is tinystories-v1.")
    directory = install_tinystories()
    hashes = verify_bundle(directory)
    print(f"Verified {len(hashes)} TinyStories files in {directory}")
    return 0


def _doctor(_args) -> int:
    print(f"ncm-art {__version__}")
    print(f"Python {platform.python_version()} on {platform.platform()}")
    print(f"PyTorch {torch.__version__}")
    try:
        hashes = verify_bundle()
    except AdapterError as error:
        print(f"Model files: {error.message}")
        return 1
    print(f"Model files: {len(hashes)} verified")
    return 0


def _shown(bundle, raw_ids) -> str:
    return decode_displayed(
        raw_ids,
        bundle.pre_tokenizer.eos_token_id,
        bundle.pre_tokenizer.pad_token_id,
        bundle.pre_tokenizer,
    )


def _branch(bundle, source, retained, seed, sampling):
    torch.manual_seed(seed)
    return branch_tinystories(
        None if retained == 12 else bundle.generator,
        bundle.vqvae,
        None if retained == 0 else source,
        retained,
        bundle.pre_tokenizer.eos_token_id,
        None if retained else bundle.level0_unigram,
        sampling,
    )


def _smoke(args) -> int:
    bundle = load_tinystories(device="cpu")
    text = "Anna borrowed a red kite from Ben."
    _tokens, codes, count = encode_source(text, bundle.pre_tokenizer, bundle.vqvae)
    trace = reconstruct_trace(bundle.vqvae, codes)
    sampling = validate_sampling(1, 0, 1)
    base_seed = 42
    variations = []
    for index in (0, 1):
        seed = candidate_seed(base_seed, index)
        result = _branch(bundle, codes, 3, seed, sampling)
        variations.append(
            {
                "candidate_index": index,
                "seed": seed,
                "retained_level_count": 3,
                "prediction_count": result.prediction_count,
                "displayed_text": _shown(bundle, bundle.vqvae.decode(result.codes).argmax(dim=-1)),
                "raw_token_ids": bundle.vqvae.decode(result.codes).argmax(dim=-1)[0].tolist(),
                "codes": result.codes[0].tolist(),
            }
        )
    fresh = _branch(bundle, codes, 0, base_seed, sampling)
    held = _branch(bundle, codes, 12, base_seed, sampling)
    manifest = {
        "kind": "checkpoint_smoke",
        "note": "Genuine TinyStories outputs from the CPU smoke check. Not an authored fixture and not a curated artwork.",
        "execution_profile": "cpu-fp32-eager-v1",
        "model_profile": "tinystories-v1",
        "adapter_version": __version__,
        "torch": torch.__version__,
        "python": platform.python_version(),
        "file_hashes": bundle.file_hashes,
        "source_text": text,
        "source_token_count": count,
        "sampling": {"temperature": 1.0, "top_k": 0, "top_p": 1.0},
        "base_seed": base_seed,
        "reconstruction_frames": len(trace),
        "final_reconstruction": _shown(bundle, trace[-1]["raw_token_ids"]),
        "final_reconstruction_tokens": trace[-1]["raw_token_ids"][0].tolist(),
        "source_codes": codes[0].tolist(),
        "variations_retained_3": variations,
        "retained_0": {
            "seed": base_seed,
            "prediction_count": fresh.prediction_count,
            "displayed_text": _shown(bundle, bundle.vqvae.decode(fresh.codes).argmax(dim=-1)),
        },
        "retained_12": {
            "prediction_count": held.prediction_count,
            "matches_source_codes": bool(torch.equal(held.codes, codes)),
        },
    }
    print(f"source tokens: {count}")
    print(f"reconstruction frames: {len(trace)}")
    print("final reconstruction:")
    print(manifest["final_reconstruction"])
    for variation in variations:
        print(f"retained 3 seed {variation['seed']}:")
        print(variation["displayed_text"])
    print("retained 0:")
    print(manifest["retained_0"]["displayed_text"])
    print(
        "predictions:"
        f" m3={variations[0]['prediction_count']},"
        f" m0={fresh.prediction_count},"
        f" m12={held.prediction_count},"
        f" m12_matches={manifest['retained_12']['matches_source_codes']}"
    )
    if args.manifest:
        destination = Path(args.manifest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"manifest: {destination}")
    return 0


def _serve(args) -> int:
    import multiprocessing
    import os
    import webbrowser
    from pathlib import Path

    import uvicorn

    from ncm_art.jobs.worker import worker_main
    from ncm_art.model_adapter.profile import repo_root
    from ncm_art.storage.library import Library

    library_root = Path(os.environ.get("NCM_ART_LIBRARY", repo_root() / ".projects"))
    library = Library(library_root)
    stop = library.root / "worker.stop"
    stop.unlink(missing_ok=True)
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=worker_main, args=(str(library.root),), name="ncm-art-worker")
    process.start()
    if args.open:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    try:
        uvicorn.run("ncm_art.api.app:app", host="127.0.0.1", port=args.port)
    finally:
        stop.write_text("stop", encoding="utf-8")
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ncm_art")
    commands = parser.add_subparsers(dest="command", required=True)

    models = commands.add_parser("models")
    model_commands = models.add_subparsers(dest="models_command", required=True)
    install = model_commands.add_parser("install")
    install.add_argument("profile", nargs="?", default="tinystories-v1")
    install.set_defaults(func=_models_install)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--profile", default="cpu-fp32-eager-v1")
    doctor.set_defaults(func=_doctor)

    smoke = commands.add_parser("smoke")
    smoke.add_argument("--manifest", default=None)
    smoke.set_defaults(func=_smoke)

    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true")
    serve.set_defaults(func=_serve)

    args = parser.parse_args(argv)
    if args.command == "models" and args.models_command is None:
        models.print_help()
        return 2
    try:
        return args.func(args)
    except AdapterError as error:
        print(f"{error.code}: {error.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
