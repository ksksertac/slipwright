"""Moving an installation from one database to another -- in practice, SQLite to PostgreSQL.

The code has run on both for a while; an installation that started on the SQLite file
still has every account, project and job in it, and pointing ``SLIPWRIGHT_DATABASE_URL``
at a server does not bring any of that along. This does.

It copies what ``schema.py`` declares, table by table, and nothing else:

* **The keyword index is not copied.** On SQLite it is an FTS5 virtual table; PostgreSQL
  derives it from ``standards_chunks`` itself, so copying the chunks is copying the index.
* **Stored credentials are copied still encrypted.** The target must be opened with the
  same key as the source (``SLIPWRIGHT_SECRET_KEY``, or the ``secret.key`` beside the
  SQLite file) or every model key, Git token and Jira token reads back as nothing.
* **Files are not the database.** Checkouts, test logs and the key itself stay where they
  are; only the rows move.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import delete, func, insert, select, text

from slipwright.store.db import Database
from slipwright.store.migrate import migrate
from slipwright.store.schema import metadata, users

#: Rows per INSERT. Large enough to be quick, small enough that one statement never
#: carries a whole table of agent transcripts.
BATCH = 500


class TargetNotEmpty(RuntimeError):
    """The target already has accounts: copying over them would merge two installations."""


def copy_database(
    source: Database, target: Database, *, progress: Callable[[str, int], None] | None = None
) -> dict[str, int]:
    """Copy every declared table from ``source`` into ``target``; return rows per table.

    Both are brought to the current schema first, so a source a few revisions behind is
    upgraded in place before it is read -- the same thing starting the server on it would
    do.

    A target that has only been *started* -- the server ran once against it, created the
    tables and filled the price list -- is fine: those rows are replaced. A target with
    accounts in it is refused, because that is a second installation and copying into it
    would leave two sets of people sharing one database.
    """
    migrate(source)
    migrate(target)
    with target.connect() as conn:
        if conn.execute(select(func.count()).select_from(users)).scalar_one():
            raise TargetNotEmpty(
                "the target database already has accounts; copy into an empty one"
            )

    counts: dict[str, int] = {}
    # one transaction: a copy that fails half-way leaves the target as it was, rather
    # than with the accounts but not their projects
    with target.begin() as dst:
        # children first when clearing, parents first when filling
        for table in reversed(metadata.sorted_tables):
            dst.execute(delete(table))
        for table in metadata.sorted_tables:
            counts[table.name] = 0
            with source.connect() as src:
                result = src.execution_options(stream_results=True).execute(select(table))
                while chunk := result.fetchmany(BATCH):
                    dst.execute(insert(table), _rows(chunk))
                    counts[table.name] += len(chunk)
            if progress is not None:
                progress(table.name, counts[table.name])
        if target.dialect == "postgresql":
            _advance_sequences(dst)
    return counts


def _rows(chunk: Any) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in chunk]


def _advance_sequences(conn: Any) -> None:
    """Move each serial column's sequence past the rows that were copied in.

    The copy writes ``job_history.seq`` explicitly, which PostgreSQL does not count
    against the sequence; left alone, the next transition of the first job would be
    handed ``seq = 1`` and collide with the history it already has.
    """
    for table in metadata.sorted_tables:
        for column in table.columns:
            if not (column.primary_key and column.autoincrement is True):
                continue
            conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', '{column.name}'), "
                    f"COALESCE((SELECT MAX({column.name}) FROM {table.name}), 0) + 1, false)"
                )
            )


def count_rows(db: Database) -> dict[str, int]:
    """Rows per declared table, to compare a source with its copy."""
    with db.connect() as conn:
        return {
            table.name: conn.execute(select(func.count()).select_from(table)).scalar_one()
            for table in metadata.sorted_tables
        }


__all__ = ["BATCH", "TargetNotEmpty", "copy_database", "count_rows"]
