"""Run one claimed job and commit its passages before the next candidate.

A finished job does not change the selected passage or the editor draft, including
edits saved while the job is running. Cancellation keeps every candidate that
already committed.
"""

import torch

from ncm_art import __version__
from ncm_art.model_adapter.display import DISPLAY_POLICY_CUT_AT_EOS
from ncm_art.model_adapter.errors import AdapterError
from ncm_art.model_adapter.sampling import validate_sampling
from ncm_art.model_adapter.seeds import candidate_seed
from ncm_art.model_adapter.tinystories import (
    branch_tinystories,
    decode_displayed,
    encode_source,
    reconstruct_trace,
)
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.project import Project


def execute_job(project: Project, bundle, job: dict, before_candidate=None) -> None:
    job_id = job["id"]
    try:
        if job["operation"] == "reconstruct":
            result = _reconstruct(project, bundle, job)
        elif job["operation"] == "variants":
            result = _variants(project, bundle, job, before_candidate)
        else:
            project.fail(job_id, "JOB_FAILED", f"Unknown operation {job['operation']}.")
            return
        if result is None:
            return
        project.succeed(job_id, result)
    except AdapterError as error:
        project.fail(job_id, error.code, error.message, error.details)
    except ProjectError as error:
        project.fail(job_id, error.code, error.message, error.details)
    except Exception as error:
        project.fail(job_id, "JOB_FAILED", str(error))


def _encode(project: Project, bundle, job: dict, passage: dict) -> tuple[list[int], list[int], int]:
    project.update_progress(job["id"], {"stage": "encode"})
    tokens, codes, token_count = encode_source(passage["text"], bundle.pre_tokenizer, bundle.vqvae)
    return tokens[0].detach().cpu().tolist(), codes[0].detach().cpu().tolist(), token_count


def _run_parameters(bundle, recipe: dict, extra: dict) -> dict:
    fingerprint = {}
    hashes = getattr(bundle, "file_hashes", None) or {}
    if hashes:
        fingerprint = {"artifact_sha256": hashes}
    return {
        "model_profile": "tinystories-v1",
        "execution_profile": "cpu-fp32-eager-v1",
        "display_policy": DISPLAY_POLICY_CUT_AT_EOS,
        "adapter_version": __version__,
        "torch": torch.__version__,
        "sampling": recipe.get("sampling"),
        "retained_level_count": recipe.get("retained_level_count"),
        "base_seed": recipe.get("base_seed"),
        **fingerprint,
        **extra,
    }


def _show(bundle, raw_ids) -> str:
    return decode_displayed(
        raw_ids,
        bundle.pre_tokenizer.eos_token_id,
        bundle.pre_tokenizer.pad_token_id,
        bundle.pre_tokenizer,
    )


def _reconstruct(project: Project, bundle, job: dict) -> dict:
    recipe = job["request"]
    passage = project.revision(recipe["passage_revision_id"])
    _padded, code_list, token_count = _encode(project, bundle, job, passage)
    run_id = project.record_run(
        "reconstruct",
        passage["id"],
        _run_parameters(bundle, recipe, {"token_count": token_count}),
    )
    encoding_id = project.record_encoding(
        passage["id"],
        token_count,
        code_list,
        _padded,
        run_id,
    )
    project.update_progress(job["id"], {"stage": "reconstruct", "level": 0, "level_count": 12})
    trace = reconstruct_trace(bundle.vqvae, torch.tensor([code_list], dtype=torch.long))
    frames = []
    for frame in trace:
        text = _show(bundle, frame["raw_token_ids"])
        revision = project.commit_text(
            text,
            "decoded",
            parent_id=passage["id"],
            relationship="decoded_from",
            run_id=run_id,
        )
        frames.append(
            {
                "level": frame["completed_levels"],
                "revision_id": revision["id"],
                "text": text,
                "raw_token_ids": frame["raw_token_ids"][0].tolist(),
            }
        )
        project.update_progress(
            job["id"],
            {"stage": "reconstruct", "level": frame["completed_levels"], "level_count": len(trace)},
        )
    reconstruction_id = project.record_reconstruction(run_id, encoding_id, frames)
    return {
        "run_id": run_id,
        "encoding_id": encoding_id,
        "reconstruction_id": reconstruction_id,
        "passage_revision_id": passage["id"],
        "frames": frames,
    }


def _variants(project: Project, bundle, job: dict, before_candidate) -> dict | None:
    recipe = job["request"]
    passage = project.revision(recipe["passage_revision_id"])
    _padded, code_list, token_count = _encode(project, bundle, job, passage)
    source_codes = torch.tensor([code_list], dtype=torch.long)
    sampling = validate_sampling(
        recipe["sampling"]["temperature"],
        recipe["sampling"]["top_k"],
        recipe["sampling"]["top_p"],
        codebook_size=int(bundle.vqvae.vq.vqvae_vocab_sizes[0]),
    )
    retained = int(recipe["retained_level_count"])
    count = int(recipe["candidate_count"])
    level_count = len(bundle.vqvae.vq.levels)
    seeds = [candidate_seed(int(recipe["base_seed"]), index) for index in range(count)]
    run_id = project.record_run(
        "variants",
        passage["id"],
        _run_parameters(bundle, recipe, {"candidate_seeds": seeds, "token_count": token_count}),
    )
    candidates = []
    for index, seed in enumerate(seeds):
        if before_candidate is not None:
            before_candidate(index)
        if project.cancel_requested(job["id"]):
            project.finish_cancelled(
                job["id"],
                {"run_id": run_id, "passage_revision_id": passage["id"], "candidates": candidates},
            )
            return None
        project.update_progress(
            job["id"],
            {
                "stage": "generate",
                "candidate": index + 1,
                "candidate_count": count,
                "level": 0,
                "level_count": level_count,
            },
        )

        def on_level(level, _code, _state, current=index + 1):
            project.update_progress(
                job["id"],
                {
                    "stage": "generate",
                    "candidate": current,
                    "candidate_count": count,
                    "level": level,
                    "level_count": level_count,
                },
            )

        torch.manual_seed(seed)
        branched = branch_tinystories(
            None if retained == level_count else bundle.generator,
            bundle.vqvae,
            None if retained == 0 else source_codes,
            retained,
            bundle.pre_tokenizer.eos_token_id,
            None if retained else bundle.level0_unigram,
            sampling,
            on_level=on_level,
        )
        text = _show(bundle, bundle.vqvae.decode(branched.codes).argmax(dim=-1))
        revision = project.commit_text(
            text,
            "generated",
            parent_id=passage["id"],
            relationship="generated_from",
            run_id=run_id,
        )
        candidates.append(
            {
                "index": index,
                "seed": seed,
                "prediction_count": branched.prediction_count,
                "revision_id": revision["id"],
                "text": text,
            }
        )
    return {"run_id": run_id, "passage_revision_id": passage["id"], "candidates": candidates}
