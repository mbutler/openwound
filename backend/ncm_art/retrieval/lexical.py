"""Literal encounters from the FTS5 index.

Artist text is quoted before it reaches MATCH. Exact phrase offsets are read
from the source bytes. A case-folded FTS hit is not presented as a quotation.
"""

import sqlite3

from ncm_art.retrieval.text import STOPWORD_POLICY, content_words, jaccard, phrases, tokens

RECIPE = "fts5-unicode61-exact-phrase-v1"


def _quote(token: str) -> str:
    return '"' + token.replace('"', '""') + '"'


def search(project, query: str, collection: str = "imported") -> list[dict]:
    words = content_words(query) or tokens(query)
    if not words:
        return []
    match = " OR ".join(_quote(word) for word in words)
    phrase_list = phrases(query)
    try:
        with project._conn() as conn:
            rows = conn.execute(
                """SELECT f.id, f.source_id, f.start_byte, f.end_byte, f.slice_sha256,
                          f.source_text_sha256, s.title, s.author, s.family_id
                   FROM fragment_fts
                   JOIN source_fragment f ON f.id = fragment_fts.fragment_id
                   JOIN source_document s ON s.id = f.source_id
                   WHERE fragment_fts MATCH ? AND s.collection = ?""",
                (match, collection),
            ).fetchall()
            frequencies = {phrase: _count(conn, phrase) for phrase in phrase_list}
            word_frequencies = {_quote(word): _count(conn, word) for word in words}
    except sqlite3.OperationalError:
        return []
    assets: dict[str, bytes] = {}
    hits = []
    for row in rows:
        digest = row["source_text_sha256"]
        if digest not in assets:
            assets[digest] = project.read_asset_bytes(digest)
        raw = assets[digest]
        text = raw[row["start_byte"] : row["end_byte"]].decode("utf-8")
        exact = _exact_spans(text, phrase_list, row["start_byte"])
        rarest = min((frequencies[span["text"]] for span in exact), default=10**9)
        if not exact:
            present = [word for word in words if word.casefold() in {item.casefold() for item in tokens(text)}]
            if present:
                rarest = min(word_frequencies[_quote(word)] for word in present)
        hits.append(
            {
                "fragment_id": row["id"],
                "source_id": row["source_id"],
                "title": row["title"],
                "author": row["author"],
                "family_id": row["family_id"],
                "start_byte": row["start_byte"],
                "end_byte": row["end_byte"],
                "slice_sha256": row["slice_sha256"],
                "text_sha256": digest,
                "text": text,
                "view": "lexical",
                "reason": "Shared phrase" if exact else "Shared words, case-folded",
                "score": None,
                "recipe": RECIPE,
                "stopword_policy": STOPWORD_POLICY,
                "matched_spans": exact,
                "folded": not exact,
                "rarest_df": rarest,
                "overlap": jaccard(query, text),
            }
        )
    hits.sort(key=lambda hit: (0 if hit["matched_spans"] else 1, hit["rarest_df"], -hit["overlap"], hit["fragment_id"]))
    return hits


def _count(conn, phrase: str) -> int:
    row = conn.execute(
        "SELECT count(*) FROM fragment_fts WHERE fragment_fts MATCH ?",
        (_quote(phrase),),
    ).fetchone()
    return int(row[0])


def _exact_spans(text: str, phrase_list: list[str], base: int) -> list[dict]:
    spans = []
    seen: set[tuple[int, int]] = set()
    for phrase in phrase_list:
        cursor = 0
        while phrase:
            found = text.find(phrase, cursor)
            if found < 0:
                break
            start = base + len(text[:found].encode("utf-8"))
            end = start + len(phrase.encode("utf-8"))
            if (start, end) not in seen:
                seen.add((start, end))
                spans.append({"start_byte": start, "end_byte": end, "label": "exact", "text": phrase})
            cursor = found + len(phrase)
    return spans
