"""Bounded encounters.

Views are interleaved. They are not fused into one significance score.
Another passage is a seeded shuffle with a saved cursor.
"""

import json
import random
import uuid
from datetime import datetime, timezone

from ncm_art.corpus.anchors import make_anchor
from ncm_art.corpus.sources import get_source_row, leaf_fragments, latest_snapshot_id
from ncm_art.retrieval.lexical import search as lexical_search
from ncm_art.retrieval.minilm import profile_fingerprint
from ncm_art.retrieval.semantic import select_related
from ncm_art.retrieval.vectors import embedding_for_text
from ncm_art.storage.errors import ProjectError

DEFAULT_LIMIT = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_encounter(
    project,
    *,
    text: str,
    source_id: str | None = None,
    start_byte: int | None = None,
    end_byte: int | None = None,
    views: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    include_same_document: bool = False,
    include_same_family: bool = False,
    collection: str = "imported",
    fingerprint: str | None = None,
) -> dict:
    if collection != "imported":
        raise ProjectError("INVALID_TEXT", "Encounter search uses imported sources unless a work collection is chosen later.")
    chosen_views = views or ["lexical", "semantic"]
    unknown = [view for view in chosen_views if view not in {"lexical", "semantic"}]
    if unknown:
        raise ProjectError("INVALID_TEXT", "That retrieval view is not available.", {"views": unknown})
    limit = 6 if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 else min(limit, 20)
    query_source = None
    query_family = None
    if source_id:
        query_source = get_source_row(project, source_id)
        query_family = query_source["family_id"]
        if start_byte is None or end_byte is None:
            raw = project.read_asset_bytes(query_source["text_sha256"])
            start_byte, end_byte = 0, len(raw)
    profile = fingerprint or profile_fingerprint()
    groups = []
    semantic_state = "skipped"
    if "lexical" in chosen_views:
        groups.append(
            _prepare(
                lexical_search(project, text, collection),
                text,
                source_id,
                query_family,
                start_byte,
                end_byte,
                include_same_document,
                include_same_family,
            )
        )
    if "semantic" in chosen_views:
        semantic_hits, semantic_state = _semantic(
            project,
            text,
            collection,
            profile,
            limit,
            source_id,
            query_family,
            start_byte,
            end_byte,
            include_same_document,
            include_same_family,
        )
        if semantic_state == "ready":
            groups.append(semantic_hits)
    hits = _interleave(groups, limit)
    for hit in hits:
        hit.pop("vector", None)
        raw = project.read_asset_bytes(hit["text_sha256"])
        hit["anchor"] = make_anchor("source_version", hit["source_id"], raw, hit["start_byte"], hit["end_byte"])
    encounter_id = str(uuid.uuid4())
    created = _now()
    recipe = {
        "views": chosen_views,
        "limit": limit,
        "collection": collection,
        "include_same_document": include_same_document,
        "include_same_family": include_same_family,
        "profile_fingerprint": profile,
    }
    query = {"text": text, "source_id": source_id, "start_byte": start_byte, "end_byte": end_byte}
    with project.immediate_transaction() as conn:
        conn.execute(
            """INSERT INTO encounter(id, snapshot_id, recipe_json, query_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (encounter_id, latest_snapshot_id(project, collection), json.dumps(recipe), json.dumps(query), created),
        )
        for ordinal, hit in enumerate(hits):
            conn.execute(
                """INSERT INTO encounter_hit(
                       id, encounter_id, ordinal, view, fragment_id, owner_kind, owner_id,
                       start_byte, end_byte, slice_sha256, score, reason, detail_json
                   ) VALUES (?, ?, ?, ?, ?, 'source_version', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    encounter_id,
                    ordinal,
                    hit["view"],
                    hit["fragment_id"],
                    hit["source_id"],
                    hit["start_byte"],
                    hit["end_byte"],
                    hit["slice_sha256"],
                    hit["score"],
                    hit["reason"],
                    json.dumps(
                        {
                            "reasons": hit["reasons"],
                            "matched_spans": hit.get("matched_spans") or [],
                            "folded": hit.get("folded", False),
                            "recipe": hit.get("recipe"),
                            "also": hit.get("also") or [],
                            "title": hit["title"],
                            "author": hit["author"],
                        }
                    ),
                ),
            )
    return {
        "id": encounter_id,
        "created_at": created,
        "hits": hits,
        "semantic": {"state": semantic_state},
        "recipe": recipe,
        "query": query,
    }


def get_encounter(project, encounter_id: str) -> dict:
    with project._conn() as conn:
        row = conn.execute("SELECT * FROM encounter WHERE id = ?", (encounter_id,)).fetchone()
        hits = conn.execute(
            "SELECT * FROM encounter_hit WHERE encounter_id = ? ORDER BY ordinal",
            (encounter_id,),
        ).fetchall()
    if row is None:
        raise ProjectError("NOT_FOUND", "That encounter is not in this project.", status=404)
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "recipe": json.loads(row["recipe_json"]),
        "query": json.loads(row["query_json"]),
        "hits": [_saved_hit(project, hit) for hit in hits],
    }


def another_passage(project, collection: str = "imported") -> dict:
    leaves = list(leaf_fragments(project, collection))
    if not leaves:
        raise ProjectError("NOT_FOUND", "Import a source to start from.", status=404)
    with project.immediate_transaction() as conn:
        seed = _meta(conn, "encounter_seed")
        if seed is None:
            seed = str(random.SystemRandom().randrange(2**32))
            _set_meta(conn, "encounter_seed", seed)
        cursor = int(_meta(conn, "encounter_cursor") or "0")
        order = sorted(row["id"] for row in leaves)
        random.Random(int(seed)).shuffle(order)
        cursor %= len(order)
        chosen_id = order[cursor]
        _set_meta(conn, "encounter_cursor", str(cursor + 1))
    chosen = next(row for row in leaves if row["id"] == chosen_id)
    raw = project.read_asset_bytes(chosen["source_text_sha256"])
    text = raw[chosen["start_byte"] : chosen["end_byte"]].decode("utf-8")
    return {
        "fragment_id": chosen["id"],
        "source_id": chosen["source_id"],
        "title": chosen["title"],
        "author": chosen["author"],
        "text": text,
        "anchor": make_anchor("source_version", chosen["source_id"], raw, chosen["start_byte"], chosen["end_byte"]),
        "reason": "Another passage from the imported sources. The order is a saved shuffle.",
    }


def _semantic(project, text, collection, fingerprint, limit, source_id, family_id, start, end, include_same_document, include_same_family):
    query_vector = embedding_for_text(project, text, fingerprint)
    if query_vector is None:
        return [], "missing"
    candidates = []
    for row in leaf_fragments(project, collection):
        raw = project.read_asset_bytes(row["source_text_sha256"])
        passage = raw[row["start_byte"] : row["end_byte"]].decode("utf-8")
        vector = embedding_for_text(project, passage, fingerprint)
        if vector is None:
            return [], "missing"
        candidates.append(
            {
                "id": row["id"],
                "fragment_id": row["id"],
                "source_id": row["source_id"],
                "title": row["title"],
                "author": row["author"],
                "family_id": row["family_id"],
                "start_byte": row["start_byte"],
                "end_byte": row["end_byte"],
                "slice_sha256": row["slice_sha256"],
                "text_sha256": row["source_text_sha256"],
                "text": passage,
                "vector": vector,
            }
        )
    ranked = select_related(text, candidates, query_vector, max(limit * 3, 12))
    return (
        _prepare(ranked, text, source_id, family_id, start, end, include_same_document, include_same_family),
        "ready",
    )


def _prepare(hits, query_text, source_id, family_id, start, end, include_same_document, include_same_family):
    kept = []
    for hit in hits:
        if hit["text"] == query_text:
            continue
        if source_id and hit["source_id"] == source_id and not include_same_document:
            continue
        if family_id and hit.get("family_id") == family_id and hit["source_id"] != source_id and not include_same_family:
            continue
        if source_id and hit["source_id"] == source_id and start is not None and end is not None:
            if not (hit["end_byte"] <= start or hit["start_byte"] >= end):
                continue
        kept.append(hit)
    grouped = _group(kept, source_id)
    return _spread(grouped, source_id)


def _group(hits, query_source_id):
    groups: dict[str, list] = {}
    order: list[str] = []
    for hit in hits:
        key = hit["slice_sha256"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(hit)
    result = []
    for key in order:
        members = groups[key]
        primary = next((item for item in members if item["source_id"] != query_source_id), members[0])
        item = dict(primary)
        item["also"] = [
            {
                "source_id": other["source_id"],
                "title": other["title"],
                "fragment_id": other["fragment_id"],
                "start_byte": other["start_byte"],
                "end_byte": other["end_byte"],
            }
            for other in members
            if other["fragment_id"] != primary["fragment_id"]
        ]
        item["reasons"] = [{"view": item["view"], "reason": item["reason"]}]
        result.append(item)
    return result


def _spread(hits, query_source_id):
    other = []
    same = []
    extra = []
    seen: set[str] = set()
    for hit in hits:
        if hit["source_id"] in seen:
            extra.append(hit)
            continue
        seen.add(hit["source_id"])
        if query_source_id and hit["source_id"] == query_source_id:
            same.append(hit)
        else:
            other.append(hit)
    return other + same + extra


def _interleave(groups: list[list[dict]], limit: int) -> list[dict]:
    chosen: dict[tuple, dict] = {}
    order: list[tuple] = []
    indexes = [0] * len(groups)
    while len(order) < limit:
        progressed = False
        for index, group in enumerate(groups):
            if len(order) >= limit:
                break
            while indexes[index] < len(group):
                hit = group[indexes[index]]
                indexes[index] += 1
                key = (hit["source_id"], hit["start_byte"], hit["end_byte"])
                if key in chosen:
                    for reason in hit["reasons"]:
                        if reason not in chosen[key]["reasons"]:
                            chosen[key]["reasons"].append(reason)
                    continue
                chosen[key] = hit
                order.append(key)
                progressed = True
                break
        if not progressed:
            break
    return [chosen[key] for key in order]


def _saved_hit(project, row) -> dict:
    detail = json.loads(row["detail_json"])
    source = get_source_row(project, row["owner_id"])
    raw = project.read_asset_bytes(source["text_sha256"])
    text = raw[row["start_byte"] : row["end_byte"]].decode("utf-8")
    return {
        "fragment_id": row["fragment_id"],
        "source_id": row["owner_id"],
        "title": detail.get("title") or source["title"],
        "author": detail.get("author"),
        "text": text,
        "view": row["view"],
        "reason": row["reason"],
        "reasons": detail.get("reasons") or [{"view": row["view"], "reason": row["reason"]}],
        "score": row["score"],
        "matched_spans": detail.get("matched_spans") or [],
        "folded": detail.get("folded", False),
        "also": detail.get("also") or [],
        "recipe": detail.get("recipe"),
        "start_byte": row["start_byte"],
        "end_byte": row["end_byte"],
        "slice_sha256": row["slice_sha256"],
        "anchor": make_anchor("source_version", row["owner_id"], raw, row["start_byte"], row["end_byte"]),
    }


def _meta(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO meta(key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
