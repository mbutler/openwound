# Continuation

The current cycle is the live instrument. The desk's job queue was built for slow inference; on this machine a trace or a variation takes well under a second, so the Instrument and Memory Weather call the model directly and keep nothing until asked. Increment F (protected host healing) and the Correspondences release are unchanged and live under the Archive place.

## Completed

- The live engine (`live/engine.py`) loads TinyStories lazily in the API process under one lock. `POST /api/v1/live/trace` returns the codes and all twelve readings; `POST /api/v1/live/vary` keeps a prefix and samples the rest, from saved codes or from text. Neither writes to the project.
- Keeping is the only write. `live/keep` commits the source revision, its encoding, and the variation's sampled hierarchy through the same records the job path uses. `live/keep-frame` commits one reading as `decoded_from`. `live/keep-run` commits a Memory Weather run as a chain, each telling `generated_from` the telling before it, with a cut telling recorded as its own `trimmed_from` revision.
- The Instrument screen: passage with a token gauge, the twelve passes drawn as a band of code cells, one Keep dial from 0 through 12, the twelve readings, and the live variation with a word diff. Reconstruction frames are no longer written to history on every run.
- Memory Weather: a finite run driven from the browser, a return-to-source interval, and an explicit overflow policy (cut to the window, or stop). Each telling is shown as it arrives.
- A first-run explainer that uses the artist's own trace. Correspondences, works, repair, healing, and comparison are reached through Archive and are not changed.

- Format 4 opens an older project through the format-3 backup and adds works, influences, previews, receipts, held names, and protected ranges.
- Ordinary transfer copies a donor span into a chosen position. With `withhold_marked_span_v1` bound, only the marked occurrence becomes `_____`, and that name is indexed.
- Protected insertion keeps the donor bytes exact. A name rule that would change them is refused. A later edit or return over those bytes conflicts unless the protection is released.
- Preview does not create entries or held names. Adoption, retry, a conflicting request id, and a stale work or binding behave as separate outcomes. Reopening shows the displaced entry and the name's origin and recipient.
- The desk draft, the selected passage, and the 128-token gate are unchanged by this cycle.
- An omission repair asks only for the marked span. The provider sees the declared window with that one occurrence replaced by `_____`. Adopting a repair uses the same commit as a transfer, and the name rule does not apply.
- A readable export can include an appendix. A project archive imports as a new project. Unfinished jobs are marked interrupted and are not replayed. Embeddings and credentials stay out of the archive.
- Format 5 adds saved code comparisons. Slot agreement uses equal code slots. A length band of 16 unpadded tokens supplies the common-code baseline. A latent graft keeps the retained prefix and regenerates after it.
- Protected host healing, `heal_around_protected_graft_v1`, asks an instruction provider only for the text before and after a marked span. The span is copied back by the server and kept as a protected range. Adopting it uses the existing commit. The name rule does not apply.

## Next

Local code substitution: click one cell in the band to replace that code with a codebook neighbour at the same level, or resample it from the generator's own conditional, then regenerate the passes below. This is v3's word-vector substitution carried over to codebook vectors. Role inversion and register translation are still open. A broader tokenizer is not justified by the passages compared so far.

## Invariants

- Canonical text stays exact UTF-8 bytes. A mark is one span, not the first copy of a repeated string.
- Preview is not adoption. A receipt is written in the same transaction as the entry and the held name.
- One active binding per work. Unbinding does not restore names or erase events.
- A protected label is kept only while its bytes still match.
- A correspondence is not textual ancestry. Jobs do not change the desk draft or the selected passage.

## Blockers

No instruction provider is configured on this machine. Import, transfer, returning a name, healing around a span, and reopening an imported project work without one. A live repair and a live healing, with the actual request and the model's text, have not been recorded.

A live TinyStories comparison was recorded. Two short passages, 8 tokens and 7 tokens, agreed on 0.160 of the slots in the first three levels and on none of the slots in the first level. The length band was too small for a baseline adjustment. A latent graft of that pair regenerated a passage and left the work and the desk draft unchanged. Pair reconstruction of that same pair was not run.
