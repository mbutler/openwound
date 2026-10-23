"""Shared tokenization for retrieval recipes.

The stopword list is a fixed function-word policy. It is not a claim that the
remaining words are significant.
"""

import re

STOPWORD_POLICY = "english-function-words-v1"
STOPWORDS = frozenset(
    """
    a an the and or but if then else when while of to in on for with at by from
    as into over after before between under about against through during without
    within along across behind beyond up down off out nor so yet both either
    neither not no than too very just also only own same such this that these
    those it its he she they them his her their we our you your i me my who
    whom which what where why how there here is am are was were be been being
    do does did have has had having will would shall should can could may might
    must
    """.split()
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def content_words(text: str) -> list[str]:
    return [token for token in tokens(text) if token.casefold() not in STOPWORDS]


def jaccard(left: str, right: str) -> float:
    a = {word.casefold() for word in content_words(left)}
    b = {word.casefold() for word in content_words(right)}
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def phrases(text: str, limit: int = 16) -> list[str]:
    words = tokens(text)
    found: list[str] = []
    for size in range(min(4, len(words)), 1, -1):
        for index in range(0, len(words) - size + 1):
            found.append(" ".join(words[index : index + size]))
            if len(found) >= limit:
                return found
    return found
