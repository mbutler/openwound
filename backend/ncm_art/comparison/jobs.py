"""Encode selected windows, reconstruct one pair, or graft saved codes.

Encoding and reconstruction load TinyStories. Agreement itself does not.
A graft that changes no code does not call the generator.
"""

import uuid
from datetime import datetime, timezone

import torch

from ncm_art.comparison.agreement import PREPROCESSING
from ncm_art.comparison.service import assert_pair, differing_positions
from ncm_art.jobs.execute import (
    EXECUTION_PROFILE,
    MODEL_PROFILE,
    _fingerprints,
    _layout,
    _run_parameters,
    _save_source,
    _show,
)
from ncm_art.model_adapter.display import DISPLAY_POLICY_CUT_AT_EOS
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.sampling import validate_sampling
from ncm_art.model_adapter.tinystories import apply_graft, branch_tinystories, encode_source, reconstruct_trace
from ncm_art.storage.errors import ProjectError

DEFAULT_SAMPLING = {"temperature": 1.0, "top_k": 0, "top_p": 1.0}
NO_CHANGE = "Those codes already agree. Nothing was generated."


def queue_encode(project, fragment_ids: list[str], revision_ids: list[str], client_request_id: str) -> dict:
    targets = [{"kind": "fragment", "id": item} for item in fragment_ids]
    targets.extend({"kind": "passage_revision", "id": item} for item in revision_ids)
    if not targets or len(targets) > 8:
        raise ProjectError("INVALID_TEXT", "Encode one to eight passages.")
    for target in targets:
        if target["kind"] == "fragment":
            _fragment(project, target["id"])
        elif target["kind"] == "passage_revision":
            project.revision(target["id"])
        else:
            raise ProjectError("INVALID_TEXT", "Choose a source passage or a saved revision.")
    return project.submit_job("encode_corpus", {"targets": targets}, client_request_id)


def queue_reconstruction(project, left_id: str, right_id: str, prefix_count: int, client_request_id: str) -> dict:
    assert_pair(project, left_id, right_id, prefix_count)
    return project.submit_job(
        "pair_reconstruct",
        {
            "left_representation_id": left_id,
            "right_representation_id": right_id,
            "prefix_count": prefix_count,
        },
        client_request_id,
    )


def queue_graft(project, base_id: str, donor_id: str, prefix_count: int, positions: list[dict] | None, client_request_id: str) -> dict:
    base, donor = assert_pair(project, base_id, donor_id, prefix_count)
    chosen = _choose_positions(base, donor, prefix_count, positions)
    if not any(item["base_code"] != item["donor_code"] for item in chosen):
        return {"changed": False, "queued": False, "message": NO_CHANGE, "replacements": chosen}
    return project.submit_job(
        "latent_graft",
        {
            "base_representation_id": base_id,
            "donor_representation_id": donor_id,
            "prefix_count": prefix_count,
            "positions": [{"level_index": item["level_index"], "position": item["position"]} for item in chosen],
            "sampling": DEFAULT_SAMPLING,
        },
        client_request_id,
    )


def execute_encode(project, bundle, job: dict) -> dict | None:
    encoded = []
    cached = []
    skipped = []
    targets = job["request"]["targets"]
    fingerprint, _generator = _fingerprints(bundle)
    for index, target in enumerate(targets):
        if project.cancel_requested(job["id"]):
            project.finish_cancelled(job["id"], {"encoded": encoded, "cached": cached, "skipped": skipped})
            return None
        project.update_progress(
            job["id"],
            {"stage": f"encoding window {index + 1}", "window": index + 1, "window_count": len(targets)},
        )
        try:
            result = _encode_one(project, bundle, job, target, fingerprint)
        except AdapterError as error:
            if error.code == "INPUT_TOO_LONG":
                skipped.append({"id": target["id"], "message": error.message})
                continue
            raise
        if result["cached"]:
            cached.append(result["representation_id"])
        else:
            encoded.append(result["representation_id"])
    if not encoded and not cached:
        project.fail(
            job["id"],
            "INPUT_TOO_LONG",
            "Nothing was encoded. A passage longer than the model window was not truncated.",
            {"skipped": skipped},
        )
        return None
    return {"encoded": encoded, "cached": cached, "skipped": skipped}


def execute_pair(project, bundle, job: dict) -> dict:
    recipe = job["request"]
    left, right = assert_pair(project, recipe["left_representation_id"], recipe["right_representation_id"], recipe["prefix_count"])
    project.update_progress(job["id"], {"stage": "reconstructing the pair", "level": 0, "level_count": recipe["prefix_count"]})
    run_id = str(uuid.uuid4())
    with project.immediate_transaction() as conn:
        project.insert_run(
            conn,
            run_id,
            "pair_reconstruct",
            left["passage_revision_id"],
            _run_parameters(bundle, recipe, {"right_representation_id": right["id"]}),
            _now(),
        )
    sides = []
    for item in (left, right):
        trace = reconstruct_trace(bundle.vqvae, torch.tensor([item["codes"]], dtype=torch.long))
        frame = next(frame for frame in trace if frame["completed_levels"] == recipe["prefix_count"])
        text = _show(bundle, frame["raw_token_ids"])
        revision = project.commit_text(
            text,
            "decoded",
            parent_id=item["passage_revision_id"],
            relationship="decoded_from",
            run_id=run_id,
        )
        sides.append({"representation_id": item["id"], "revision_id": revision["id"], "text": text, "title": item["title"]})
        project.update_progress(
            job["id"],
            {"stage": "reconstructing the pair", "level": recipe["prefix_count"], "level_count": recipe["prefix_count"]},
        )
    shared = left["codes"][: sum(left["level_lengths"][: recipe["prefix_count"]])] == right["codes"][: sum(right["level_lengths"][: recipe["prefix_count"]])]
    return {
        "run_id": run_id,
        "prefix_count": recipe["prefix_count"],
        "sides": sides,
        "shared_prefix": shared,
        "note": "These prefixes match, so a reconstruction at this depth matches. That follows from the codes." if shared else "",
    }


def execute_graft(project, bundle, job: dict) -> dict | None:
    recipe = job["request"]
    base, donor = assert_pair(project, recipe["base_representation_id"], recipe["donor_representation_id"], recipe["prefix_count"])
    positions = [(item["level_index"], item["position"]) for item in recipe["positions"]]
    levels, sizes = _layout(bundle)
    if levels != base["level_lengths"] or sizes != base["codebook_sizes"]:
        raise ProjectError(
            "PROFILE_MISMATCH",
            "Those hierarchies were not made with the same tokenizer, checkpoint, preprocessing, and level layout.",
            status=409,
        )
    grafted = apply_graft(
        torch.tensor([base["codes"]], dtype=torch.long),
        torch.tensor([donor["codes"]], dtype=torch.long),
        positions,
        int(recipe["prefix_count"]),
        levels,
        sizes,
    )
    replacements = [
        {
            "level_index": item.level_index,
            "position": item.position,
            "original_code": item.original_code,
            "replacement_code": item.replacement_code,
        }
        for item in grafted.replacements
    ]
    if not grafted.changed:
        return {"changed": False, "message": NO_CHANGE, "replacements": replacements}
    if project.cancel_requested(job["id"]):
        project.finish_cancelled(job["id"], {"changed": False, "replacements": replacements})
        return None
    project.update_progress(job["id"], {"stage": "preparing latent graft", "level": 0, "level_count": len(levels)})
    sampling = validate_sampling(
        recipe["sampling"]["temperature"],
        recipe["sampling"]["top_k"],
        recipe["sampling"]["top_p"],
        codebook_size=int(bundle.vqvae.vq.vqvae_vocab_sizes[0]),
    )
    retained = int(recipe["prefix_count"])
    level_count = len(levels)
    seed = int(recipe["seed"])
    tokenizer_fingerprint, generator_fingerprint = _fingerprints(bundle)
    run_id = str(uuid.uuid4())
    with project.immediate_transaction() as conn:
        project.insert_run(
            conn,
            run_id,
            "latent_graft",
            base["passage_revision_id"],
            _run_parameters(
                bundle,
                recipe,
                {
                    "donor_representation_id": donor["id"],
                    "positions": recipe["positions"],
                    "seed": seed,
                    "source_title": "Latent graft",
                },
            ),
            _now(),
        )

    def on_level(level, _code, _state):
        project.update_progress(
            job["id"],
            {"stage": "preparing latent graft", "level": level, "level_count": level_count},
        )

    torch.manual_seed(seed)
    branched = branch_tinystories(
        None if retained == level_count else bundle.generator,
        bundle.vqvae,
        grafted.codes,
        retained,
        bundle.pre_tokenizer.eos_token_id,
        None if retained else bundle.level0_unigram,
        sampling,
        on_level=on_level,
    )
    raw = bundle.vqvae.decode(branched.codes).argmax(dim=-1)
    text = _show(bundle, raw)
    revision = project.save_generated_candidate(
        text,
        parent_id=base["passage_revision_id"],
        run_id=run_id,
        codes=[int(code) for code in branched.codes[0].tolist()],
        level_lengths=levels,
        codebook_sizes=sizes,
        raw_token_ids=[int(token) for token in raw[0].tolist()],
        retained_level_count=retained,
        sampling=recipe.get("sampling"),
        seed=seed,
        source_representation_id=base["id"],
        candidate_index=0,
        model_profile=MODEL_PROFILE,
        execution_profile=EXECUTION_PROFILE,
        tokenizer_fingerprint=tokenizer_fingerprint,
        generator_fingerprint=generator_fingerprint,
        display_policy=DISPLAY_POLICY_CUT_AT_EOS,
        relationship="grafted_from",
        extra_parents=[(donor["passage_revision_id"], "grafted_from")],
    )
    return {
        "changed": True,
        "message": "Latent graft. This replaces codes. It does not move a phrase.",
        "run_id": run_id,
        "revision_id": revision["id"],
        "representation_id": revision["representation_id"],
        "text": text,
        "replacements": replacements,
        "seed": seed,
    }


def _encode_one(project, bundle, job, target, fingerprint) -> dict:
    if target["kind"] == "fragment":
        text, source, _row = _fragment(project, target["id"])
        existing = _cached_fragment(project, target["id"], fingerprint)
        if existing:
            return {"cached": True, "representation_id": existing}
        revision_id = str(uuid.uuid4())
        with project.immediate_transaction() as conn:
            project.insert_revision(
                conn,
                revision_id=revision_id,
                text_sha256=project._write_text(text),
                origin_kind="corpus_encoding",
                source_id=source["id"],
                created_at=_now(),
            )
        passage = project.revision(revision_id)
        title = source["title"]
        family_id = source["family_id"]
        fragment_id = target["id"]
    else:
        passage = project.revision(target["id"])
        text = passage["text"]
        existing = _cached_revision(project, passage["id"], fingerprint)
        if existing:
            return {"cached": True, "representation_id": existing}
        title = _entry_title(project, passage["id"]) or "Saved hierarchy"
        family_id = None
        fragment_id = None
    tokens, codes, token_count = encode_source(text, bundle.pre_tokenizer, bundle.vqvae)
    _run_id, representation_id = _save_source(
        project,
        bundle,
        passage,
        "encode_corpus",
        job["request"],
        {
            "fragment_id": fragment_id,
            "source_title": title,
            "family_id": family_id,
            "preprocessing_policy": PREPROCESSING,
            "token_count": token_count,
        },
        tokens[0].detach().cpu().tolist(),
        codes[0].detach().cpu().tolist(),
        token_count,
    )
    return {"cached": False, "representation_id": representation_id}


def _choose_positions(base: dict, donor: dict, prefix_count: int, positions: list[dict] | None) -> list[dict]:
    if positions is None:
        return differing_positions(base["codes"], donor["codes"], base["level_lengths"], prefix_count)
    chosen = []
    seen = set()
    widths = base["level_lengths"]
    for item in positions:
        level_index = item.get("level_index")
        position = item.get("position")
        if isinstance(level_index, bool) or not isinstance(level_index, int):
            raise ProjectError("INVALID_TEXT", "A graft level must be an integer.")
        if isinstance(position, bool) or not isinstance(position, int):
            raise ProjectError("INVALID_TEXT", "A graft position must be an integer.")
        if (level_index, position) in seen:
            raise ProjectError(
                "INVALID_TEXT",
                "That code position is already in this graft.",
                {"level_index": level_index, "position": position},
            )
        seen.add((level_index, position))
        if level_index < 0 or level_index >= prefix_count:
            raise ProjectError(
                "INVALID_TEXT",
                "retained_level_count must be greater than the highest modified level.",
                {"retained_level_count": prefix_count, "level_index": level_index},
                status=409,
            )
        if position < 0 or position >= widths[level_index]:
            raise ProjectError("INVALID_TEXT", f"Position {position} is outside level {level_index}.")
        offset = sum(widths[:level_index]) + position
        chosen.append(
            {
                "level_index": level_index,
                "position": position,
                "base_code": base["codes"][offset],
                "donor_code": donor["codes"][offset],
            }
        )
    if not chosen:
        raise ProjectError("INVALID_TEXT", "A graft needs at least one code position.")
    return chosen


def _fragment(project, fragment_id: str):
    with project._conn() as conn:
        row = conn.execute("SELECT * FROM source_fragment WHERE id=?", (fragment_id,)).fetchone()
        source = None
        if row is not None:
            source = conn.execute(
                "SELECT id, title, family_id, collection FROM source_document WHERE id=?",
                (row["source_id"],),
            ).fetchone()
    if row is None or source is None or source["collection"] != "imported":
        raise ProjectError("NOT_FOUND", "That source passage is not in this project.", status=404)
    raw = project.read_asset_bytes(row["source_text_sha256"])
    text = raw[row["start_byte"] : row["end_byte"]].decode("utf-8")
    return text, source, row


def _cached_fragment(project, fragment_id: str, fingerprint: str) -> str | None:
    with project._conn() as conn:
        row = conn.execute(
            """SELECT representation.id FROM representation
               JOIN run ON run.id = representation.run_id
               WHERE representation.kind = 'source_encoding'
                 AND representation.hierarchy_available = 1
                 AND representation.tokenizer_fingerprint = ?
                 AND representation.model_profile = ?
                 AND json_extract(run.parameters_json, '$.fragment_id') = ?""",
            (fingerprint, MODEL_PROFILE, fragment_id),
        ).fetchone()
    return None if row is None else row["id"]


def _cached_revision(project, revision_id: str, fingerprint: str) -> str | None:
    for item in project.representations_for(revision_id):
        if (
            item["kind"] == "source_encoding"
            and item["hierarchy_available"]
            and item["tokenizer_fingerprint"] == fingerprint
            and item["model_profile"] == MODEL_PROFILE
        ):
            return item["id"]
    return None


def _entry_title(project, revision_id: str) -> str | None:
    with project._conn() as conn:
        row = conn.execute(
            """SELECT work.title FROM work_entry
               JOIN work ON work.id = work_entry.work_id
               WHERE work_entry.passage_revision_id = ?
               LIMIT 1""",
            (revision_id,),
        ).fetchone()
    return None if row is None else row["title"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
