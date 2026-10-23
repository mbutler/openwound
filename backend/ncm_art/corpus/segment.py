"""Paragraph fragments and explicit model windows.

Paragraph bytes are an exact slice of the source. A window is a smaller view
into a paragraph that does not fit a model's input budget. The source itself
is never shortened to fit.
"""

import re

_BLANK_LINE = re.compile(r"(?:\r\n|\n)[ \t]*(?:\r\n|\n)")
_SENTENCE_END = re.compile(r"[.?!](?:\s+|$)")
_WORD = re.compile(r"\S+\s*")

PARAGRAPH_SEGMENTATION = "paragraph-blankline-v1"
WINDOW_SEGMENTATION = "window-sentence-whitespace-v1"


def paragraph_spans(raw: bytes) -> list[tuple[int, int]]:
    text = raw.decode("utf-8")
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in _BLANK_LINE.finditer(text):
        if match.start() > cursor:
            spans.append(_bytes(text, cursor, match.start(), 0))
        cursor = match.end()
    if cursor < len(text):
        spans.append(_bytes(text, cursor, len(text), 0))
    return [(start, end) for start, end in spans if start < end]


def window_spans(text: str, token_count, limit: int) -> list[tuple[int, int]] | None:
    """Code-point spans. None means the whole text already fits."""
    if limit < 1:
        raise ValueError("A model window needs a positive token limit.")
    if token_count(text) <= limit:
        return None
    sentences = _cover(text, _SENTENCE_END)
    grouped = _pack(text, sentences, token_count, limit)
    return grouped


def _pack(text: str, pieces: list[tuple[int, int]], token_count, limit: int) -> list[tuple[int, int]]:
    packed: list[tuple[int, int]] = []
    start = None
    end = None
    for piece_start, piece_end in pieces:
        piece = text[piece_start:piece_end]
        if token_count(piece) > limit:
            if start is not None:
                packed.append((start, end))
                start = None
            packed.extend(_split_piece(text, piece_start, piece_end, token_count, limit))
            continue
        if start is None:
            start, end = piece_start, piece_end
            continue
        combined = text[start:piece_end]
        if token_count(combined) <= limit:
            end = piece_end
        else:
            packed.append((start, end))
            start, end = piece_start, piece_end
    if start is not None:
        packed.append((start, end))
    return packed


def _split_piece(text: str, start: int, end: int, token_count, limit: int) -> list[tuple[int, int]]:
    piece = text[start:end]
    words = [(start + match.start(), start + match.end()) for match in _WORD.finditer(piece)]
    if len(words) > 1:
        return _pack(text, words, token_count, limit)
    return _split_code_points(text, start, end, token_count, limit)


def _split_code_points(text: str, start: int, end: int, token_count, limit: int) -> list[tuple[int, int]]:
    spans = []
    cursor = start
    while cursor < end:
        fit = cursor
        for index in range(cursor + 1, end + 1):
            if token_count(text[cursor:index]) <= limit:
                fit = index
            else:
                break
        if fit == cursor:
            raise ValueError("A single character does not fit the model window.")
        spans.append((cursor, fit))
        cursor = fit
    return spans


def _cover(text: str, pattern: re.Pattern) -> list[tuple[int, int]]:
    spans = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.end() > cursor:
            spans.append((cursor, match.end()))
            cursor = match.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return spans or [(0, len(text))]


def _bytes(text: str, start: int, end: int, base: int) -> tuple[int, int]:
    prefix = len(text[:start].encode("utf-8"))
    piece = len(text[start:end].encode("utf-8"))
    return base + prefix, base + prefix + piece
