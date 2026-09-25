"""Keyword search over the standards index, in whichever dialect is underneath.

This is the one place where SQLite and PostgreSQL genuinely diverge. SQLite has FTS5 --
a virtual table with its own BM25 -- and PostgreSQL has ``tsvector``. Neither can be
spelled in portable Core expressions, so both live here behind one function and the rest
of ``standards/index.py`` never learns which it got.

The two rankers do not return identical numbers, and they do not need to: the caller
fuses this ranking with the embedding one by reciprocal rank (``_rrf``), which only reads
the order. What both must agree on is *which* sections match and that a heading hit
outranks a body hit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, text

# unchanged from the SQLite-only index: two characters or more, apostrophes and hyphens
# kept inside a word so "end-to-end" stays one token
_TOKEN = re.compile(r"[\w][\w'-]{1,}", re.UNICODE)

#: Beyond this the query stops being a query and starts being the document.
MAX_TOKENS = 32

# -- SQLite -----------------------------------------------------------------------------

# FTS5 cannot be declared through MetaData, so the virtual table is raw DDL. `id` is
# unindexed: it is carried along to join back, never searched.
SQLITE_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS standards_fts USING fts5("
    "  id UNINDEXED, heading, text, tags, tokenize = 'porter unicode61')"
)

# -- PostgreSQL -------------------------------------------------------------------------

# 'simple' rather than 'english': the shipped standards are written in Turkish, and an
# English stemmer on Turkish text is worse than no stemmer at all.
#
# Two pieces of PostgreSQL pedantry are load-bearing here. A compound index expression
# needs parentheses of its own inside ``USING GIN ( … )``, and the ``text`` column has to
# be quoted or the parser reads it as the type name.
_TSVECTOR = (
    "setweight(to_tsvector('simple', coalesce(heading, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(\"text\", '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(tags, '')), 'D')"
)
POSTGRES_DDL = (
    f"CREATE INDEX IF NOT EXISTS standards_chunks_tsv ON standards_chunks USING GIN (({_TSVECTOR}))"
)


def words(text: str) -> list[str]:
    """Every word of a text, lowercased. What an embedder reads."""
    return [t.lower() for t in _TOKEN.findall(text)]


def tokens(query: str) -> list[str]:
    """The words of a *query*, capped: past a few dozen it is a document, not a question."""
    return words(query)[:MAX_TOKENS]


def match_expression(query: str) -> str:
    """A safe FTS5 MATCH expression: quoted tokens joined with OR."""
    return " OR ".join(f'"{t}"' for t in tokens(query))


def create(conn: Connection, dialect: str) -> None:
    """Create whatever the dialect needs beyond the declared tables."""
    conn.execute(text(SQLITE_DDL if dialect == "sqlite" else POSTGRES_DDL))


def index_chunk(
    conn: Connection, dialect: str, *, chunk_id: str, heading: str, body: str, tags: str
) -> None:
    """Add one section to the keyword index. PostgreSQL derives it from the row itself,
    so there is nothing to write there."""
    if dialect != "sqlite":
        return
    conn.execute(
        text(
            "INSERT INTO standards_fts (id, heading, text, tags) "
            "VALUES (:id, :heading, :text, :tags)"
        ),
        {"id": chunk_id, "heading": heading, "text": body, "tags": tags},
    )


def drop_chunk(conn: Connection, dialect: str, chunk_id: str) -> None:
    if dialect != "sqlite":
        return
    conn.execute(text("DELETE FROM standards_fts WHERE id = :id"), {"id": chunk_id})


def scores(conn: Connection, dialect: str, query: str, *, ids: Sequence[str]) -> dict[str, float]:
    """``{chunk id: score}`` for the sections this query hits. Higher is better."""
    if not ids:
        return {}
    asked = tokens(query)
    if not asked:
        return {}
    if dialect == "sqlite":
        return _sqlite_scores(conn, query, ids)
    return _postgres_scores(conn, asked, ids)


def _sqlite_scores(conn: Connection, query: str, ids: Sequence[str]) -> dict[str, float]:
    # column weights: a heading hit is worth more than a body hit, tags least
    result = conn.execute(
        text(
            "SELECT id, bm25(standards_fts, 4.0, 1.0, 0.3) AS rank FROM standards_fts "
            "WHERE standards_fts MATCH :match"
        ),
        {"match": match_expression(query)},
    )
    wanted = set(ids)
    # bm25() is negative and lower is better, so it is flipped to "higher is better"
    return {r.id: -float(r.rank) for r in result if r.id in wanted}


def _postgres_scores(
    conn: Connection, asked: Sequence[str], ids: Sequence[str]
) -> dict[str, float]:
    # the same OR-of-tokens the FTS5 side builds, as a tsquery
    query = " | ".join(asked)
    result = conn.execute(
        text(
            f"SELECT id, ts_rank_cd('{{0.1, 0.3, 0.5, 1.0}}', ({_TSVECTOR}), "
            "  to_tsquery('simple', :query)) AS rank "
            f"FROM standards_chunks WHERE id = ANY(:ids) "
            f"  AND ({_TSVECTOR}) @@ to_tsquery('simple', :query)"
        ),
        {"query": query, "ids": list(ids)},
    )
    return {r.id: float(r.rank) for r in result}


__all__: list[Any] = [
    "MAX_TOKENS",
    "POSTGRES_DDL",
    "SQLITE_DDL",
    "create",
    "drop_chunk",
    "index_chunk",
    "match_expression",
    "scores",
    "tokens",
    "words",
]
