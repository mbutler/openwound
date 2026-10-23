"""Read saved hierarchies and record one comparison. This does not load a model."""

import json
import uuid
from datetime import datetime, timezone

from ncm_art.comparison.agreement import (
    BAND_POLICY,
    METRIC_ID,
    PREPROCESSING,
    adjust,
    as_float,
    band_for,
    diagnose_baseline,
    prefix_agreement,
    profiles_match,
    require_compatible,
    require_prefix,
)
from ncm_art.storage.errors import ProjectError


def list_encodings(project) -> list[dict]:
    return [_public(item) for item in _load(project) if item["hierarchy_available"]]


def compare_hierarchies(project, query_id: str, prefix_count: int) -> dict:
    rows = _load(project)
    query = next((item for item in rows if item["id"] == query_id), None)
    if query is None or not query["hierarchy_available"]:
        raise ProjectError("NOT_FOUND", "That hierarchy is not available for comparison.", status=404)
    require_prefix(len(query["level_lengths"]), prefix_count)
    band = band_for(query["token_count"])
    excluded = {"query": 1, "duplicate_text": 0, "family": 0, "other_band": 0, "incompatible": 0, "unavailable": 0}
    seen_text = set()
    population = []
    population_ids = []
    pairs = []
    for item in rows:
        if item["id"] == query["id"]:
            continue
        if not item["hierarchy_available"] or item["kind"] != "source_encoding":
            excluded["unavailable"] += 1
            continue
        if not profiles_match(query, item):
            excluded["incompatible"] += 1
            continue
        same_band = band is not None and band_for(item["token_count"]) == band
        if not same_band:
            excluded["other_band"] += 1
        score = prefix_agreement(query["codes"], item["codes"], query["level_lengths"], prefix_count)
        pairs.append({"item": item, "score": score, "same_band": same_band})
        if not same_band:
            continue
        if query.get("family_id") and item.get("family_id") == query["family_id"]:
            excluded["family"] += 1
            continue
        if item["text_sha256"] in seen_text or item["text_sha256"] == query["text_sha256"]:
            excluded["duplicate_text"] += 1
            continue
        seen_text.add(item["text_sha256"])
        population.append(item["codes"])
        population_ids.append(item["id"])
    diagnosis = (
        diagnose_baseline(population, query["level_lengths"], prefix_count)
        if band is not None
        else {"state": "unavailable", "value": None, "count": 0}
    )
    if band is None:
        diagnosis = {"state": "unavailable", "value": None, "count": len(population_ids)}
    now = _now()
    comparison_id = str(uuid.uuid4())
    snapshot = {
        "count": diagnosis["count"],
        "representation_ids": population_ids,
        "excluded": excluded,
        "sparse_below": 8,
        "band": band,
    }
    stored_pairs = []
    for pair in pairs:
        adjusted = adjust(pair["score"]["agreement"], diagnosis["value"], diagnosis["state"]) if pair["same_band"] else None
        stored_pairs.append(
            {
                "id": str(uuid.uuid4()),
                "other_id": pair["item"]["id"],
                "agreement": as_float(pair["score"]["agreement"]),
                "adjusted": as_float(adjusted) if pair["same_band"] else None,
                "shared_prefix": pair["score"]["shared_prefix"],
                "same_band": pair["same_band"],
                "item": pair["item"],
            }
        )
    stored_pairs.sort(key=lambda pair: (not pair["same_band"], -(pair["agreement"] or 0), pair["other_id"]))
    with project.immediate_transaction() as conn:
        conn.execute(
            """INSERT INTO code_comparison(
                   id, query_representation_id, metric_id, prefix_count, band_policy, band_index,
                   snapshot_json, baseline_state, baseline_value, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                comparison_id,
                query_id,
                METRIC_ID,
                prefix_count,
                BAND_POLICY,
                None if band is None else band["index"],
                json.dumps(snapshot),
                diagnosis["state"],
                as_float(diagnosis["value"]),
                now,
            ),
        )
        for pair in stored_pairs:
            conn.execute(
                """INSERT INTO code_comparison_pair(
                       id, comparison_id, other_representation_id, agreement, adjusted, shared_prefix, same_band
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    pair["id"],
                    comparison_id,
                    pair["other_id"],
                    pair["agreement"],
                    pair["adjusted"],
                    1 if pair["shared_prefix"] else 0,
                    1 if pair["same_band"] else 0,
                ),
            )
    return _present(comparison_id, query, prefix_count, band, diagnosis, snapshot, stored_pairs, now)


def get_comparison(project, comparison_id: str) -> dict:
    with project._conn() as conn:
        row = conn.execute("SELECT * FROM code_comparison WHERE id=?", (comparison_id,)).fetchone()
        if row is None:
            raise ProjectError("NOT_FOUND", "That comparison is not in this project.", status=404)
        pairs = conn.execute(
            "SELECT * FROM code_comparison_pair WHERE comparison_id=? ORDER BY same_band DESC, agreement DESC, other_representation_id",
            (comparison_id,),
        ).fetchall()
    indexed = {item["id"]: item for item in _load(project)}
    query = indexed.get(row["query_representation_id"])
    if query is None:
        raise ProjectError("NOT_FOUND", "That comparison's hierarchy is missing.", status=404)
    snapshot = json.loads(row["snapshot_json"])
    diagnosis = {"state": row["baseline_state"], "value": row["baseline_value"], "count": snapshot.get("count", 0)}
    stored = []
    for pair in pairs:
        item = indexed.get(pair["other_representation_id"])
        if item is None:
            continue
        stored.append(
            {
                "id": pair["id"],
                "other_id": pair["other_representation_id"],
                "agreement": pair["agreement"],
                "adjusted": pair["adjusted"],
                "shared_prefix": bool(pair["shared_prefix"]),
                "same_band": bool(pair["same_band"]),
                "item": item,
            }
        )
    return _present(
        row["id"],
        query,
        row["prefix_count"],
        snapshot.get("band"),
        diagnosis,
        snapshot,
        stored,
        row["created_at"],
    )


def differing_positions(left_codes: list[int], right_codes: list[int], level_lengths: list[int], prefix_count: int) -> list[dict]:
    width = sum(level_lengths[:prefix_count])
    found = []
    cursor = 0
    for level_index, length in enumerate(level_lengths[:prefix_count]):
        for position in range(length):
            if cursor >= width:
                break
            if left_codes[cursor] != right_codes[cursor]:
                found.append(
                    {
                        "level_index": level_index,
                        "position": position,
                        "base_code": left_codes[cursor],
                        "donor_code": right_codes[cursor],
                    }
                )
            cursor += 1
    return found


def _present(comparison_id, query, prefix_count, band, diagnosis, snapshot, pairs, created_at) -> dict:
    return {
        "id": comparison_id,
        "metric_id": METRIC_ID,
        "prefix_count": prefix_count,
        "query": _public(query),
        "band": band,
        "baseline": {
            "state": diagnosis["state"],
            "value": diagnosis["value"] if isinstance(diagnosis["value"], float) or diagnosis["value"] is None else as_float(diagnosis["value"]),
            "count": diagnosis["count"],
            "message": _baseline_message(diagnosis, band),
        },
        "snapshot": snapshot,
        "pairs": [_pair_public(pair) for pair in pairs],
        "created_at": created_at,
    }


def _pair_public(pair: dict) -> dict:
    notes = []
    if pair["shared_prefix"]:
        notes.append("These prefixes match, so a reconstruction at this depth matches. That follows from the codes.")
    if not pair["same_band"]:
        notes.append("Different length band. No baseline is applied to this pair.")
    return {
        "representation_id": pair["other_id"],
        "text": pair["item"]["text"],
        "title": pair["item"]["title"],
        "token_count": pair["item"]["token_count"],
        "agreement": pair["agreement"],
        "adjusted": pair["adjusted"],
        "shared_prefix": pair["shared_prefix"],
        "same_band": pair["same_band"],
        "note": " ".join(notes),
    }


def _baseline_message(diagnosis: dict, band: dict | None) -> str:
    state = diagnosis["state"]
    count = diagnosis["count"]
    if band is None:
        return "This hierarchy has no token length, so there is no length-band baseline. The raw agreement is shown."
    if state == "unavailable":
        return "The baseline needs at least two other encodings in this length band. The raw agreement is shown."
    if state == "sparse":
        return (
            f"The baseline is sparse: {count} encodings in this length band. "
            "The adjustment is a diagnostic, not a measure of shared meaning."
        )
    if state == "degenerate":
        return "Every compared code in this prefix is the same across the baseline. The adjustment is undefined. The raw agreement is shown."
    return f"Agreement above the common-code baseline in this length band ({count} encodings)."


def _public(item: dict) -> dict:
    return {
        "id": item["id"],
        "kind": item["kind"],
        "text": item["text"],
        "title": item["title"],
        "token_count": item["token_count"],
        "passage_revision_id": item["passage_revision_id"],
        "fragment_id": item.get("fragment_id"),
        "family_id": item.get("family_id"),
    }


def _load(project) -> list[dict]:
    with project._conn() as conn:
        rows = conn.execute(
            """SELECT representation.*, run.parameters_json, passage_revision.text_sha256 AS passage_sha,
                      passage_revision.origin_kind
               FROM representation
               JOIN passage_revision ON passage_revision.id = representation.passage_revision_id
               LEFT JOIN run ON run.id = representation.run_id
               ORDER BY representation.created_at, representation.id"""
        ).fetchall()
    loaded = []
    for row in rows:
        parameters = json.loads(row["parameters_json"]) if row["parameters_json"] else {}
        if not isinstance(parameters, dict):
            parameters = {}
        policy = parameters.get("preprocessing_policy")
        if not policy and row["model_profile"] == "tinystories-v1":
            policy = PREPROCESSING
        codes = json.loads(row["codes_json"]) if row["codes_json"] else None
        token_count = row["token_count"]
        if token_count is None and isinstance(parameters.get("source_token_count"), int):
            token_count = parameters["source_token_count"]
        loaded.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "hierarchy_available": bool(row["hierarchy_available"]),
                "passage_revision_id": row["passage_revision_id"],
                "text": project._read_text(row["passage_sha"]),
                "text_sha256": row["passage_sha"],
                "title": parameters.get("source_title") or "Saved hierarchy",
                "token_count": token_count,
                "fragment_id": parameters.get("fragment_id"),
                "family_id": parameters.get("family_id"),
                "codes": codes or [],
                "level_lengths": json.loads(row["level_lengths_json"]),
                "codebook_sizes": json.loads(row["codebook_sizes_json"]),
                "model_profile": row["model_profile"],
                "tokenizer_fingerprint": row["tokenizer_fingerprint"],
                "preprocessing_policy": policy or "",
                "execution_profile": row["execution_profile"],
            }
        )
    return loaded


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def assert_pair(project, left_id: str, right_id: str, prefix_count: int) -> tuple[dict, dict]:
    rows = {item["id"]: item for item in _load(project)}
    left = rows.get(left_id)
    right = rows.get(right_id)
    if left is None or right is None or not left["hierarchy_available"] or not right["hierarchy_available"]:
        raise ProjectError("NOT_FOUND", "Choose two saved hierarchies.", status=404)
    require_compatible(left, right)
    require_prefix(len(left["level_lengths"]), prefix_count)
    return left, right
