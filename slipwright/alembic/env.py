"""Alembic's entry point, wired to Slipwright's own engine.

The usual generated ``env.py`` opens its own connection from the config URL. Ours takes
the live ``Database`` the caller already built (``cfg.attributes["database"]``) when there
is one, so a migration runs on the same engine, the same pool and -- on SQLite -- the same
file the store has open. Falling back to the URL keeps ``alembic`` usable from a terminal.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from slipwright.store.schema import metadata

config = context.config
target_metadata = metadata


def _render_as_batch(dialect_name: str) -> bool:
    """SQLite cannot ALTER a column in place; batch mode rewrites the table instead."""
    return dialect_name == "sqlite"


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # a caller may hand us the very connection it is working on, so a migration or a
    # stamp joins its transaction instead of opening a second one beside it
    existing = config.attributes.get("connection")
    if existing is not None:
        context.configure(
            connection=existing,
            target_metadata=target_metadata,
            render_as_batch=_render_as_batch(existing.dialect.name),
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    database = config.attributes.get("database")
    if database is not None:
        connectable = database.engine
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_render_as_batch(connection.dialect.name),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
