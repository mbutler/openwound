# Openwound v4 Correspondences and Executable Influences

Implementation specification for the coding agent  
23 October 2026 · Document version 1.0

Suggested repository location: `docs/openwound-v4-correspondences-build-spec.md`. Read alongside the original NCM technical specification; the precedence rules below define the next build.

## 1 Purpose and governing direction

Extend Openwound into a creative instrument in which Matthew Butler can encounter relationships among real source materials, investigate them through transformations, and give selected interpretations an executable role in a continuing work. The complete artistic cycle is encounter, interpretation, intervention, binding, consequence, and return. A successful session leaves both an artifact and a situation worth revisiting.

The next release must make that cycle usable with a small personal corpus and modest inference resources. It must support exact source handling, several ways of finding passages, a readable working table, literal grafts, marked omissions and proposed repairs, saved correspondences, one implemented influence rule, persistent consequences, and portable exports. Model training, a research collaborator, HPC access, a large vector database, and a general autonomous agent are not prerequisites.

The first implemented influence allows an artist to mark one name or other identifying span in a donor fragment. When an ordinary transfer is committed under that influence, the marked span is displaced from the receiving copy into the work's name index. The original source stays intact. The displaced element remains attached to the particular transfer that produced it and can subsequently be returned or used as a retrieval starting point. This is a concrete first mechanism for an interpretation acquiring consequences.

The larger vision includes grammatical and relational comparison, NCM representation comparison, protected host healing, richer influence rules, folklore studies, games whose rules emerge through reading, and dATAPLOT artifacts that accumulate actual and fictional histories. These capabilities are staged in Section 19. They must not become prerequisites for completing the first usable cycle.

This specification defines application behavior. It does not assign universal semantic meanings to NCM levels, treat retrieval scores as measures of occult significance, or make generated recurrence evidence of an independent supernatural cause. The artist may use occult language, cosmologies, and hyperstitional premises freely. The software preserves the actual materials, interpretations, interventions, and consequences so that the practice can investigate how significance develops.

### 1.1 Relationship to the existing specification

The repository already contains `ncm_art_studio_openwound_v4_technical_spec.md`. Keep it. This new document changes the next product milestone and adds requirements for corpus work, correspondences, and executable influences. It does not replace the earlier document's exact-text, inference, checkpoint, mathematical adapter, sampling, display, provenance, or data-integrity contracts unless a change is explicitly stated here.

The earlier release plan prioritized completing sequences, reveal puzzles, and The Last Account after the writing desk. For the next development cycle, the Correspondences release defined here takes priority. Those earlier forms remain later possibilities; they are not required to complete this release. Automated source segmentation and corpus retrieval move forward from the earlier exploratory phase because they are now essential to the central experience.

Use the repository's established Python, FastAPI, SQLite, PyTorch, React, TypeScript, and Vite structure. Preserve the working desk and legacy versions. Do not restart the application in another language or framework, replace the storage model wholesale, or create a parallel application.

When asked to implement this document, complete the requested release and its acceptance scenarios. The build increments in Section 17 are checkpoints, not automatic permission requests. Make routine implementation choices within these contracts, record material departures in `docs/decisions.md`, and report a concrete blocker when one prevents completion.

### 1.2 Intended artistic experience

Source passages should arrive before expansive explanations of what they supposedly mean. The artist must be able to notice a correspondence, keep it unresolved, reject it, revise its description, or explore an alternative reading. A useful encounter can be awkward, contradictory, sparse, or resistant to integration.

The application should preserve original voices and specific textual arrangements. It must not automatically polish every result, convert every juxtaposition into a coherent story, or supply dramatic narration when no event has occurred. A few changed words can be a finished artistic result.

Binding is an explicit act that gives a selected interpretation a defined role within a work. A named influence can exist without being bound. It acquires no unspecified powers because its description is persuasive. Its identity can develop through its actual applications, exceptions, failures, and consequences.

## 2 Baseline and compatibility

The implementation baseline reviewed for this document is the Openwound repository at commit `b5719b8bba8aeda4b2809611d9d93602e3ee8019`, following `2e0bdb7`. The first adds the writing desk and the second adds the project store and desk API. If implementation starts from a later commit, inspect the differences before changing anything and reconcile features already completed. The baseline is a source reference, not an instruction to reset a newer working tree. [R01–R04]

The pinned NCM upstream is `c70274273f489abc73832b2b98584a8483b6b203`. The existing TinyStories artifact revision and checksums remain authoritative in `model_profiles/tinystories-v1.json`. Preserve the upstream license and attribution. [R05–R07]

| Area | Baseline behavior | Required extension |
| --- | --- | --- |
| `frontend/src/App.tsx` | Writing desk, draft, reconstruction, variation, selection, comparison, notes, history | Add a Correspondences workspace and reusable components without breaking desk behavior |
| `storage/project.py` | Exact UTF-8 assets, revisions, ancestry, annotations, runs, encodings, jobs | Add migrations, corpus records, works, correspondences, influence state, and atomic application methods |
| `storage/library.py` | Project discovery and opening | Migrate supported existing projects on opening |
| `jobs/execute.py` | Reconstruct and variants from one passage | Dispatch additional typed operations and preserve sampled hierarchies |
| `jobs/worker.py` | Single worker eagerly loads TinyStories | Separate worker liveness from capability readiness and load models lazily |
| `api/app.py` | Active-project desk endpoints and TinyStories input gate | Add explicit project-scoped corpus, work, correspondence, preview, and commit contracts |
| `model_adapter/tinystories.py` | Encoding, reconstruction, branching, low-level donor-code replacement | Preserve current behavior; expose comparison and latent grafting in a later increment |

A background job must continue to leave the current draft and selected passage unchanged. Candidate completion is not adoption. Preserve existing idempotency behavior, including the distinction between an omitted seed assigned by the server and an explicitly supplied seed.

The current asset reader and writer preserve UTF-8 bytes without line-ending or Unicode normalization. Keep that property. The current migration method only creates missing tables, and reopening does not perform a real versioned upgrade. The new release must add migration-on-open before relying on new tables.

The current `passage_revision.source_id` is inherited through some derivations. It is a legacy source-family reference, not proof that the text is an exact quotation. New literal-source claims must use exact anchors as defined below.

The desk currently returns all passage revisions. Do not create a passage revision for every automatically indexed paragraph or add the entire archive to every desk response. Corpus records and bounded query endpoints should keep the existing desk responsive.

## 3 Release scope

Call the first complete milestone the **Correspondences release**. Its acceptance gate is a complete encounter-to-return cycle. The deterministic parts must remain usable when no generation model is running.

| Capability | Correspondences release | Following increments |
| --- | --- | --- |
| TXT and Markdown import, immutable source versions, context, exact anchors | Required | PDF and document extraction with explicit extraction provenance |
| Paragraph fragments and explicit model input windows | Required | Language-aware segmentation and specialist views |
| Lexical and one local semantic retrieval capability | Required | Grammatical, relational, phonological, and NCM views |
| Saved correspondences with passages, interpretations, and operations | Required | Collections, competing readings, richer comparisons |
| Ordered works with stable entry identities | Required | Branching works, game authoring, richer composition |
| Ordinary literal transfer and protected literal insertion | Required | Model-assisted protected host healing |
| Marked omission and multiple proposed repairs | Required with a configured instruction provider | Controlled inversion, register translation, variation families |
| One versioned influence preset for name displacement | Required | Obligations, preservation rules, retrieval constraints, rule composition |
| Preview, explicit adoption, held-name index, return, unbind, reopen | Required | Additional local actions and bounded autonomous schedules |
| Exact sampled NCM hierarchy preservation | Required maintenance change | Paired hierarchy comparison and latent graft UI |
| Portable project export and readable work export | Required | Self-contained playable and exhibition exports |
| New model training, multiuser service, general DSL editor | Out of scope | Separately justified work |

The initial influence editor exposes a name, an interpretation, linked correspondences, and the supported rule preset. It is not a freeform rule compiler. A prose rule that has no supported implementation can be saved as an idea, but cannot be presented as active.

An unavailable capability must be stated plainly. Import, browsing, exact transfer, binding, returning a name, and reopening must not fail because NCM weights or an instruction provider are absent. A missing embedding capability limits semantic encounters; it does not make the archive unavailable. The completed release must nevertheless demonstrate real semantic retrieval and one real omission-repair run in a documented supported configuration.

The first interface should expose only working features. Later operators belong in documentation until implemented.

## 4 The first complete session

The artist creates or opens a project and imports a small collection. Whole source texts remain readable. A paragraph or selected passage becomes the current point of inquiry. The application offers a small set of encounters from different retrieval views and shows each passage with its title and source context.

The artist selects two or more passages and saves a correspondence. A description can be as tentative as “the condition of crossing appears to change who owns the name.” This is the artist's interpretation. The correspondence records its materials and any operations used to investigate it.

The artist creates a work and transfers a selected fragment into it. A work begins as an ordered collection of entries, each containing a passage revision. This structure supports collage and persistent local consequences without requiring a rich text editor. The artist can edit an entry, change its order, and inspect its history.

The artist creates an influence from the correspondence and selects the name-displacement preset. The poetic title may be “What crosses must leave its name behind.” For an ordinary transfer, the artist marks one exact identifying span and previews the common literal candidate, the candidate after the influence, and the projected name-index addition. Nothing has yet changed in the live work.

Adopting the affected candidate creates a receiving entry, its passage revision, the held-name record, and a committed event together. The original source is unchanged. The artist can leave the application and reopen the same work with the unnamed passage, held name, active binding, and history restored.

Each held-name record can open its receiving entry, open its donor source, start an encounter search from its text, or return that particular name. Returning it creates another passage revision and event. Earlier grafts remain actionable; the most recent graft must not be the only one the interface can address.

This first cycle is sufficient to make interpretation operative. Its usefulness depends on the specificity of the material and the consequences, rather than the amount of generated prose.

## 5 Source identity and exact spans

### 5.1 Import and document versions

Initially accept UTF-8 `.txt` and `.md` files and pasted plain text. Read file bytes, decode strictly, and preserve the original UTF-8 content. Reject invalid UTF-8 with a useful explanation rather than silently guessing an encoding. Preserve BOM bytes when present, CRLF or LF line endings, whitespace, punctuation, and Unicode normalization form. Search representations may normalize text, but canonical assets may not.

An imported source version is immutable. Reimporting changed content creates a new version linked to the same document family when the artist identifies it as a revision. The same filename does not establish identity. Identical bytes may share an asset while retaining distinct source occurrences and metadata.

Retain title, optional author or creator, source URI, publication or creation date when supplied, language, edition or translator where relevant, and optional notes. Unknown metadata stays unknown. Store import time separately from any claimed source date.

The existing `source_document` table may represent an immutable source version. Add document-family or version metadata as needed without rewriting existing source identities. The precise physical schema may be adapted, provided the logical distinctions and migrations remain explicit.

A source fragment needs a stable identifier, its source-version identifier, exact byte range, text hash, and segmentation method/version. Do not materialize thousands of passage revisions during indexing. Create a linked passage revision when an operation actually uses a fragment.

### 5.2 Canonical anchor contract

Use half-open UTF-8 byte offsets throughout the persistent model and API. An anchor refers to an immutable text version, never an implicitly current editor buffer.

~~~json
{
  "owner_kind": "source_version",
  "owner_id": "source-version-id",
  "text_sha256": "sha256-of-the-entire-referenced-text",
  "start_byte": 0,
  "end_byte": 4,
  "slice_sha256": "sha256-of-the-selected-bytes"
}
~~~

An anchor may instead name a `passage_revision`. In that case, `owner_id` identifies that immutable revision. The example values illustrate shape; real hashes must be computed.

The backend validates the owner, whole-text hash, range bounds, UTF-8 boundaries, and slice hash. If the client sends selected text, compare it with the exact decoded slice. Never find an occurrence by selecting the first matching string. Repeated words at different positions are distinct occurrences.

~~~python
def validate_span(raw: bytes, start: int, end: int, expected: str) -> bytes:
    if not 0 <= start <= end <= len(raw):
        raise InvalidSpan("Range outside immutable text")
    raw[:start].decode("utf-8", errors="strict")
    raw[:end].decode("utf-8", errors="strict")
    selected = raw[start:end]
    if selected.decode("utf-8", errors="strict") != expected:
        raise InvalidSpan("Selected text does not match this revision")
    return selected
~~~

Hash validation and owner resolution surround this illustrative helper. A marked name must be nonempty.

Browser selections use UTF-16 positions. Convert an exact source-view selection by UTF-8 encoding the prefixes ending at each selected boundary. Reject boundaries that split a surrogate pair before using `TextEncoder`. Do not apply JavaScript offsets directly to Python strings or UTF-8 bytes. The source viewer must preserve a mapping to the canonical text when it highlights or segments passages.

Selecting part of a combining sequence is technically a valid code-point boundary but may be awkward to read. The UI may prefer grapheme boundaries; backend validation remains defined in bytes.

### 5.3 Fragments and model windows

Start with paragraph fragments, preserving exact source locations. A long paragraph remains intact. Individual models may require smaller input windows, which are separately identified views into that fragment.

Every model input records its exact anchor or composed input, preprocessing policy, token count, model context limit, and whether special tokens are included. Reject overlength model input or create explicitly recorded subwindows. Do not silently truncate. A preview of the actual model input must be available.

The initial windowing implementation may select sentence groups, then split oversized sentences at whitespace boundaries, with a code-point fallback for unusually long tokens. Use the model tokenizer to validate the final budget. Record the segmentation version. Search results must identify the particular analyzed window and allow navigation to the full paragraph and document.

A 128-token NCM limit applies to its selected input. It is not an archive limit and must not block import of the white paper, a folktale, or a long work.

### 5.4 Source material and work made here

Default encounter search to imported source material. Generated, transformed, and manually composed works remain available in a separate selectable collection. Including them in search is an explicit choice, not a silent expansion of the evidence pool.

Store actual derivation for every generated or transformed artifact. Preserve known source families and duplicate occurrences. If an exported Openwound artifact is reimported with its manifest, retain its known ancestry. If plain text lacks that metadata, do not invent an origin; exact-duplicate detection can still flag an existing match.

The artist may deliberately feed the work back into its corpus. Label that collection choice and retain the history. A descendant of an influence's application must not silently become independent evidence that the influence predated its application.

## 6 Encounter retrieval

### 6.1 A common result contract

A retrieval run takes an immutable query span or explicit query text, a corpus snapshot, collection filters, enabled views, bounded result counts, and optional exploration seed. Save the recipe and returned candidate identifiers when an encounter is saved to a correspondence.

Each result includes its source anchor, source metadata, retrieval view, metric version, relevant score or matched spans, and a concise reason such as “shared phrase” or “semantic proximity.” Put detailed model and index metadata in “Why this appeared.”

Do not combine raw lexical, embedding, grammatical, and NCM scores into a single significance score. Interleave the enabled result lists deterministically, deduplicate displayed candidates, and preserve every applicable reason. A starting display can show six candidates, divided across available views; this is a configurable presentation default, not a statistical claim.

Exclude the query itself, exact-text duplicates, and directly overlapping neighbors from the default encounter set. Group duplicate occurrences with their sources available. Prefer different source documents where possible. Let the artist include same-document and same-family material deliberately.

A result is a candidate for reading, not a verified interpretation. Allow empty or unpromising results without inventing an explanation.

### 6.2 Literal retrieval

Use SQLite FTS5 for the initial lexical index. Keep the indexed search text separate from canonical bytes. Parameterize SQL, and quote or parse artist-entered search terms rather than treating them as arbitrary FTS syntax. Preserve exact phrase matches and their source offsets when displaying a literal-echo reason. [R12]

A useful initial recipe can combine selected content words with exact multiword phrases and prefer less common shared phrases. Record its stopword and tokenization policy. Document frequency may be shown in inspection, but rarity is not a probability of significance.

Simple token overlap can support diversity selection. Any normalized or stemmed match must be labeled accordingly; an exact quotation must refer to exact source bytes.

### 6.3 Semantic retrieval

Use one pinned local sentence-embedding model initially. The default baseline is `sentence-transformers/all-MiniLM-L6-v2` at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Its published model card describes a 384-dimensional English sentence/short-paragraph encoder and a default truncation limit of 256 word pieces. For this profile, validate the final tokenizer input length, including added special tokens, against the verified maximum sequence length of 256. Perform the preflight with truncation disabled. Create recorded subwindows or reject overlength input before embedding; do not rely on automatic truncation. This is a practical baseline, not a claim that it is the strongest available model. [R18]

Store the model identifier, immutable revision, tokenizer revision, effective context limit, embedding dimension, normalization, language coverage, and preprocessing recipe in an explicit profile. Download the pinned required configuration, tokenizer, pooling, and safetensors assets; record their checksums. A deliberate replacement model gets a new profile and cache namespace. Do not use an unpinned main branch or silently switch profiles.

Cache embeddings by exact model-input hash and complete embedding-profile fingerprint. At personal-corpus scale, a normalized in-memory matrix backed by cached arrays is sufficient. A vector database is not required. For normalized query vector `q` and passage vector `v_i`, rank by `q · v_i`. Resolve ties with a stable fragment/window identifier. Reject nonfinite or zero-norm vectors.

Sentence Transformers provides the underlying semantic-search pattern. Select a profile appropriate to passage-to-passage comparison, and handle a short query differently if the model specifies query/document encoders or prompts. [R13]

Exact search over a few thousand windows is the initial engineering target, not a promised performance benchmark. Index incrementally, batch encoding, and report progress. Cache invalidation must follow profile and input changes.

A “different words, related meaning” view may first retrieve plausible semantic candidates and then favor lower lexical overlap within that set. Minimizing lexical overlap alone is not a meaningful discovery procedure. Such views need a named recipe and inspectable settings.

### 6.4 Exploratory selection and alternative readings

Provide a simple way to begin from an imported fragment that the artist has not recently viewed. A seeded shuffle of eligible fragment IDs, with a saved session cursor, is sufficient. Do not describe this as a prediction about what the artist needs to see.

The initial interface may offer “Another encounter” without learning a hidden preference model from every click. Saved and rejected correspondences can support explicit filters. Later preference learning requires its own visible behavior and evaluation.

A later relational view can propose actor, action, recipient, object, condition, negation, and consequence fields, each tied to supporting source spans. All fields are optional, and the model can abstain. Validating a quote establishes that it exists; it does not validate the relationship claimed about it.

## 7 Correspondences and works

### 7.1 Correspondence records

A correspondence groups two or more exact source or passage references, an optional title, the artist's current interpretation, saved retrieval reasons, and relevant operation results. It can be open, retained, set aside, or rejected. These dispositions describe the artist's activity; they are not truth labels.

Interpretation edits create a revision or retain a previous-version history. Record whether a statement was written by the artist, proposed by a model, or adapted from a model proposal. Do not silently turn a model description into the artist's accepted interpretation.

Correspondences and influence definitions may link to one another, but an interpretive relation is separate from textual ancestry. Never add a `generated_from` edge merely because two passages resemble each other.

### 7.2 Ordered works

A work has a stable identity, title, ordered entries, active binding information, and a monotonically increasing `state_version`. Each entry has a stable `entry_id` and points to an immutable `passage_revision_id`. Changing an entry creates or selects a revision and increments work state through a committed action.

This ordered-entry design is the first composition model. Ordinary transfer inserts an entry at a chosen position. Editing, reordering, and removing entries are explicit work actions. Avoid implementing a new rich text editor or a general block-document platform for this release.

Store entry order as a small ordered list or transactional integer positions. Preserve old/new revision identities and order changes in history. Removing an entry detaches its held-name targets; it does not erase its revisions, events, or held-name records.

Use separate work-entry drafts or a draft keyed by work and entry. The existing desk's single draft must not be silently repurposed and lost. Saving a draft is not committing a rule application.

### 7.3 Reading and provenance

Keep source text and work text readable at comfortable line lengths. The primary workspace should show a selected source encounter, the work or selected work entry, and the current operation. At narrow widths, stack these views.

Context, comparisons, explanations, and history should open on demand. The default experience must not require the artist to complete a research form before making a graft.

The provenance inspector must support multiple actual parents. For a host-and-donor operation, both contributions matter. The baseline history endpoint uses the first parent's run; extend it so it can show all relevant inputs and runs without implying a single-parent history.

A correspondence can be shown next to an artifact as interpretation. Its presence must not imply that the interpretation caused the artifact unless an operation actually used it.

## 8 Operations and candidates

### 8.1 Shared operation contract

An operation is a versioned procedure applied to immutable inputs. Its record contains an operation name and version, input references and hashes, parameters, provider/profile information when applicable, exact provider request, raw response or raw model output, validated candidate outputs, and derivation links.

A candidate is an inspectable result, not a committed change to a work. Candidate generation can persist assets, run metadata, and proposed revisions. It cannot create live held names, obligations, or other operative state.

The artist can keep, reject, edit, or adopt a candidate. Editing a candidate creates a derivative revision and invalidates any preview whose effects depended on the earlier bytes. Job completion must not move selection or overwrite drafts.

Every preview has a typed adoption destination: `insert_entry(position)` or `replace_entry(entry_id, expected_revision_id)`, within its identified work. Ordinary transfer inserts. A host operation on a selected work entry normally replaces that entry's current revision only on explicit adoption and preserves its stable entry ID. A source- or desk-based candidate can be inserted as a new entry. Show the destination action in the preview and capture it in the immutable request. Never infer it later from the currently selected UI entry.

### 8.2 Ordinary transfer

`transfer_fragment_v1` takes one exact donor span and a destination work position. Its base candidate is an exact copy of the selected donor bytes. Without an applied influence, committing it inserts an entry whose text matches those bytes.

When the destination work has an active compatible binding, the base candidate is transformed according to the rule's supported effects. Binding or unbinding is the explicit choice; a per-operation checkbox cannot silently bypass the active binding. Preserve the base candidate, the applied effect, and the final candidate as distinct records or stages. Do not call the final text an exact donor copy if a rule changed it.

This operation does not need an LLM. The first release must let an artist perform it immediately after import.

### 8.3 Protected literal graft

`protected_insert_v1` takes a host passage revision, an exact insertion boundary, and a donor span. The server assembles `host_prefix + donor + host_suffix` without changing any component. If separator text is desired, it is an explicit parameter and appears in the preview.

The inserted donor receives a protected-range record attached to that candidate and resulting entry revision. Its exact bytes must survive this operation and subsequent operations while the protection remains active.

Carry forward and rebase unaffected protected ranges through validated structured edits. Repair, healing, returning a name, and other operations that would change protected bytes must report a conflict unless the artist explicitly releases that protection first. Free-text editing must either preserve protected bytes and establish their new unambiguous anchors, or explicitly release the affected protections. The first implementation may require explicit release before editing an entry containing protection. Never retain a protection label whose byte guarantee no longer holds.

A name-displacement effect that overlaps the protected donor must return `RULE_CONFLICT`. The artist may choose an ordinary transfer, explicitly unbind the influence, or use a work with a different binding. Creating a derivative donor does not by itself exempt a later transfer from an active rule. The application must never silently relax protection to make an operation succeed.

### 8.4 Marked omission and proposed repair

`omit_and_repair_v1` takes a passage revision, one exact nonempty omission span, an explicitly selected context window, a provider profile, and a bounded candidate count. Default to three repair candidates and allow one through eight, matching the scale of current variation controls.

The declared context window must wholly contain the omission span. Store the omitted occurrence in the operation record for comparison, but remove that occurrence from the provider request. The provider sees only the declared window with a gap marker. The server assembles each replacement into the full immutable passage, preserving all bytes outside the omitted span, including material outside the provider's context window.

Do not add the complete original passage, source filename, annotations, or a hidden copy of the answer elsewhere in the prompt. Metadata that intentionally supplies a clue must be an explicit recorded setting. Identical text already present elsewhere in the declared retained context remains visible. Withholding an occurrence does not authorize additional redactions of every matching string.

Ask the model for the missing span only, using a small structured output schema. Assemble each repair between the exact retained prefix and suffix on the server. This preserves the material that was not selected for change.

~~~json
{
  "replacement_text": "The proposed text for the marked gap."
}
~~~

Validate the response type, length budget, and termination status. Save the actual request and response. Schema-valid text can still be an unhelpful repair; keep that artistic judgment separate.

The provider may know a published passage from training, and repeated repairs may reflect prompt constraints or model habits. The application records what was supplied and what returned without labeling the result proof of memory located throughout the text.

Adopting a repair into a work creates a new entry revision through the same explicit commit path used by other candidates. The name-displacement preset does not apply to repair jobs; its trigger is a selected donor entering the work, as defined in Section 9.

### 8.5 Protected host healing

Implement `heal_around_protected_graft_v1` after the core cycle works. The artist chooses a host region that may be rewritten and a donor span that must remain exact. Request only the editable surroundings from the model:

~~~json
{
  "before": "New editable material before the donor.",
  "after": "New editable material after the donor."
}
~~~

The server inserts the protected donor between these fields and retains any unchanged outer host material. This design enforces exact preservation by construction. A model request to return the entire composite and copy the donor faithfully is insufficient.

Additional checks should reject a response that violates the declared output budget or duplicates a protected block in a way the operation disallows. Retain failed attempts as failed operations, not successful protected grafts.

The artist can keep an awkward seam. Do not automatically smooth it through an additional unrecorded generation.

## 9 Influence definitions and binding

### 9.1 Definition and scope

An influence has an identity, a versioned name and interpretation, optional linked correspondences, a supported rule template, and validated parameters. A binding activates one exact influence version within one work. The initial release supports one active binding per work. Multiple unbound influences may be saved.

Editing an influence creates a new version. Existing bindings and past events continue to reference their original version until the artist explicitly replaces the binding. Binding, replacing a binding, and unbinding are work-state changes with recorded events.

The initial preset applies when an operation brings a selected donor fragment into a work. It does not apply recursively to its own effects, ordinary entry edits, omission repairs, or returning a name. The operation preview always shows whether the active binding will apply.

~~~json
{
  "schema_version": 1,
  "template": "withhold_marked_span_v1",
  "name": "What crosses must leave its name behind.",
  "interpretation": "Identity is displaced when this material enters the work.",
  "trigger": "donor_enters_work",
  "parameters": {
    "mark_role": "name",
    "replacement_text": "_____"
  }
}
~~~

This is a typed configuration for one implemented handler. It is not executable code. Validate keys, supported template/version, and parameter types. Do not accept arbitrary Python, JavaScript, SQL, templating expressions, network actions, or model-proposed handlers.

A new prose interpretation can be saved without a supported operative template. The UI must show that it is unbound rather than claiming it controls the work.

### 9.2 Marking and preconditions

The artist marks one exact, nonempty span inside the selected donor. The label “name” describes its artistic role; automatic named-entity recognition is not required. A name may be several words or another identifying expression.

Only the marked occurrence is affected. If the same text appears elsewhere in the donor, those occurrences remain unchanged. Validate that the mark belongs to the exact donor version and lies wholly within the transferred span.

A bound transfer without a required mark returns `MARK_REQUIRED`. An effect overlapping a protected range returns `RULE_CONFLICT`. A stale or invalid anchor returns `SPAN_MISMATCH`. Do not guess a name, silently skip the rule, or override the protection.

The active preset applies to ordinary transfer and is checked when a protected insertion brings in a donor. Because the selected donor is protected in the latter operation, a proposed overlapping displacement conflicts. The artist can use ordinary transfer, explicitly unbind for future actions, or use a work with a different binding. The conflict is a meaningful consequence of the selected constraints.

### 9.3 Preview and comparison

A preview captures exact input revisions and hashes, the operation recipe, the destination work and position, the work's expected state version, the binding ID and immutable influence version, and the marked occurrence.

Produce the base candidate once. Compute both the unbound display and the bound display from that same candidate. For a model-assisted operation, generate or select one candidate first, then compare rule effects on it. Independently generated passages do not isolate the effect of a rule even when their seed fields match.

Show the changed text and projected effects, including the specific name-index addition. No live work entries or held-name records are created by previewing. Keeping a preview in history is permitted, provided its proposed effects are clearly distinct from committed events. With an active binding, the unbound pane is a counterfactual comparison; adopting that unbound outcome requires explicitly unbinding and preparing a fresh preview.

If the work, binding, candidate bytes, or selected destination changes, the existing preview is stale. Keep it available for inspection, but require a refreshed preview before applying it to the current work. Never silently recompute and adopt a different result.

### 9.4 Committing the first rule

The committed ordinary transfer copies the donor into a new receiving entry, replaces the marked occurrence in that new copy with the configured placeholder, and creates one held-name record. These changes are a single application transaction.

The held-name record identifies the exact marked donor occurrence, its text, the receiving work and entry, the resulting revision and placeholder span, the influence version, and the application event. Two held instances of “Mara” are distinct records even if their text and source bytes happen to match.

Retain the literal base candidate and final revision so the artist can inspect what the rule changed. The existing source asset, donor revision, and earlier work states remain intact.

### 9.5 Returning, detaching, and unbinding

Every held name has its own return action. Returning one replaces the validated placeholder span, or an explicitly retargeted current byte range, with its saved bytes. An explicitly selected zero-length range may be used when the artist intends insertion. The return creates a new receiving revision and event and marks only that held-name ID returned. The earlier displaced version remains in history.

A return must validate the current receiving entry revision and target span. Never search the work for the first matching placeholder. If an entry was edited and the target cannot be established, keep the name held and show: “The receiving passage has changed since this name was taken.” The artist can select the current target explicitly and preview the return.

For ordinary free-text entry edits, the first implementation may mark all held-name targets in that entry unresolved. Operations already expressed as validated byte-range edits may rebase unaffected anchors. Do not infer exact identity from an ambiguous text diff.

Removing an entry marks its held-name targets detached. Preserve the entry's history and provide a way to restore it before returning a name. Restore and retarget actions are explicit events; removal must not silently release or discard held names.

Unbinding changes future operations. It does not restore names automatically or erase events. The name index remains usable after unbinding.

### 9.6 Consequences at the next session

On reopening, show actual unfinished state: held names, detached targets, uncommitted saved candidates, and open correspondences. A held name can become the query for a new encounter, with its source and receiving work immediately available.

The initial rule does not secretly change ranking weights. Any later influence that constrains retrieval must record the resulting collection filter or ranking recipe. Interpretations should acquire specific observable powers, not an undocumented global effect.

## 10 Data model and persistence

### 10.1 Logical records

Reuse `passage_revision` for immutable text outputs and `provenance_edge` for actual text derivation. Reuse runs and jobs where their contracts fit. Add the following logical records; physical tables may be combined when doing so does not blur identity or transactional behavior.

| Record | Essential content |
| --- | --- |
| Source version and fragment | Documentary identity, exact text hash, metadata, immutable byte anchors, segmentation version |
| Corpus/index snapshot | Included source versions, collection rules, preprocessing/profile fingerprints, build status |
| Correspondence | Referenced passages, interpretation versions, producer, disposition, retrieval and operation references |
| Work and work entry | Stable work/entry IDs, current entry revision IDs, order, state version, active binding |
| Influence version and binding | Interpretation, supported preset/version, parameters, work scope, activation history |
| Operation candidate or preview | Immutable inputs, base/final output refs, proposed effects, captured state and binding |
| Work event and application receipt | Action identity, request hash, old/new references, effects, state versions, committed result |
| Held name | Application identity, marked donor, recipient entry and target, held/returned state, target resolution |
| Model representation | Source encoding or sampled hierarchy, model fingerprints, arrays, raw decode, derivation |
| Embedding cache | Exact input/window identity, profile fingerprint, vector asset, dimensions and normalization |

This is a small application model, not a request for a generic event-sourcing platform or graph database. SQLite rows can hold current state while committed events preserve the history needed to explain and reconstruct work changes.

An interpretation edge never substitutes for a derivation edge. A fictional ancestor can later have an earlier fictional date while its actual production edge points from the text used to generate it. Preserve both relations separately.

### 10.2 Versioned migration

Add an ordered, versioned migration path invoked when opening existing projects. Check supported manifest and database versions before starting the worker on that project. Reject a newer unsupported format with a useful message; do not attempt an automatic downgrade.

Back up a project before its first migration to the new schema. Use a WAL-aware SQLite backup method, such as the database backup API, rather than copying only `project.sqlite` while committed data may remain in its WAL. Preserve content-addressed assets and the original manifest with the backup.

Run each schema migration transactionally. Use the database schema version as the recovery authority if the process stops after the database commit but before replacing the manifest. Replace the manifest atomically and reconcile a known interrupted version pair on the next open.

The current code enables foreign keys but its original tables declare none. New relationships should use actual foreign keys where practical. Validate legacy references during migration without inventing missing ancestry or deleting old rows to satisfy constraints.

A migration fixture must preserve the existing draft, selected revision, text bytes, annotations, runs, completed jobs, and old model records. Do not treat a fresh empty project as sufficient migration verification.

### 10.3 Assets and arrays

Write new content-addressed assets through a temporary file on the same filesystem, finalize atomically, and only then commit database references. Verify an existing asset when an integrity problem is suspected. A failed database transaction may leave an unreferenced asset; a committed row must never point at a partial file.

Continue exact UTF-8 text storage. Store arrays as validated JSON or a non-pickled numeric format with shape, dtype, and hash metadata. Imported projects must never load arbitrary pickle or executable model files.

Caches are rebuildable and can be excluded from a minimal export. Source assets, committed outputs, actual operation inputs, held-name values, events, and saved model representations are not disposable caches.

### 10.4 One atomic application

The current convenience methods open separate SQLite connections. Calling `commit_text`, `record_run`, and a new name-index method sequentially will not make a bound transfer atomic. Add lower-level helpers that accept an existing transaction connection, retaining public convenience methods for existing callers.

A commit follows this contract:

~~~python
def commit_prepared_application(project, request):
    receipt = project.find_receipt(request.client_request_id)
    if receipt is not None:
        require_same_request_hash(receipt, request)
        return receipt.result

    prepared = resolve_and_validate_immutable_preview(project, request)
    finalize_required_assets(prepared)  # No model calls inside the transaction.

    with project.immediate_transaction() as tx:
        receipt = find_receipt(tx, request.client_request_id)
        if receipt is not None:
            require_same_request_hash(receipt, request)
            return receipt.result

        require_expected_work_state(tx, prepared)
        require_current_binding_matches(tx, prepared)
        require_inputs_and_protected_spans_match(prepared)

        result = insert_revision_entry_event_and_effects(tx, prepared)
        advance_work_state(tx, prepared.work_id)
        store_application_receipt(tx, request, result)
        return result
~~~

This is an application contract, not drop-in code. All inserts and state updates share one transaction. The server derives effects from the validated preset and captured inputs; it does not trust a client-supplied list of state mutations.

Check a matching committed receipt before rejecting a retry on the basis of a now-advanced work version. A retry of the successful request must return the original result.

The receipt must survive a crash after the transaction commits but before the job or HTTP response reports success. On retry, it prevents a second receiving entry or held-name record.

### 10.5 Idempotency and state conflicts

Scope `client_request_id` to the project. The same ID and same canonical request return the same committed result. The same ID with a changed request returns `409 IDEMPOTENCY_CONFLICT`. Compute its hash from the stable submitted request, route target, and immutable preview/candidate identifiers; never rebuild that hash from current work state, current binding state, or a newly assigned server seed.

The resolved request includes the operation version, immutable inputs and hashes, candidate ID, destination work and position, expected work state, binding/influence version, and marked occurrence. Save the server-resolved snapshot rather than relying on a currently selected UI passage.

Use optimistic work-state checks and `BEGIN IMMEDIATE` for the short write transaction. A changed head, entry order, binding, or relevant target yields `409 STALE_PREVIEW` or `STALE_TARGET`. Preserve the artist's current work and the earlier candidate.

## 11 Jobs and provider capabilities

Keep one worker and the current limit of one queued or running model/index job per project initially. Keep project switching guarded while an active project job is executing. These constraints are adequate for the first release and reduce resource and state complexity.

Separate worker liveness from readiness of each capability. The worker can be alive while NCM weights are missing or an instruction server is offline. Load model bundles lazily and release or reuse them deliberately. Source browsing, deterministic previews, commits, and reopening should not require loading a model.

Move the TinyStories 128-token validation out of generic queueing. Each operation validates the input limits of the particular capability it invokes. Corpus import and rule application do not use the NCM gate.

Use explicit capability interfaces for embedding, instruction generation, NCM encoding/reconstruction, and NCM generation. Implement only the providers needed for the release. An instruction provider should support a configured local endpoint, including LM Studio's compatible API when the selected model supports the requested schema. Do not pin an unverified “best” model in application logic. [R14]

Record endpoint kind, actual model identifier/revision when available, context configuration, prompt/template version, generation parameters, and actual outputs. Store credentials outside projects and exports. A remote provider is used only when deliberately configured; do not silently send a local corpus elsewhere when a local service fails.

Structured output constrains the response shape, not the truth or literary quality of its contents. Validate it, allow one bounded repair/retry for malformed output if configured, and preserve the attempted responses. Do not loop indefinitely to manufacture a successful result.

Cancellation is cooperative. Before a candidate or application transaction commits, cancellation can prevent it. After a transaction commits, its artifact and effects remain committed. Cancelled jobs retain completed candidate records without adopting them.

Use conditional job transitions or transactions to resolve queued-cancellation versus worker-claim races. A state read followed by an unconditional later update is insufficient.

Report actual stages such as indexing document 4, encoding window 20, or preparing repair 2. Avoid invented percentages of semantic progress. A source query should remain cancellable without making the current work inaccessible.

## 12 NCM representation preservation and comparison

### 12.1 Preserve what was actually generated

The baseline variation executor decodes `branched.codes` and persists displayed text and sampling metadata, but discards the exact sampled hierarchy and raw decoded IDs. Fix this during the first release. [R03]

Introduce an explicit representation kind. A source encoding has source/input text, token count, padded input token IDs, and encoded codes. A sampled hierarchy has generated codes and their generation recipe; it does not have a fabricated source-token count or padded input sequence.

Store the full code sequence, level lengths, codebook sizes, tokenizer and generator fingerprints as applicable, execution profile, raw decoded token IDs, display policy, displayed-text hash, run/candidate identity, retained-level count, sampling recipe, seed, and source representation references.

The current `encoding` table requires fields appropriate to source encoding. Do not populate those fields with invented values to squeeze a sampled hierarchy into it. Add a representation table or an explicit typed extension and migrate old encodings faithfully.

Re-encoding a generated or edited displayed passage creates a new representation. It never overwrites the sampled hierarchy that produced the earlier text. Old candidates for which codes were not saved must be marked unavailable for exact-hierarchy operations. A fresh re-encoding can be offered as a different operation.

### 12.2 Inherited model contract

TinyStories has 128 BPE text positions, latent width 384, twelve levels with lengths `[1, 8, 16, 24, 32, 40, 52, 64, 76, 92, 108, 128]`, and 4096 categories at each level. There are 641 codes in the complete hierarchy. Retaining three levels fixes 25 codes. These quantities come from the pinned profile. [R05]

The source is encoded by the VQ tokenizer. The released unconditional generator's raw-token prefix is one EOS token; it is not an instruction prompt containing the source passage. Retaining a code prefix fixes those categories without guaranteeing preservation of a particular word, fact, or interpretation.

For a level's categorical codes `c_l`, the decoder-side cumulative latent uses the upstream codebook, upsampling, and configured residual transform. Conceptually:

\[
\widehat z^{(m)}=\sum_{\ell=0}^{m-1} R_\ell(U_\ell(E_\ell(c_\ell))).
\]

Use the actual upstream methods and the existing verified adapter rather than reimplementing this expression from the notation. The earlier specification's Sections 10–13 retain authority over shapes, loading, sampling, and reference algorithms. [R06–R09]

The reconstruction trace must snapshot the cumulative latent after each level. Preserve the current independent snapshots from `get_next_autoregressive_input`. Upstream `idx_to_zhats` can retain references to an accumulator modified by later levels; those references are not a valid saved trace.

Use completed-level counts from 0 through 12 for prefix retention and zero-based indices for code locations. Translate to one-based labels only at the UI boundary.

### 12.3 Paired corpus comparison

Implement NCM comparison after the core Correspondences release. Cache encodings for explicitly selected, eligible source windows. Compare within the same tokenizer/checkpoint fingerprint, preprocessing policy, and level layout. Equal tensor dimensions do not establish compatibility.

For a retained prefix of `m` completed levels, define slot agreement:

\[
C_m=\sum_{\ell=0}^{m-1}n_\ell,\qquad
A_m(x,y)=\frac{1}{C_m}\sum_{\ell=0}^{m-1}
\sum_{j=1}^{n_\ell}\mathbf{1}[c_{\ell,j}(x)=c_{\ell,j}(y)].
\]

The measure is undefined at `m = 0`. Disable comparison at that setting. It weights slots equally, so longer levels contribute more. Equal weighting by level would be a different metric and must have a different identifier.

Code IDs are categorical. Do not compute arithmetic distances between their integer labels. A future latent-vector metric must identify the actual vectors, normalization, and profile used; it cannot be substituted silently for categorical agreement.

Query a cached code matrix against one selected hierarchy. A full all-pairs graph is unnecessary. Decode reconstruction traces only for the selected pair or a small shortlist. Start with a few coarse prefix counts, such as 1, 2, and 3, and let the artist inspect additional levels.

Show the original passages, their input lengths, the selected prefix, the raw agreement, and paired partial reconstructions. Keep the original source context available while following the levels.

### 12.4 Length effects and a common-code baseline

Padding can influence the entire encoded representation. Do not mask supposed “latent padding positions” by treating coarse code indices as direct text-token positions.

For an initial diagnostic, compare within recorded unpadded-token-length strata. Sixteen-token bands are a reasonable TinyStories implementation default, subject to artistic evaluation; they are not a guarantee that length effects disappear. Save the band definition and corpus snapshot with the result.

Common codes can produce high raw agreement. For a stratum containing `N` eligible fragments and count `n_ljk` for category `k` at a position, expected agreement between two distinct sampled fragments can be estimated as:

\[
b_{\ell,j}=
\frac{\sum_k n_{\ell,j,k}(n_{\ell,j,k}-1)}{N(N-1)},\qquad N\ge2.
\]

Average over the selected prefix:

\[
B_m=\frac{1}{C_m}\sum_{\ell<m}\sum_j b_{\ell,j}.
\]

The optional adjustment

\[
A_m^\ast=\frac{A_m-B_m}{1-B_m}
\]

is undefined when `B_m = 1`. Preserve negative values when defined. This is a diagnostic agreement adjustment, not a probability, significance test, or calibrated measure of shared meaning.

Estimate statistics from a recorded, deduplicated snapshot, retaining the count and known family exclusions. At very small sample sizes, show the raw comparison and identify the baseline as sparse or unavailable. Do not manufacture a precise confidence claim.

Exact shared prefixes necessarily produce identical partial reconstructions under the same decoder. That equality is a consequence of the representation, not a second independent observation of common meaning. A coarse match may arise from a useful shared structure, frequent categories, padding, or poor representation of unfamiliar material.

### 12.5 Latent grafting

The existing `apply_graft` replaces donor codes at corresponding levels and positions. Retain its requirement that `retained_level_count` exceed every modified level index, so modified codes remain within the preserved prefix. Require matching representation fingerprints. Clone source tensors before changing them. [R08]

Deduplicate selected locations or reject duplicates. Record every old and replacement code. If all selected codes already agree, return a no-change result rather than implying an effective intervention.

Save the ungrafted hierarchy, modified hierarchy, substitutions, retained count, regeneration recipe, and resulting raw IDs. A shared generation seed helps comparison but does not guarantee semantically matched samples after conditioning changes.

Call this operation “Latent graft” and literal insertion “Text graft” or “Transfer.” A latent code replacement does not promise to transplant a particular phrase, character, or semantic organ.

### 12.6 Broader tokenizer profiles

An OpenWebText tokenizer-only profile is a later extension if TinyStories comparisons prove unproductive. Its released configuration uses 1,024 text positions and 32 levels. The corresponding generator has architectural differences, including post-upsampling convolution, which the current TinyStories generator adapter rejects. [R10]

Add a separate profile and verified loading/reconstruction path. Do not remove compatibility checks from TinyStories or assume changing a model name is sufficient. Cache representations separately and evaluate the new tokenizer on actual selected materials before implementing its generator.

New inference hardware, longer contexts, and broader generators should respond to a demonstrated artistic or engineering need. They do not replace the encounter-and-consequence cycle.

## 13 API and module boundaries

### 13.1 Application modules

Keep storage responsible for durable identities, transactions, migrations, and retrieval of records. Put corpus import/windowing/index management in a small `corpus` module, candidate retrieval in `retrieval`, text transformations in `operations`, typed influence evaluation in `influences`, and external model calls in `providers`. These are suggested module boundaries, not a requirement to create a large class hierarchy.

The existing `model_adapter` remains the authority for NCM. A rule evaluator receives validated immutable data and produces a proposed text patch plus typed effects. It does not write the database or call a language model. The application service validates and commits those effects in one transaction.

Frontend components should follow the user activities: source context, encounter list, correspondence, work entries, operation preview, influence binding, name index, and history. Extract components as they acquire real responsibilities; do not continue expanding a single large `App.tsx` indefinitely.

Keep shared request/response types explicit. A small set of discriminated operation and effect types is sufficient. Avoid a generic workflow-builder schema before there are several implemented workflows.

### 13.2 Endpoint contracts

Preserve current endpoints. Add project-scoped routes for the new domain so a request identifies its project independently of current UI selection. Initially mutations may still require that project to be active; return `PROJECT_NOT_ACTIVE` for a mismatch rather than applying an operation to the wrong project.

The following route families define the required responsibilities. Exact naming can follow existing conventions if the same distinctions remain documented.

| Route family | Required responsibility |
| --- | --- |
| `/api/v1/projects/{project_id}/sources` | Import, list, inspect source versions and exact context |
| `.../fragments` | Bounded fragment/window listing and exact anchors |
| `.../encounters` | Submit a retrieval recipe; return results or a job referencing the recipe |
| `.../correspondences` | Save, revise, inspect, and set aside interpretations and their references |
| `.../works` | Create/read works; explicitly edit, reorder, remove, or restore entries |
| `.../influences` | Create immutable definition versions and list supported templates |
| `.../works/{work_id}/binding` | Bind, replace, or unbind with expected work state |
| `.../previews` | Prepare deterministic or model-assisted candidates without live effects |
| `.../works/{work_id}/commit` | Atomically adopt a prepared candidate and its validated effects |
| `.../works/{work_id}/held-names/{held_id}/return` | Preview/commit return of one identified held name |
| `.../jobs` and `.../exports` | Inspect bounded background work and create portable results |

Model-assisted previews return a job and later a preview/candidate identifier. Deterministic previews can return synchronously. Both use the same candidate and commit contract. Do not use an endpoint whose name implies preview to mutate live work state.

Use the existing error envelope: code, message, details, and retryable status. Add concrete errors for invalid spans, missing marks, protected-range conflicts, stale previews/targets, profile mismatch, unavailable capability, invalid provider output, and unsupported project format.

A commit request should be small because the server resolves the saved preview:

~~~json
{
  "client_request_id": "unique-id-for-this-application",
  "preview_id": "immutable-preview-id",
  "candidate_id": "selected-candidate-id",
  "expected_work_state_version": 7
}
~~~

The server first honors a valid existing application receipt, before any endpoint-level stale-state gate. For a new application it resolves the captured binding, exact inputs, typed destination, and effects from the preview, compares them to current state, and rejects tampering or staleness. A successful response includes the application ID, resulting work state version, affected entry/revision IDs, event ID, and held-name IDs.

Use cursor pagination or explicit bounded limits for source lists, fragment lists, events, and candidates. Do not load an entire corpus in the desk payload.

## 14 Interface behavior

Add a clearly named Correspondences workspace alongside the existing desk. The artist should be able to move a passage or result between them without copying away its identity.

The initial working table contains source encounters, the selected work, and an operation area. The name index and influence definition can be persistent side areas when space permits or accessible panels when it does not. Keep the text itself prominent. A global force-directed graph is not part of the first release.

Source encounters display complete short passages, a title, and a compact reason. Longer passages expand in context. Show interpretation after selection or on request. Avoid large confidence badges, occult-significance meters, or automatic explanations that preempt reading.

An operation preview shows the actual selected inputs, editable parameters, relevant protection, active binding, and the common base candidate versus the affected candidate. The primary action says what will happen, such as “Add to work” or “Adopt repair.” Pending model output never appears as if already committed.

The name index lists individual held occurrences, even when their displayed names match. Each item provides its source, receiving entry, status, and actions. A detached or unresolved target must be visible without losing the name. Returning a name requires a clear preview when the destination has been retargeted.

When the artist changes source selection after previewing, the current candidate comparison remains tied to its original inputs. A new selection prepares a new operation; it must not relabel the existing result's provenance.

Keep keyboard interaction, visible focus, readable contrast, sensible headings, screen-reader labels, reduced-motion behavior, and responsive reflow. Source selection and marking need an accessible alternative to drag selection, such as selecting an occurrence from a text-selection dialog. A color difference alone must not communicate protected versus changed text.

Model settings and technical provenance belong in an inspector. The ordinary flow should not require the artist to understand hashes, byte offsets, tensor layouts, or request IDs.

Opening a work restores its entries, binding, held names, saved candidates, and draft. Show actual unfinished items. Do not invent a message from an influence or simulate an event to make the reopening screen feel alive.

## 15 Export and portability

Provide a readable Markdown or plain-text export of a work, with its title, ordered entries, and an optional appendix containing source references, influence definitions, held names, and event history. Let the artist choose whether the appendix accompanies an exhibition text.

Provide a portable project archive containing a versioned manifest, required text assets, source metadata, exact fragment anchors, correspondences, works and entry revisions, influence versions and bindings, held names, events, application receipts, operation records, and saved model representations. Include saved desk and work-entry drafts, selections, retained previews/candidates, and their immutable inputs. Exclude credentials, active worker leases, and machine-specific paths.

Embedding and search caches can be omitted and rebuilt. Model weights should not be bundled by default; export their profiles and fingerprints. Imported projects must remain readable without those weights. An unavailable model affects new inference, not access to saved artifacts.

Export from a consistent snapshot. Validate archive paths, hashes, IDs, and supported schema versions on import. Reject path traversal, executable payload assumptions, and corrupt referenced assets. An export-import round trip must retain committed history and the ability to return a held name.

Importing the same project as a copy should establish an explicit copied-project identity while retaining internal relationships. Do not silently overwrite an existing project because its title matches.

Restore imported queued/running jobs as inactive or interrupted records requiring an explicit retry. Restoring bindings, held names, events, and receipts restores saved state; it must not replay effects, resume worker leases, or automatically invoke a provider.

Later offline games and exhibition works should execute supported local rules from precomputed material without requiring Python, model weights, an API key, or a network connection. That player is a subsequent deliverable, not an obligation for the first Correspondences release.

## 16 Acceptance and verification

### 16.1 End-to-end artistic fixture

Create a small clearly labeled invented corpus for deterministic verification. Include at least three sources, a plausible relation, an obvious mismatch, repeated name strings, and an alternative reading. This fixture verifies behavior; it does not establish that discovery is compelling on the artist's archive.

The primary walkthrough imports the corpus, opens a passage in context, obtains literal and semantic encounters, saves a correspondence, creates an influence and work, marks one name, previews a governed ordinary transfer, and adopts it. After closing and reopening the application, the receiving entry must still show the intended displacement and the name index must retain its exact origin and recipient. Returning the name creates a new revision while leaving the earlier one inspectable.

A second walkthrough commits two transfers with the same name text, returns only one, unbinds the influence, and commits a third transfer. One older name remains held, the new transfer preserves its marked text, and all events remain distinguishable.

A third walkthrough changes the work or binding after preparing a preview. Adoption must reject the stale preview without discarding current edits. Editing a receiving entry before returning its name must preserve the held name and require a valid current target.

### 16.2 Engineering acceptance cases

| ID | Scenario | Required result |
| --- | --- | --- |
| A01 | Open a populated baseline-format project | Migration preserves draft, selection, exact assets, revisions, annotations, and old runs |
| A02 | Import CRLF, BOM, emoji, combining marks, non-ASCII text, and repeated phrases | Exact bytes and intended occurrence anchors survive import, use, and export |
| A03 | Import a document longer than every enabled model window | Whole source remains intact; model windows are explicit and never silently truncated |
| A04 | Same text appears in distinct source occurrences | Provenance remains distinct; default encounters group or omit trivial duplicates |
| A05 | Preview several bound candidates | No live work entries or held names are created |
| A06 | Commit one bound transfer | Revision, entry, held name, event, receipt, and work version change atomically |
| A07 | Retry after commit but before success response | Original receipt/result is returned; no duplicate graft or name |
| A08 | Reuse request ID with different payload | Conflict is reported; previous result remains unchanged |
| A09 | Change work, entry order, binding, or candidate before adoption | Stale preview is rejected |
| A10 | Apply name displacement across protected donor text | Visible conflict; protected bytes and state remain unchanged |
| A11 | Return an older held occurrence with duplicate name strings present | Only the specified occurrence changes |
| A12 | Edit or remove the receiving entry | Held name persists with unresolved/detached target; no guessed replacement |
| A13 | Unbind an influence | Future governed behavior changes; past events and held names remain |
| A14 | Run omission repair | Actual request matches the declared window with the selected occurrence removed and no undeclared source clues; legitimate duplicate text in retained context remains |
| A15 | Provider returns malformed, over-budget, or incomplete output | Bounded error/retry behavior; no fabricated success or adoption |
| A16 | Open with no NCM weights or instruction server | Archive, saved works, deterministic transfer, return, and history remain usable |
| A17 | Cancel while a worker claims or finishes a job | Consistent terminal state; no half-applied effect |
| A18 | Export and import a complete project | History, anchors, work state, and held-name actions survive |
| A19 | Generate an NCM variation | Exact sampled hierarchy and raw decoded IDs are retained with correct representation kind |
| A20 | Re-encode edited generated text | A new representation is created; the earlier sampled hierarchy remains unchanged |
| A21 | Apply a later edit, repair, or return over protected bytes | Conflict or explicit protection release occurs; no false protection label survives changed bytes |

For the later NCM comparison increment, add tests for incompatible profiles, `m = 0`, equal prefixes, a degenerate `B_m = 1` baseline, sparse strata, valid negative adjusted agreement, duplicate graft locations, retained-prefix boundaries, and no-change code replacements. Controlled fixtures should verify metric arithmetic independently of the model implementation.

Use unit tests for span and rule contracts, transactional integration tests for state changes, and a small number of browser workflows for the complete artistic cycle. Do not create a broad collection of tests that merely restate component internals. Test the failure modes that could alter the artist's work or misrepresent an operation.

### 16.3 Real capability checks

Run at least one real embedding retrieval example and one real configured instruction-provider repair before claiming those capabilities work. Record the model/profile and actual input/output. Do not substitute a deterministic mock for a capability claim.

Preserve existing NCM adapter fixtures and test expectations. For saved sampled representations, verify replay under the recorded compatible execution profile. Stored outputs remain authoritative when later hardware or numerical settings differ.

If a capability cannot be exercised in the available environment, complete unaffected work and report that specific validation as outstanding. Do not describe the complete release as fully verified while its required live model path remains untested.

### 16.4 Artistic evaluation

Use a small selection of Matthew's actual materials after the engineered fixture works. Record a few sessions in terms of the encounters offered, operations chosen, results kept, rules bound, and work resumed. This is observation of use, not a numerical measure of occult significance.

The central questions are whether an encounter was worth reading, whether an intervention made a consequential difference, whether the material resisted a preferred interpretation, and whether the artist wanted to continue a work after returning. A compelling result need not be fluent or long.

If the application repeatedly produces only broad thematic labels and polished explanations, improve source selection, retrieval diversity, and the specificity of operations before expanding infrastructure. Keep unsuccessful correspondences available when they help show why an approach failed.

## 17 Implementation sequence

### Increment A Preserve and prepare

Read the current code, this document, and the relevant earlier inference contracts. Add migration-on-open, transaction-aware persistence helpers, and exact sampled-hierarchy preservation. Separate worker liveness from capability readiness. Keep the desk functional and preserve its behavior.

Completion means a populated old project opens safely, existing operations still work, and archive/history access does not depend on a successful NCM model load.

### Increment B Import and encounter

Implement exact source import, immutable versions, paragraph fragments, context display, lexical search, and the pinned embedding provider. Add bounded encounter results and saved correspondences. Use source fragments rather than thousands of desk passage revisions.

Completion means the artist can import a real collection, inspect original passages in context, encounter material through two actual retrieval views, and save a correspondence that can be reopened.

### Increment C Work and consequence

Implement ordered works, stable entry identities, ordinary transfer, protected insertion, influence definitions and binding, preview/adoption, the held-name index, return/retarget behavior, and event history. Use one preset and one active binding per work.

Completion means the full deterministic cycle survives restart and the duplicate-name, stale-preview, protected-span, and interrupted-response scenarios pass. This is the first substantial artistic interaction; do not postpone it until every research instrument exists.

### Increment D Repair and portable completion

Add marked omission and the configured instruction-provider repair path. Finish source/operation inspection, portable export/import, keyboard behavior, and the complete browser walkthrough. Verify the live embedding and repair paths, and record one session using actual selected material.

Completing A through D is the Correspondences release. A search interface without operative consequences, or a rule demonstration disconnected from the corpus, does not meet that release gate.

### Increment E Compare representations

Add NCM corpus encoding, paired reconstruction, the documented agreement metric and baseline, and the latent-graft interface using saved representations. Evaluate whether those encounters add anything useful to the working practice.

This increment can be developed in parallel only when it does not delay completion of the core cycle or destabilize the verified adapter.

### Increment F Extend from demonstrated use

Choose the next operator or rule from the artist's observed sessions. Protected host healing, role inversion, and register translation are strong candidates. A broader tokenizer is justified when existing representations visibly limit the selected material. Implement one extension end to end before building a general framework for all of them.

## 18 Instructions for the coding agent

Treat this document as a product and behavior contract. The exact module and table arrangement can follow the repository's conventions, but source identity, preview/commit separation, rule scope, transactional effects, and provenance distinctions are not optional.

Inspect current HEAD and relevant local instructions first. Reconcile changes made after the documented baseline. Do not reset or overwrite newer work to match this snapshot. Keep code, migration, and documentation changes focused on the active increment.

Use the existing dependency and development workflow. Add only dependencies with a current implemented purpose. Do not introduce a vector service, message broker, distributed worker system, graph database, arbitrary plugin runtime, or agent orchestration framework for the first release.

Keep model assets outside source control and pin profiles. Do not change checkpoint identities, display policies, or existing inference validation merely to make a new feature appear compatible. Record deliberate profile extensions separately.

Keep `docs/decisions.md` concise and specific about material departures, schema changes, provider selections, and validation results. Update the README with exact installation, model setup, startup, import, and completion steps. A fresh user should be able to reach the first artistic cycle without reading internal source files.

At the end of each substantial increment, leave a short continuation note identifying completed behavior, the next concrete task, important invariants, and any actual blockers. Do not create a second competing master specification or an enormous inventory of hypothetical tasks.

The completion report should state what changed, how the full cycle was exercised, which model capabilities were actually run, what remains unavailable, and where the artist starts. Preserve real failures and limitations rather than generating attractive demonstration outputs that the program did not produce.

## 19 Longer artistic and investigative program

### 19.1 Carry forward the white paper's operators

The dATAPLOT white paper is a source of artistic procedures and research questions. Implement its useful operations with explicit input boundaries, preserved outputs, and distinct actual derivation. Its biological analogies are not prerequisites for making the software work. [R17]

| Operator family | Concrete software behavior | Required qualification |
| --- | --- | --- |
| Variation | Generate bounded alternative families and compare declared features or relations | Recurrence may follow the prompt, model, or preservation constraint |
| Omission and repair | Remove a marked span and generate replacements from declared remaining context | Record what was withheld and supplied |
| Translation of register | Render a declared event or relation as testimony, contract, prayer, inventory, instruction, or tale | Inspect what changed as well as what survived |
| Inversion | Exchange roles, negate a condition, reverse an obligation, or change who may speak | Define the particular transformation; do not rely only on a vague anti-text prompt |
| Fragment reconstruction | Generate speculative surrounding works from a supplied fragment | Save the fragment and actual prompt boundary; generated context is a proposal |
| Chimeric graft | Preserve a donor while rewriting allowed host regions | Assemble protected text server-side and expose rejected integrations |
| Imagined ancestry | Generate fictional earlier drafts with explicit vestigial possibilities | Actual production and fictional chronology are different relationships |
| Distant futures | Extend specified world rules through chosen horizons | Generated futures are conditional artifacts, not forecasts established by the model |

Sound and visual scope can become additional instruments. A phonological view needs a declared pronunciation resource or user-supplied pronunciation, treatment of ambiguous words, and inspectable counts. A viewpoint or visual-distance annotation is an interpretation and should retain its annotator and supporting text. A search for a word that compresses a larger relation can be an artistic exercise without declaring a literal hidden memory mechanism.

These operators should produce artifacts the artist can keep, juxtapose, and bind to later procedures. Their value does not depend on every experiment affirming its initial interpretation.

### 19.2 Grammar and relationship surgery

Add part-of-speech and dependency views when they support specific operations. Grammatical grafting can reuse the earlier practice of retaining one text's arrangement while substituting selected material from another. Preserve which elements supplied the structure and which supplied the vocabulary. [R15]

A relational comparison should keep conditions and negations explicit. “Only if,” “unless,” and an exchanged giver and receiver can change the force of an otherwise similar passage. A model's proposal should be inspectable and rejectable before it becomes an operative rule.

“Same relation, different material” and “same words, opposing relation” are useful view names. Their retrieval recipes require actual implementations and evaluation; they should not be decorative labels on ordinary semantic similarity.

### 19.3 Richer influences and games

Add a second rule only after the first creates useful work. A transfer-creates-obligation rule could record a specific obligation between entries or works and constrain a later action. A preservation rule could require a phrase to survive a declared transformation. A retrieval rule could restrict the next donor collection or require a counterexample.

Each rule needs a trigger, scope, preconditions, typed effects, conflict behavior, and persistent state. A future combination engine must define ordering and prevent unbounded recursive triggers. It must not treat the language model's narration as an authoritative state update.

Game behavior can emerge from these bounded rules, limited available actions, and unfinished consequences. An influence becomes a game entity through what it can do and the history of its actions. A complete RPG, invented cosmological ontology, or conversational personality is not required.

The earlier reveal puzzle, Memory Weather, retelling sequences, and The Last Account can later use the same saved artifacts and work histories. Preserve their concepts in the original specification without treating them as unfinished obligations of this release.

### 19.4 Folklore and historical inquiry

Folklore work should retain the identity of particular tellings, editions, languages, translators, and contexts. Compare specific relations such as conditional hospitality, a transfer with a price, prohibited naming, or inherited obligation without flattening different traditions into a universal motif.

Imported scholarly classifications may be useful when their source and applicability are known. The application should also support the artist's own provisional groupings. Computational resemblance does not by itself establish historical influence; dated transmission evidence can be added as a distinct documented relationship.

A strong session might discover that two tales behave similarly under an intervention, or that an apparent match collapses when the condition of an exchange changes. Both results can guide writing and further inquiry.

### 19.5 The personal archive and dATAPLOT

The personal-archive trajectory examines changes in procedures, grammatical forms, images, and relations across decades of work. A later text can become an instrument for rereading an earlier one. The archive should make those encounters available without declaring that a recent interpretation was already consciously present in the earlier work.

The dATAPLOT trajectory allows artifacts to acquire fictional histories alongside actual events of creation, interpretation, performance, circulation, and revision. Cryptographic integrity and stable identity can preserve particular versions. Behavior comes from implemented operations, human activity, and recorded state changes.

Reader contributions and documented performances can return as new material through explicit import or event entry. Publishing, messaging, autonomous external actions, and multiuser access require separate product scope. The first release remains a local artistic instrument.

Hyperstition is operationalized here as a traceable process: an interpretation is adopted, its defined effects change a work or practice, and those changes become material for later interpretation. The program must allow this feedback while preserving when and how it occurred. [R16–R17]

## 20 References and builder source map

The links below identify primary sources and the inspected repository baseline. The new product design, release priorities, rule preset, data contracts, and acceptance criteria are specified in this document; they are not claims that the NCM paper evaluated this application.

**R01 — Openwound reviewed head.** [Commit b5719b8](https://github.com/mbutler/openwound/commit/b5719b8bba8aeda4b2809611d9d93602e3ee8019). Inspect later changes before implementation.

**R02 — Existing specification and writing desk.** [Original technical specification](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/ncm_art_studio_openwound_v4_technical_spec.md), [App.tsx](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/frontend/src/App.tsx), and [implementation decisions](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/docs/decisions.md).

**R03 — Job execution and worker.** [execute.py](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/backend/ncm_art/jobs/execute.py) and [worker.py](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/backend/ncm_art/jobs/worker.py).

**R04 — Persistence and API.** [project.py](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/backend/ncm_art/storage/project.py), [library.py](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/backend/ncm_art/storage/library.py), and [app.py](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/backend/ncm_art/api/app.py).

**R05 — Current model profile.** [tinystories-v1.json](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/model_profiles/tinystories-v1.json). Contains the released hierarchy, model revisions, and artifact hashes.

**R06 — NCM paper.** [Next-Concept Modeling: Fast, Parallel Coarse-to-Fine Text Generation, arXiv 2610.14162v1](https://arxiv.org/abs/2610.14162v1). Consult the architecture and Appendix H together with the pinned code; preserve the earlier specification's adapter corrections.

**R07 — NCM upstream snapshot.** [HazyResearch/ncm at c702742](https://github.com/HazyResearch/ncm/tree/c70274273f489abc73832b2b98584a8483b6b203).

**R08 — Current verified adapter.** [tinystories.py](https://github.com/mbutler/openwound/blob/b5719b8bba8aeda4b2809611d9d93602e3ee8019/backend/ncm_art/model_adapter/tinystories.py). Relevant functions include `encode_source`, `reconstruct_trace`, `branch_tinystories`, and `apply_graft`.

**R09 — Upstream representation code.** [models/quant.py](https://github.com/HazyResearch/ncm/blob/c70274273f489abc73832b2b98584a8483b6b203/models/quant.py), [models/vqvae.py](https://github.com/HazyResearch/ncm/blob/c70274273f489abc73832b2b98584a8483b6b203/models/vqvae.py), and [models/next_concept.py](https://github.com/HazyResearch/ncm/blob/c70274273f489abc73832b2b98584a8483b6b203/models/next_concept.py).

**R10 — Broader model configuration.** [config/eval/owt.yaml](https://github.com/HazyResearch/ncm/blob/c70274273f489abc73832b2b98584a8483b6b203/config/eval/owt.yaml). Treat tokenizer and generator support as separate capabilities.

**R11 — Existing tests and recorded fixtures.** Use the tests and `fixtures/recorded/tinystories-cpu-fp32-eager-v1.json` in the reviewed repository. Keep recorded checkpoint evidence distinct from random-model fixtures and new live validation.

**R12 — Lexical retrieval.** [SQLite FTS5 documentation](https://sqlite.org/fts5.html).

**R13 — Semantic retrieval.** [Sentence Transformers semantic search documentation](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html).

**R14 — Local structured generation.** [LM Studio structured output documentation](https://lmstudio.ai/docs/developer/openai-compat/structured-output). Check the configured model's actual support and validate responses.

**R15 — Early practice.** Matthew Butler, [The lifecycle of the Corpus Chimera](https://mbutler.org/the-lifecycle-of-the-corpus-chimera/), including grammatical grafting and the movement from generated material through interpretation to instruction.

**R16 — Early conceptual framework.** Matthew Butler, [Crypto-Adaptation](https://mbutler.org/crypto-adaptation/), originally produced in May 2003.

**R17 — Artist-provided white paper.** Matthew Butler, *WHITE PAPER: dATAPLOT — Protocol for the Excavation and Stabilization of Agential Material in Latent Semantic Space*, version 2.0, supplied in the project discussion. The operator catalog and artistic motivations relevant to implementation are preserved in Section 19; the builder does not need the original attachment to complete the first release.

**R18 — Initial embedding baseline.** [sentence-transformers/all-MiniLM-L6-v2 model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) and [model metadata](https://huggingface.co/api/models/sentence-transformers/all-MiniLM-L6-v2). The repository revision observed for this specification is `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.



