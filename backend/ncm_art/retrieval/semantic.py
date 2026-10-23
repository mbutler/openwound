"""Related-meaning rank.

Semantic candidates come first. Lower lexical overlap is a second pass inside
that pool. Overlap by itself is not a retrieval view.
"""

from ncm_art.retrieval.text import jaccard
from ncm_art.retrieval.vectors import dot, normalize

RECIPE = "minilm-l6-v2-cosine-low-overlap-v1"
OVERLAP_LIMIT = 0.6


def select_related(query_text: str, candidates: list[dict], query_vector: list[float], limit: int) -> list[dict]:
    """Rank candidate dicts that already carry `id`, `text`, and `vector`."""
    query = normalize(query_vector)
    scored = []
    for candidate in candidates:
        vector = normalize(candidate["vector"])
        scored.append((dot(query, vector), candidate["id"], candidate, vector))
    scored.sort(key=lambda item: (-item[0], item[1]))
    pool = scored[: max(limit * 4, 24)]
    kept = [item for item in pool if jaccard(query_text, item[2]["text"]) <= OVERLAP_LIMIT]
    chosen = kept or pool
    chosen.sort(key=lambda item: (-item[0], item[1]))
    results = []
    for score, _identifier, candidate, _vector in chosen[:limit]:
        item = dict(candidate)
        item["score"] = score
        item["view"] = "semantic"
        item["reason"] = "Different words, related meaning"
        item["recipe"] = RECIPE
        results.append(item)
    return results
