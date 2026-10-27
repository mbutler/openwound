"""Routes for the instrument and Memory Weather.

Trace and vary return results without writing anything. Keep commits a
result with its exact encoding and sampled hierarchy, through the same
records the job path uses, so provenance reads the same either way.
"""

from pydantic import BaseModel, Field

from ncm_art import __version__
from ncm_art.live.engine import EXECUTION_PROFILE, MODEL_PROFILE, LiveEngine
from ncm_art.model_adapter.display import DISPLAY_POLICY_CUT_AT_EOS
from ncm_art.model_adapter.sampling import validate_sampling
from ncm_art.storage.errors import ProjectError
from ncm_art.storage.library import Library

MAX_STEPS = 48


class TraceBody(BaseModel):
    text: str


class VaryBody(BaseModel):
    text: str | None = None
    codes: list[int] | None = None
    keep: int = 6
    seed: int | None = None
    temperature: float = 1.0
    top_k: int = 0
    top_p: float = 1.0
    trim: bool = False


class Variation(BaseModel):
    text: str
    codes: list[int]
    raw_token_ids: list[int]
    keep: int
    seed: int
    sampling: dict


class KeepVariationBody(BaseModel):
    source_text: str
    source_codes: list[int]
    source_padded_token_ids: list[int]
    source_token_count: int
    variation: Variation


class KeepFrameBody(BaseModel):
    source_text: str
    source_codes: list[int]
    source_padded_token_ids: list[int]
    source_token_count: int
    level: int
    text: str
    raw_token_ids: list[int]


class WeatherStep(BaseModel):
    reset: bool = False
    trimmed: bool = False
    input_text: str
    input_codes: list[int]
    input_padded_token_ids: list[int]
    input_token_count: int
    variation: Variation


class KeepRunBody(BaseModel):
    source_text: str
    keep: int
    steps: list[WeatherStep] = Field(min_length=1, max_length=MAX_STEPS)


def _parameters(engine: LiveEngine, operation: str, extra: dict) -> dict:
    hashes = getattr(engine._ready(), "file_hashes", None) or {}
    return {
        "operation": operation,
        "model_profile": MODEL_PROFILE,
        "execution_profile": EXECUTION_PROFILE,
        "display_policy": DISPLAY_POLICY_CUT_AT_EOS,
        "adapter_version": __version__,
        **({"artifact_sha256": hashes} if hashes else {}),
        **extra,
    }


def _source_revision(project, text: str) -> dict:
    """The instrument's passage is the draft. Keeping it makes it a revision."""
    project.set_draft(text)
    return project.ensure_input_revision()


def _commit_variation(engine: LiveEngine, project, *, parent: dict, source_codes, padded, token_count, variation: Variation, operation: str, extra: dict) -> dict:
    layout = engine.layout()
    tokenizer_fingerprint, generator_fingerprint = engine.fingerprints()
    run_id, encoding_id = project.save_source_run(
        operation=operation,
        passage_revision_id=parent["id"],
        parameters=_parameters(engine, operation, {"retained_level_count": variation.keep, "base_seed": variation.seed, "sampling": variation.sampling, **extra}),
        token_count=token_count,
        codes=source_codes,
        padded_token_ids=padded,
        level_lengths=layout["levels"],
        codebook_sizes=layout["codebook_sizes"],
        model_profile=MODEL_PROFILE,
        execution_profile=EXECUTION_PROFILE,
        tokenizer_fingerprint=tokenizer_fingerprint,
        generator_fingerprint=generator_fingerprint,
        display_policy=DISPLAY_POLICY_CUT_AT_EOS,
    )
    return project.save_generated_candidate(
        variation.text,
        parent_id=parent["id"],
        run_id=run_id,
        codes=variation.codes,
        level_lengths=layout["levels"],
        codebook_sizes=layout["codebook_sizes"],
        raw_token_ids=variation.raw_token_ids,
        retained_level_count=variation.keep,
        sampling=variation.sampling,
        seed=variation.seed,
        source_representation_id=encoding_id,
        candidate_index=0,
        model_profile=MODEL_PROFILE,
        execution_profile=EXECUTION_PROFILE,
        tokenizer_fingerprint=tokenizer_fingerprint,
        generator_fingerprint=generator_fingerprint,
        display_policy=DISPLAY_POLICY_CUT_AT_EOS,
    )


def register(application, library: Library, engine: LiveEngine) -> None:
    @application.get("/api/v1/live/status")
    def live_status():
        return engine.state()

    @application.post("/api/v1/live/load")
    def live_load():
        engine.load()
        return {**engine.state(), **engine.layout()}

    @application.post("/api/v1/live/trace")
    def live_trace(body: TraceBody):
        return engine.trace(body.text)

    @application.post("/api/v1/live/vary")
    def live_vary(body: VaryBody):
        sampling = validate_sampling(body.temperature, body.top_k, body.top_p)
        return engine.vary(text=body.text, codes=body.codes, keep=body.keep, seed=body.seed, sampling=sampling, trim=body.trim)

    @application.post("/api/v1/live/keep")
    def live_keep(body: KeepVariationBody):
        project = library.require_active()
        parent = _source_revision(project, body.source_text)
        revision = _commit_variation(
            engine,
            project,
            parent=parent,
            source_codes=body.source_codes,
            padded=body.source_padded_token_ids,
            token_count=body.source_token_count,
            variation=body.variation,
            operation="live_vary",
            extra={},
        )
        return revision

    @application.post("/api/v1/live/keep-frame")
    def live_keep_frame(body: KeepFrameBody):
        project = library.require_active()
        parent = _source_revision(project, body.source_text)
        layout = engine.layout()
        tokenizer_fingerprint, generator_fingerprint = engine.fingerprints()
        run_id, _encoding_id = project.save_source_run(
            operation="live_trace",
            passage_revision_id=parent["id"],
            parameters=_parameters(engine, "live_trace", {"level": body.level, "raw_token_ids": body.raw_token_ids}),
            token_count=body.source_token_count,
            codes=body.source_codes,
            padded_token_ids=body.source_padded_token_ids,
            level_lengths=layout["levels"],
            codebook_sizes=layout["codebook_sizes"],
            model_profile=MODEL_PROFILE,
            execution_profile=EXECUTION_PROFILE,
            tokenizer_fingerprint=tokenizer_fingerprint,
            generator_fingerprint=generator_fingerprint,
            display_policy=DISPLAY_POLICY_CUT_AT_EOS,
        )
        return project.commit_text(
            body.text,
            "decoded",
            parent_id=parent["id"],
            relationship="decoded_from",
            run_id=run_id,
        )

    @application.post("/api/v1/live/keep-run")
    def live_keep_run(body: KeepRunBody):
        """Commit a Memory Weather run as a chain. Each telling's parent is the telling it was told from."""
        project = library.require_active()
        source = _source_revision(project, body.source_text)
        previous = source
        kept = []
        for index, step in enumerate(body.steps):
            if step.reset:
                previous = source
            if step.input_text != previous["text"]:
                # A telling that overflowed the window was cut at a token boundary before it was told again.
                # The cut is its own revision, so the chain shows it.
                cut = step.trimmed and step.input_text and previous["text"].startswith(step.input_text)
                if not cut:
                    raise ProjectError(
                        "STALE_RUN",
                        f"Telling {index + 1} was told from a passage that is not the one before it.",
                        {"step": index},
                        status=409,
                    )
                previous = project.commit_text(
                    step.input_text,
                    "edited",
                    parent_id=previous["id"],
                    relationship="trimmed_from",
                )
            revision = _commit_variation(
                engine,
                project,
                parent=previous,
                source_codes=step.input_codes,
                padded=step.input_padded_token_ids,
                token_count=step.input_token_count,
                variation=step.variation,
                operation="weather",
                extra={"step": index, "reset": step.reset, "steps": len(body.steps)},
            )
            kept.append({"step": index, "revision_id": revision["id"], "reset": step.reset})
            previous = revision
        return {"source_revision_id": source["id"], "tellings": kept}
