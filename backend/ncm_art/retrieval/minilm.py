"""Pinned local MiniLM profile.

The model is loaded only in the worker, and only when an embedding job runs.
Missing weights leave lexical search available.
"""

import hashlib
import json
from pathlib import Path

from ncm_art.model_adapter.profile import repo_root
from ncm_art.storage.errors import ProjectError

PROFILE_ID = "minilm-l6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
REPOSITORY = "sentence-transformers/all-MiniLM-L6-v2"
DIMENSION = 384
MAX_SEQUENCE_LENGTH = 256
PREPROCESSING = "minilm-l6-v2-no-truncation"


def profile_path() -> Path:
    return repo_root() / "model_profiles" / "minilm-l6-v2.json"


def cache_dir() -> Path:
    return repo_root() / ".model-cache" / PROFILE_ID / REVISION


def profile_fingerprint() -> str:
    checksums: dict = {}
    path = profile_path()
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        checksums = payload.get("artifacts") or {}
    extra = hashlib.sha256(json.dumps(checksums, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"{PROFILE_ID}@{REVISION}#{extra}"


def verify_minilm() -> Path:
    directory = cache_dir()
    profile = json.loads(profile_path().read_text(encoding="utf-8"))
    artifacts = profile.get("artifacts") or {}
    if not artifacts:
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "The MiniLM profile has no recorded checksums.",
            {"profile": PROFILE_ID},
            status=503,
        )
    for name, meta in artifacts.items():
        path = directory / name
        if not path.is_file():
            raise ProjectError(
                "CAPABILITY_UNAVAILABLE",
                "The MiniLM embedding model is not available. Lexical search still works.",
                {"missing": name},
                status=503,
            )
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != meta["bytes"] or digest != meta["sha256"]:
            raise ProjectError(
                "CAPABILITY_UNAVAILABLE",
                "A MiniLM file does not match the pinned checksum.",
                {"file": name},
                status=503,
            )
    return directory


def install_minilm() -> Path:
    """Download the pinned snapshot into the local cache. Weights stay out of git."""
    destination = cache_dir()
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / "model.safetensors").is_file() and (destination / "tokenizer.json").is_file():
        return destination
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=REPOSITORY,
        revision=REVISION,
        local_dir=str(destination),
        allow_patterns=[
            "config.json",
            "config_sentence_transformers.json",
            "model.safetensors",
            "modules.json",
            "sentence_bert_config.json",
            "special_tokens_map.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "vocab.txt",
            "1_Pooling/config.json",
        ],
    )
    return destination


def load_encoder():
    """Return `(count_tokens, embed_texts)` for the pinned local snapshot."""
    directory = cache_dir()
    weights = list(directory.glob("*.safetensors")) + list(directory.glob("**/*.safetensors"))
    if not weights:
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "The MiniLM embedding model is not available. Lexical search still works.",
            {"profile": PROFILE_ID, "revision": REVISION},
            status=503,
        )
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise ProjectError(
            "CAPABILITY_UNAVAILABLE",
            "The MiniLM embedding model is not available. Lexical search still works.",
            {"reason": str(error)},
            status=503,
        ) from error
    model = SentenceTransformer(str(directory), local_files_only=True, trust_remote_code=False)

    def count_tokens(text: str) -> int:
        encoded = model.tokenizer(text, add_special_tokens=True, truncation=False)
        return len(encoded["input_ids"])

    def embed_texts(texts: list[str]) -> list[list[float]]:
        for text in texts:
            if count_tokens(text) > MAX_SEQUENCE_LENGTH:
                raise ProjectError(
                    "INVALID_TEXT",
                    "That passage is longer than the MiniLM window. It was not truncated.",
                    {"token_limit": MAX_SEQUENCE_LENGTH},
                )
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [row.tolist() for row in vectors]

    return count_tokens, embed_texts
