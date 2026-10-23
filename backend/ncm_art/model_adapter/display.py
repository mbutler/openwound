"""Text display policies for a raw token row.

The ordinary policy matches the TinyStories evaluation script: cut at the first
EOS, drop EOS and PAD, then decode. A diagnostic view keeps tokens after EOS.
The two policies are different records and must not be substituted for each other.
"""

DISPLAY_POLICY_CUT_AT_EOS = "tinystories-eval-cut-at-eos-v1"
DISPLAY_POLICY_KEEP_AFTER_EOS = "diagnostic-keep-after-eos-v1"


def select_display_ids(
    raw_ids: list[int],
    eos_id: int,
    pad_id: int,
    policy: str = DISPLAY_POLICY_CUT_AT_EOS,
) -> list[int]:
    ids = [int(token) for token in raw_ids]
    if policy == DISPLAY_POLICY_CUT_AT_EOS:
        if eos_id in ids:
            ids = ids[: ids.index(eos_id)]
    elif policy != DISPLAY_POLICY_KEEP_AFTER_EOS:
        raise ValueError(f"Unknown display policy {policy}.")
    hidden = {eos_id, pad_id}
    return [token for token in ids if token not in hidden]


def displayed_text(
    raw_ids: list[int],
    eos_id: int,
    pad_id: int,
    decode,
    policy: str = DISPLAY_POLICY_CUT_AT_EOS,
) -> str:
    return decode(select_display_ids(raw_ids, eos_id, pad_id, policy))
