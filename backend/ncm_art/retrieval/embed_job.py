"""Embed imported leaves in the worker.

This job does not encode with TinyStories and does not change the draft.
Over-length input is windowed or left unembedded. It is not truncated.
"""

from ncm_art.corpus.sources import WindowBudget, leaf_fragments, record_model_windows
from ncm_art.jobs.worker import write_capabilities
from ncm_art.retrieval.minilm import (
    DIMENSION,
    MAX_SEQUENCE_LENGTH,
    PREPROCESSING,
    PROFILE_ID,
    load_encoder,
    profile_fingerprint,
)
from ncm_art.retrieval.vectors import embedding_for_text, store_embedding
from ncm_art.storage.errors import ProjectError


def execute_embed(project, job: dict, library_root=None, load=None) -> None:
    loader = load or load_encoder
    try:
        count_tokens, embed_texts = loader()
        if library_root is not None:
            write_capabilities(library_root, "ready", capability="embedding", profile=PROFILE_ID)
        record_model_windows(
            project,
            WindowBudget(
                profile_id=PROFILE_ID,
                limit=MAX_SEQUENCE_LENGTH,
                special_tokens_included=True,
                count=count_tokens,
                preprocessing_policy=PREPROCESSING,
            ),
        )
        fingerprint = profile_fingerprint()
        pending = []
        for row in leaf_fragments(project, "imported"):
            raw = project.read_asset_bytes(row["source_text_sha256"])
            text = raw[row["start_byte"] : row["end_byte"]].decode("utf-8")
            if count_tokens(text) > MAX_SEQUENCE_LENGTH:
                continue
            if embedding_for_text(project, text, fingerprint) is None:
                pending.append((row["id"], text))
        seen_inputs = {text for _fragment_id, text in pending}
        query = job["request"].get("query_text") or ""
        query_embedded = True
        message = None
        if query and count_tokens(query) > MAX_SEQUENCE_LENGTH:
            query_embedded = False
            message = "The query is longer than the MiniLM window. It was not truncated."
        elif query and query not in seen_inputs and embedding_for_text(project, query, fingerprint) is None:
            pending.append((f"query:{fingerprint}", query))
        embedded = 0
        for start in range(0, len(pending), 16):
            batch = pending[start : start + 16]
            vectors = embed_texts([text for _fragment_id, text in batch])
            for (fragment_id, text), vector in zip(batch, vectors, strict=True):
                if len(vector) != DIMENSION:
                    raise ProjectError(
                        "CAPABILITY_UNAVAILABLE",
                        "The embedding model returned an unexpected dimension.",
                        {"dimension": len(vector), "expected": DIMENSION},
                    )
                store_embedding(project, fragment_id, text, vector, fingerprint)
                embedded += 1
            project.update_progress(job["id"], {"stage": "embed", "embedded": embedded, "total": len(pending)})
        project.succeed(
            job["id"],
            {
                "embedded": embedded,
                "profile": PROFILE_ID,
                "query_embedded": query_embedded,
                "message": message,
            },
        )
    except ProjectError as error:
        _unavailable(library_root, error.message)
        project.fail(job["id"], error.code, error.message, error.details)
    except Exception as error:
        message = "The MiniLM embedding model is not available. Lexical search still works."
        _unavailable(library_root, str(error) or message)
        project.fail(job["id"], "CAPABILITY_UNAVAILABLE", message, {"reason": str(error)})


def _unavailable(library_root, message: str) -> None:
    if library_root is not None:
        write_capabilities(library_root, "unavailable", message, capability="embedding", profile=PROFILE_ID)
