"""Download and verify the pinned TinyStories files.

Only these verified files may be deserialized by the model loader. A failed
check removes the bad file and leaves files that already matched.
"""

import hashlib
from pathlib import Path

from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.profile import load_profile, repo_root

ALLOW_PATTERNS = [
    "tinystories/generator.pt",
    "tinystories/tokenizer.pt",
    "tinystories/bpe_vocab_8192.pickle",
    "tinystories/bpe_merges_8192.pickle",
    "tinystories/config.yaml",
    "tinystories/README.md",
]


def cache_root() -> Path:
    return repo_root() / ".model-cache" / "tinystories-v1"


def bundle_dir() -> Path:
    return cache_root() / "tinystories"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected_bytes: int, expected_sha256: str | None) -> str:
    if not path.is_file():
        raise AdapterError(
            "MODEL_NOT_READY",
            f"Missing model file {path.name}.",
            {"path": path.name},
        )
    actual_bytes = path.stat().st_size
    if actual_bytes != expected_bytes:
        raise AdapterError(
            "MODEL_NOT_READY",
            f"{path.name} is {actual_bytes} bytes; the pinned file is {expected_bytes}.",
            {"path": path.name, "actual_bytes": actual_bytes, "expected_bytes": expected_bytes},
        )
    actual_sha256 = sha256_file(path)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise AdapterError(
            "MODEL_NOT_READY",
            f"{path.name} does not match the pinned SHA-256.",
            {"path": path.name, "actual_sha256": actual_sha256, "expected_sha256": expected_sha256},
        )
    return actual_sha256


def verify_bundle(directory: Path | None = None) -> dict[str, str]:
    directory = directory or bundle_dir()
    profile = load_profile()
    hashes = {}
    for relative, meta in profile["artifacts"].items():
        name = Path(relative).name
        hashes[name] = verify_file(directory / name, meta["bytes"], meta["sha256"])
    return hashes


def install_tinystories() -> Path:
    """Fetch any pinned file that is missing or fails verification."""
    profile = load_profile()
    destination = cache_root()
    destination.mkdir(parents=True, exist_ok=True)
    directory = bundle_dir()
    directory.mkdir(parents=True, exist_ok=True)
    needs_download = False
    for relative, meta in profile["artifacts"].items():
        path = directory / Path(relative).name
        try:
            verify_file(path, meta["bytes"], meta["sha256"])
        except AdapterError:
            if path.is_file():
                path.unlink()
            needs_download = True
    if needs_download:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id=profile["artifact_repository"],
            revision=profile["artifact_revision"],
            allow_patterns=ALLOW_PATTERNS,
            local_dir=str(destination),
        )
    verify_bundle(directory)
    return directory
