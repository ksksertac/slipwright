"""Bringing a database up to the current schema.

Two situations, one entry point:

* **A new database** -- the test suite, a first run, a freshly created PostgreSQL
  database. There is nothing to migrate, so the tables are created straight from the
  declarations in ``schema.py`` and the database is stamped with the newest revision so
  later upgrades know where they start.
* **An existing one** -- Alembic runs whatever revisions it has not seen.

Doing it this way keeps the test suite fast (no revision is replayed to build an empty
database) while a server that has been running for months still upgrades in order. The
declarations stay the single source of truth for *what* the schema is; the revisions
record *how it changed*.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, inspect

from slipwright.standards import fts
from slipwright.store.db import Database
from slipwright.store.schema import metadata

log = logging.getLogger(__name__)

#: ``slipwright/alembic``: the revision scripts ship with the package.
ALEMBIC_DIR = Path(__file__).resolve().parent.parent / "alembic"

# Alembic narrates at INFO ("Running upgrade …"), which is right for its own command line
# and wrong inside a library call: whatever the host process has pointed the root logger
# at then receives it, and a CLI that prints a token to stdout finds the token mixed with
# migration chatter. Only warnings get through.
logging.getLogger("alembic").setLevel(logging.WARNING)


def _config(db: Database) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", db.url)
    # env.py reads the live connection from here rather than opening a second one
    cfg.attributes["database"] = db
    return cfg


def current_revision(db: Database) -> str | None:
    with db.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def is_empty(db: Database) -> bool:
    """True when nothing of ours has ever been written here."""
    return "jobs" not in set(inspect(db.engine).get_table_names())


def migrate(db: Database) -> None:
    """Make the database match the declarations. Safe to call on every start.

    A brand-new database is built from the declarations and stamped as current, all in
    one transaction. That last part matters more than it looks: both engines run DDL
    transactionally, so a failure part-way through leaves *nothing* behind. Without it a
    half-built database would come back on the next start with its tables present but no
    revision stamped, and the migrations would then be replayed over a schema that
    already had them -- "column already exists", and no way forward but by hand.

    A database that already has tables but no stamp is the old hand-rolled SQLite one
    from before migrations existed. It upgrades normally: revision 0001 creates only what
    is missing, and the rest apply in order.
    """
    # started by compose, the application and its database come up together
    db.wait_until_ready()
    cfg = _config(db)
    if is_empty(db) and current_revision(db) is None:
        with db.begin() as conn:
            metadata.create_all(conn)
            fts.create(conn, db.dialect)
            _stamp(conn, cfg)
        log.info("database created at the current revision")
        return
    command.upgrade(cfg, "head")
    with db.begin() as conn:
        fts.create(conn, db.dialect)


def _stamp(conn: Connection, cfg: Config) -> None:
    """Record the newest revision, on this connection so it shares the transaction."""
    cfg.attributes["connection"] = conn
    try:
        command.stamp(cfg, "head")
    finally:
        cfg.attributes.pop("connection", None)


__all__ = ["ALEMBIC_DIR", "current_revision", "is_empty", "migrate"]
