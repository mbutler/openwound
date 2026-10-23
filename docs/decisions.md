# Implementation decisions

Departures from `ncm_art_studio_openwound_v4_technical_spec.md`, upstream patches, dependency choices, and numerical tolerances. The specification's user-facing behavior, mathematical contracts, and provenance rules stay in force.

## 2026-10-23 Repository layout

The specification proposes an `ncm-art-studio/` project root and a file named `SPEC.md`. This repository is already the v4 working tree, and `legacy-versions/` stays beside the new code, so the application lives at the repository root. The specification keeps the filename it was given.

## 2026-10-23 Upstream pin

`vendor/ncm` is the pinned research source described in `vendor/UPSTREAM.md`. The adapter will call those modules. It will not import `scripts/eval_shard.py`, and it will not copy the public tokenizer wrapper's silent chunking of over-length text.

`idx_to_zhats` appends references to an accumulator that is modified in place. Reconstruction traces will store independent snapshots from `get_next_autoregressive_input`, as in the specification's reference algorithm, rather than patching that upstream function.

## 2026-10-23 Python

The specification asks for Python 3.12. This machine's system Python is 3.9.6. `conda create` stopped because the Anaconda channel terms of service have not been accepted, and those terms were not accepted on the artist's behalf. uv 0.13.5, installed under `~/.local/bin`, provides CPython 3.12.15. The environment lives in `.venv` and is not committed. `uv.lock` records the installed set.

Inference imports from the pinned quantizer require NumPy, so it is a direct dependency. Evaluation packages from the upstream requirements file, including `transformers`, `rouge_score`, and `sacrebleu`, are not installed.

The specification's preparation environment was PyTorch 2.14.1+cpu. This machine installed the macOS wheel `torch==2.14.1` and ran the fixture on CPU, FP32, eager mode. MPS was not used. On the random twelve-level fixture, the incremental full-grid latent matched `idx_to_z_q` exactly, so no floating-point tolerance was introduced.

The package version is `4.0.0.dev0`. In the specification, "version 1" means the first complete studio release. That release is still openwound v4.

Adapter error codes `INPUT_EMPTY`, `INVALID_SAMPLING`, and `PROFILE_MISMATCH` name failures the HTTP list had not yet spelled out. They use the same envelope idea: a code, a readable message, and details.

## 2026-10-23 Checkpoint smoke

`huggingface_hub` 2.3.0 downloaded the pinned TinyStories revision into `.model-cache`, which is not committed. SHA-256 values for `config.yaml` and `README.md` were computed from those files and then written into the profile. The four hashes supplied by the specification matched.

`python -m ncm_art.cli smoke` loaded the tokenizer checkpoint before constructing the generator, encoded "Anna borrowed a red kite from Ben." (8 BPE tokens), reconstructed all twelve levels, and branched at retained counts 0, 3, and 12. Two retained-3 variations used base seed 42 and candidate seed 1. Retaining all twelve levels made no generator calls and returned the source codes. The final reconstruction is not the source sentence. The outputs were not edited. The record is `fixtures/recorded/tinystories-cpu-fp32-eager-v1.json`.

## 2026-10-23 Writing desk

Each project is a directory under `.projects/`, which is not committed. Passage text is exact UTF-8 stored by SHA-256. SQLite holds revisions, provenance, the editor draft, and one job queue. The API process counts tokens with the released BPE files and does not load the generator. `python -m ncm_art.cli serve` spawns one worker with `spawn`, and that worker loads TinyStories.

A variation request may omit the seed. The server assigns an unsigned 32-bit seed when it stores the job, and that assigned seed is left out of the idempotency hash, so a retry of the same request returns the original job. An explicit seed is part of the hash. The desk accepts one through eight candidates and defaults to four. A finished or cancelled job does not write the editor draft or the selected passage. A later variation leaves the latest successful reconstruction available.

Sequences, works, grafting, and the other later milestones are absent from this desk. The automated desk tests run the random short model in-process. The browser check of the desk used the released checkpoint.

## 2026-10-23 Correspondences, increment A

`openwound-v4-correspondences-build-spec.md` is the next product contract. The writing-desk specification stays in force for exact text, inference, and provenance. Format version 2 is the first correspondences schema. Opening a format-1 project migrates it. The database schema version is the authority if the manifest was not replaced. The backup is `backups/schema-1/` inside the project, written with the SQLite backup API, and it includes the original manifest and text assets. A newer format is rejected and left unchanged. New tables use foreign keys. The original tables still do not.

A source encoding and a sampled hierarchy are different representation rows. The hierarchy does not store a token count or padded input ids. Variation jobs now keep the sampled codes, the level layout, and the raw decoded token ids. Re-encoding edited text inserts a new source encoding and does not update the earlier hierarchy. Variations saved before this change are marked unavailable for exact-hierarchy operations. Their displayed text hash and seed are kept when the old job recorded them. Codes that were never stored are not invented.

Reconstruction frames still use the existing one-based completed-level numbers. Retained counts stay 0 through 12. Changing the frame numbering would rewrite the desk's current level display.

The worker's ready file means the process is alive. TinyStories readiness is `worker.capabilities`. The checkpoint loads on the first reconstruct or variation job and is not required to read a project. The 128-token check runs only for those two operations, not as a gate on every queued job.

## 2026-10-23 Correspondences, increment B

Format 3 adds imported source versions, paragraph and window fragments, an FTS5 index, correspondences, and an embedding cache. Opening a format-1 project migrates through format 2. `backups/schema-1/` is still the pre-representation copy. `backups/schema-2/` is the copy taken before the corpus tables. Desk rows stay in the `desk` collection and are not encounter evidence.

Import accepts UTF-8 `.txt` and `.md`, or pasted text. File bytes are sent as base64 inside the JSON body so the server can reject invalid UTF-8 without a multipart parser. Identical bytes share an asset. The same filename is not an identity. A family link is stored only when the artist marks the import as a revision of an existing source.

Paragraphs split on blank lines. A model window is a child fragment with its own byte span, token count, and limit. The source asset is not shortened. Search indexes leaves: a window when one exists, otherwise the paragraph. Fragments are not passage revisions.

Lexical search quotes the artist's words before FTS5. The stopword policy is `english-function-words-v1`. Exact phrase offsets come from the source bytes. A case-folded hit is labeled folded. Semantic search is `minilm-l6-v2-cosine-low-overlap-v1`: cosine order inside a pool, then drop content-word overlap above 0.6 when that leaves any candidate. The two views are interleaved. They are not added into one score.

The embedding profile is `sentence-transformers/all-MiniLM-L6-v2` at `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, 384 dimensions, 256 tokens including special tokens, truncation disabled. `sentence-transformers` 6.2.0 is installed for that job. The API process does not load it. Checksums are in `model_profiles/minilm-l6-v2.json`. On this machine the model encoded "The lantern crossed the river.", "A lamp went over the water.", and "Birds slept in the eaves." The normalized scores against the river sentence were 0.4755 and 0.2403. A 402-token input was rejected and was not embedded. Another passage is a seeded shuffle with a saved cursor.

## 2026-10-23 Correspondences, increment C

Format 4 adds works, entries, influence versions, one active binding per work, operation previews, application receipts, events, held names, and protected ranges. Opening a format-1 project still migrates through formats 2 and 3. `backups/schema-3/` is the copy taken before the work tables. Candidate revisions use origin `candidate` and stay off the desk history. The desk draft and selected passage are not written by a transfer.

The operative preset is `withhold_marked_span_v1`. It replaces one marked span with the configured text, default `_____`, when a donor enters a work. A prose influence can be saved and cannot be bound. Preview writes the base and final revisions and does not create entries or held names. Adoption is one transaction: the receipt is checked before a stale-state rejection, then the entry, event, held name, and receipt are written together. A repeated request returns that receipt. The same request id with a different preview conflicts.

A protected insertion keeps the donor bytes exact. The name rule cannot change those bytes; the preview is refused and the work is left as it was. A later edit or return that would change a protected span is refused unless the artist releases that protection. A label whose bytes no longer match is marked released.

Returning a name uses the recorded placeholder, or a span the artist selects after the entry has changed. It does not search the work for the first copy of the placeholder. Removing an entry detaches its names. Unbinding affects the next transfer and leaves the earlier names held.

A host-and-donor operation records both passage parents. The provenance view lists every parent and, when the runs differ, each operation. A source donor is carried on the run because a provenance edge points at a passage revision.

## 2026-10-23 Correspondences, increment D

Format stays at 4. An omission repair is a job, `omit_repair`, and a preview, `omit_and_repair_v1`. The provider sees one declared window with the selected occurrence replaced by `_____`. Copies of that text elsewhere in the window stay. The server puts the replacement back into the full passage. A replacement longer than 512 UTF-8 bytes, malformed JSON, or a finish reason other than `stop` is refused after one retry. The name-withholding preset does not apply. Adoption is the existing commit, with the button “Adopt repair”.

The provider is an OpenAI-compatible chat endpoint. The address and model come from `{library}/instruction.json` or, when both are set, `NCM_ART_INSTRUCTION_URL` and `NCM_ART_INSTRUCTION_MODEL`. The API key is only `NCM_ART_INSTRUCTION_API_KEY`. A key written into the JSON file is refused. Status reports `instruction` as configured or unavailable and does not probe the network. No provider is configured on this machine, and nothing was listening on `127.0.0.1:1234`. The live repair is outstanding. A test server checked the request shape and that the saved job does not keep the key. That is not a model run.

A work exports as markdown or plain text, with an optional appendix. A project archive is `export.json`, `project.json`, `project.sqlite`, and the referenced assets. Embeddings are omitted. Queued and running jobs become interrupted and are not resumed. Import assigns a new project id, records `copied_from_project_id`, and does not call a provider or replay effects. The archive is rejected above 64MB, on a hash mismatch, on a path outside the archive, or on a format newer than 4.

## 2026-10-23 Correspondences, increment E

Format 5 adds `code_comparison` and `code_comparison_pair`. Opening a format-4 project migrates through the earlier formats and keeps `backups/schema-4/`. The metric is `slot-agreement-v1`: equal weight per code slot inside a retained prefix. Prefix 0 is refused. Matching tensor length does not make two hierarchies comparable; the tokenizer fingerprint, model profile, preprocessing policy, level lengths, and codebook sizes all have to match. Source encodings made before this increment are treated as `tinystories-bpe-pad-to-128-v1` when their model profile is TinyStories, which is the only encoder this application has used.

The baseline uses unpadded token length in bands of 16 (`unpadded-token-length-bands-16-v1`). Fewer than two other encodings leaves it unavailable. Two to seven are labeled sparse and the adjustment is still stored. When every slot in the prefix is unanimous, the adjustment is undefined and the raw agreement remains. Negative adjustments are kept. The snapshot records who was left out: the query, duplicate text, the same source family, other length bands, and incompatible profiles.

A latent graft rejects a repeated code position and a retained prefix that does not cover the edited level. If the selected codes already agree, nothing is generated. Otherwise the donor codes replace the base codes, the prefix is kept, and the levels after it are regenerated. The result is a new passage with both parents marked `grafted_from`. It is not written into the work. Corpus encodings use origin `corpus_encoding` and stay off the desk history. The regenerated passage is listed with the encodings under the title Latent graft.

One live comparison was recorded with the TinyStories checkpoint. “The lantern crossed the river.” is 8 tokens. “The lamp stayed on the table.” is 7 tokens. At the first three levels their slot agreement is 0.160. At the first level it is 0.000. The length band had only one other encoding, so the adjustment stayed unavailable and the raw figure was shown. A latent graft of that pair replaced 21 codes and regenerated a passage beginning “Once sandy a time, there was big big lake”. The work entry and the desk draft stayed as they were. The regenerated passage appears in the desk history. No instruction-provider repair was run.
