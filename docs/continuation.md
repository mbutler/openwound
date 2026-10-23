# Continuation

Increment C is in place. The artist can keep an ordered work, transfer a passage into it, bind one name-withholding influence, preview the change, adopt it, and return the held name. The governing contract is `openwound-v4-correspondences-build-spec.md`.

## Completed

- Format 4 opens an older project through the format-3 backup and adds works, influences, previews, receipts, held names, and protected ranges.
- Ordinary transfer copies a donor span into a chosen position. With `withhold_marked_span_v1` bound, only the marked occurrence becomes `_____`, and that name is indexed.
- Protected insertion keeps the donor bytes exact. A name rule that would change them is refused. A later edit or return over those bytes conflicts unless the protection is released.
- Preview does not create entries or held names. Adoption, retry, a conflicting request id, and a stale work or binding behave as separate outcomes. Reopening shows the displaced entry and the name's origin and recipient.
- The desk draft, the selected passage, and the 128-token gate are unchanged by this cycle.

## Next

Increment D: marked omission and a configured instruction-provider repair, then portable export and import. Do not treat the deterministic cycle as that repair.

## Invariants

- Canonical text stays exact UTF-8 bytes. A mark is one span, not the first copy of a repeated string.
- Preview is not adoption. A receipt is written in the same transaction as the entry and the held name.
- One active binding per work. Unbinding does not restore names or erase events.
- A protected label is kept only while its bytes still match.
- A correspondence is not textual ancestry. Jobs do not change the desk draft or the selected passage.

## Blockers

None for the deterministic work cycle. The instruction-provider repair in Increment D has not been configured.
