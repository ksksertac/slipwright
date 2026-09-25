"""The database behind the store: SQLite for a local install, PostgreSQL for a server.

One object owns the engine, hands out connections and knows which dialect it is talking
to. Everything above it writes SQLAlchemy Core expressions against ``store/schema.py``,
so a query is written once and runs on both.

Three things this layer exists to hide:

* **Transactions.** ``begin()`` is the write path and ``connect()`` the read path. On
  SQLite writes are additionally serialised by a lock, because one file cannot take
  concurrent writers; on PostgreSQL the lock is a no-op and the pool does the work.
* **Rows.** SQLAlchemy returns tuple-like ``Row`` objects; the store reads columns by
  name, so ``rows()`` and ``one()`` hand back plain dicts.
* **Upserts.** ``INSERT ... ON CONFLICT DO UPDATE`` is spelled differently per dialect.
  ``upsert()`` picks the right one.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, Result, Table, create_engine, event, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError

from slipwright.store.schema import metadata


class DatabaseUnavailable(RuntimeError):
    """The database never answered. Says which one, so the URL can be checked."""

    def __init__(self, url: str, cause: Exception | None) -> None:
        # the URL carries the password; show only enough of it to identify the server
        shown = url.split("@")[-1] if "@" in url else url
        super().__init__(f"database at {shown} did not answer: {cause}")
        self.url = shown


def url_for(target: str | Path) -> str:
    """A database URL from what the caller had: a URL stays, a path becomes SQLite.

    Every existing caller passes a file path (``<state>/jobs.sqlite3``) and keeps working;
    a hosted installation passes ``postgresql+psycopg://…`` instead.
    """
    value = str(target)
    return value if "://" in value else f"sqlite:///{Path(value).as_posix()}"


class Database:
    """One engine, shared across threads."""

    def __init__(self, url: str | Path, *, echo: bool = False) -> None:
        self.url = url_for(url)
        self.dialect = "sqlite" if self.url.startswith("sqlite") else "postgresql"
        kwargs: dict[str, Any] = {"echo": echo, "future": True}
        if self.dialect == "sqlite":
            # the API serves requests on a thread pool and jobs run on their own threads
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_pre_ping"] = True  # a server connection can be cut between jobs
        self.engine: Engine = create_engine(self.url, **kwargs)
        # one writer at a time on SQLite; on PostgreSQL this is never contended because
        # `begin()` does not take it
        self._write_lock = threading.RLock()
        if self.dialect == "sqlite":
            self._prepare_sqlite()

    def _prepare_sqlite(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.close()

    def create_all(self) -> None:
        """Bring an empty or older database up to the declared schema."""
        metadata.create_all(self.engine)

    def wait_until_ready(self, *, timeout_s: float = 30.0, every_s: float = 0.5) -> None:
        """Block until the server answers, or give up and say so.

        Only ever waits for PostgreSQL; a file is ready the moment it exists. Started by
        ``docker compose up``, the application and its database come up together, and the
        application usually wins -- without this, the first boot after every deploy fails
        on a database that was two seconds from being ready.
        """
        if self.dialect == "sqlite":
            return
        deadline = time.monotonic() + timeout_s
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                return
            except OperationalError as exc:  # not up yet, or still starting
                last = exc
                time.sleep(every_s)
        raise DatabaseUnavailable(self.url, last)

    def dispose(self) -> None:
        self.engine.dispose()

    # -- connections -------------------------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        """A read connection. Nothing is committed on the way out."""
        with self.engine.connect() as conn:
            yield conn

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        """A write transaction: committed on a clean exit, rolled back on an exception."""
        if self.dialect == "sqlite":
            with self._write_lock, self.engine.begin() as conn:
                yield conn
            return
        with self.engine.begin() as conn:
            yield conn

    # -- upserts -----------------------------------------------------------------------

    def upsert(self, table: Table, values: Mapping[str, Any] | Sequence[Mapping[str, Any]], *,
               key: Sequence[str], update: Sequence[str]) -> Any:
        """``INSERT … ON CONFLICT (key) DO UPDATE SET update…`` for the current dialect."""
        maker = sqlite_insert if self.dialect == "sqlite" else pg_insert
        stmt = maker(table).values(values)
        return stmt.on_conflict_do_update(
            index_elements=list(key),
            set_={name: getattr(stmt.excluded, name) for name in update},
        )

    # -- plain SQL, for the rare dialect-specific query ---------------------------------

    def sql(self, statement: str) -> Any:
        return text(statement)


# -- rows -------------------------------------------------------------------------------


def rows(result: Result[Any]) -> list[dict[str, Any]]:
    """Every row as a plain dict, so columns are read by name."""
    return [dict(row) for row in result.mappings()]


def one(result: Result[Any]) -> dict[str, Any] | None:
    """The first row as a dict, or ``None``."""
    row = result.mappings().first()
    return None if row is None else dict(row)


__all__ = ["Database", "DatabaseUnavailable", "one", "rows", "url_for"]
