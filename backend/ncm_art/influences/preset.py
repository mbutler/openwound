"""The one operative preset: a marked span is withheld when a donor enters a work."""

from ncm_art.operations.text import displace, overlaps
from ncm_art.storage.errors import ProjectError

TEMPLATE = "withhold_marked_span_v1"
TRIGGER = "donor_enters_work"


def validate_definition(template: str | None, parameters: dict | None) -> dict:
    if template is None:
        if parameters:
            raise ProjectError("INVALID_TEXT", "An idea does not take rule parameters.")
        return {}
    if template != TEMPLATE:
        raise ProjectError("UNSUPPORTED_TEMPLATE", "That influence template is not available.")
    if not isinstance(parameters, dict):
        raise ProjectError("INVALID_TEXT", "Rule parameters have to be a JSON object.")
    unknown = set(parameters) - {"mark_role", "replacement_text"}
    if unknown or set(parameters) != {"mark_role", "replacement_text"}:
        raise ProjectError("INVALID_TEXT", "That influence has parameters this preset does not use.")
    if parameters["mark_role"] != "name" or not isinstance(parameters["replacement_text"], str):
        raise ProjectError(
            "INVALID_TEXT",
            "This preset withholds one marked name and replaces it with the given text.",
        )
    return {"mark_role": "name", "replacement_text": parameters["replacement_text"]}


def apply_to_donor(donor: bytes, mark_start: int, mark_end: int, replacement: str) -> tuple[bytes, int, int]:
    if mark_end <= mark_start:
        raise ProjectError("MARK_REQUIRED", "Mark the name this passage must leave behind.", status=409)
    return displace(donor, mark_start, mark_end, replacement)


def conflicting_protection(mark_start: int, mark_end: int, protected: list[tuple[int, int]]) -> None:
    for start, end in protected:
        if overlaps(mark_start, mark_end, start, end):
            raise ProjectError(
                "RULE_CONFLICT",
                "The name rule would change a protected passage. Use an ordinary transfer, unbind the influence, or choose another work.",
                status=409,
            )
