"""Cached passage vectors, keyed by the exact input and the profile fingerprint."""

import hashlib
import json
import math
import uuid
from datetime import datetime, timezone

from ncm_art.storage.errors import ProjectError

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(vector: list[float]) -> list[float]:
    if not vector or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in vector):
        raise ProjectError("INVALID_TEXT", "That embedding is not a numeric vector.")
    if any(not math.isfinite(float(value)) for value in vector):
        raise ProjectError("INVALID_TEXT", "That embedding is not a finite vector.")
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm == 0.0:
        raise ProjectError("INVALID_TEXT", "That embedding has length zero.")
    return [float(value) / norm for value in vector]


def dot(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ProjectError("INVALID_TEXT", "Those embeddings do not share a dimension.")
    return sum(a * b for a, b in zip(left, right, strict=True))


def input_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store_embedding(project, fragment_id: str, text: str, vector: list[float], fingerprint: str) -> None:
    stored = normalize(vector)
    with project.immediate_transaction() as conn:
        conn.execute(
            """INSERT INTO embedding(
                   id, fragment_id, input_sha256, profile_fingerprint, dimension, normalized, vector_json, created_at
               ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(input_sha256, profile_fingerprint) DO NOTHING""",
            (
                str(uuid.uuid4()),
                fragment_id,
                input_sha256(text),
                fingerprint,
                len(stored),
                json.dumps(stored),
                _now(),
            ),
        )


def embedding_for_text(project, text: str, fingerprint: str) -> list[float] | None:
    with project._conn() as conn:
        row = conn.execute(
            """SELECT vector_json, normalized FROM embedding
               WHERE input_sha256 = ? AND profile_fingerprint = ?""",
            (input_sha256(text), fingerprint),
        ).fetchone()
    if row is None:
        return None
    vector = json.loads(row["vector_json"])
    if not row["normalized"]:
        return normalize(vector)
    return vector
