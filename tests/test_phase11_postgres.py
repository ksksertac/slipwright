"""T11 — the same store, on PostgreSQL.

A hosted installation runs on PostgreSQL and the test suite runs on SQLite, which means
the interesting bugs are the ones only one of them has: a compound index expression that
needs its own parentheses, a column called ``text``, an upsert spelled differently, a
migration that rewrites a table.

These tests are skipped unless ``SLIPWRIGHT_TEST_DATABASE_URL`` points at a server, so
the ordinary run stays fast and needs nothing installed. To run them::

    docker run -d --name pg -e POSTGRES_PASSWORD=slipwright -e POSTGRES_USER=slipwright \\
        -e POSTGRES_DB=slipwright -p 55432:5432 postgres:16-alpine
    SLIPWRIGHT_TEST_DATABASE_URL=postgresql+psycopg://slipwright:slipwright@\\
        127.0.0.1:55432/slipwright uv run pytest tests/test_phase11_postgres.py
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from slipwright.auth import UserStatus
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.project import Project
from slipwright.secrets import generate_key
from slipwright.standards import page_from_text
from slipwright.standards.index import HashingEmbedder, StandardsIndex
from slipwright.store import JobStore, ProjectNotFound
from slipwright.store.scoped import ScopedStore

URL = os.environ.get("SLIPWRIGHT_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not URL, reason="set SLIPWRIGHT_TEST_DATABASE_URL to run the PostgreSQL tests"
)


@pytest.fixture
def pg() -> Iterator[JobStore]:
    """A store on a freshly emptied schema, so every test starts from nothing."""
    scratch = JobStore(URL, secret_key=generate_key())
    with scratch.db.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    scratch.close()
    store = JobStore(URL, secret_key=generate_key())
    try:
        yield store
    finally:
        store.close()


# --- the schema itself ---------------------------------------------------------------------


def test_a_fresh_database_is_built_and_stamped(pg: JobStore) -> None:
    tables = set(inspect(pg.db.engine).get_table_names())
    for expected in ("jobs", "projects", "job_history", "settings", "users", "standards_chunks"):
        assert expected in tables
    # stamped as current, so the next start upgrades rather than replaying
    assert "alembic_version" in tables
    with pg.db.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def test_opening_it_again_is_a_no_op(pg: JobStore) -> None:
    again = JobStore(URL, secret_key=generate_key())
    try:
        assert "jobs" in set(inspect(again.db.engine).get_table_names())
    finally:
        again.close()


# --- the things that differ by dialect ---------------------------------------------------------


def test_jobs_and_history_round_trip(pg: JobStore, repo: Path) -> None:
    project = pg.create_project(Project(name="demo", repo_path=repo, owner_id="ada"))
    job = pg.create(Job(request="health", repo_path=repo, project_id=project.id, owner_id="ada"))
    pg.update_state(job.id, JobState.BACKLOG, note="job started")
    pg.update_state(job.id, JobState.AWAITING_BACKLOG_APPROVAL, note="po: ready")

    again = pg.get(job.id)
    assert again.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert [t.note for t in again.history] == ["job started", "po: ready"]
    # the auto-incrementing history key is a SERIAL here and an AUTOINCREMENT there
    assert len(again.history) == 2


def test_the_owner_filter_works(pg: JobStore, repo: Path) -> None:
    mine = pg.create_project(Project(name="ada's", repo_path=repo, owner_id="ada"))
    pg.create_project(Project(name="bob's", repo_path=repo, owner_id="bob"))
    assert [p.name for p in pg.list_projects("ada")] == ["ada's"]
    assert pg.get_project(mine.id, "ada").name == "ada's"
    # not found rather than forbidden: a 403 would confirm that the id exists
    with pytest.raises(ProjectNotFound):
        pg.get_project(mine.id, "bob")


def test_upserts_are_spelled_for_this_dialect(pg: JobStore) -> None:
    """Settings, translations, prices and pages all go through ``Database.upsert``."""
    pg.set_setting("providers.default", "anthropic", user_id="ada")
    pg.set_setting("providers.default", "openai", user_id="ada")
    assert pg.get_setting("providers.default", user_id="ada") == "openai"

    pg.save_translations("tr", {"Backlog ready": "Backlog hazır"})
    pg.save_translations("tr", {"Backlog ready": "Backlog hazırlandı"})
    assert pg.translations("tr", ["Backlog ready"]) == {"Backlog ready": "Backlog hazırlandı"}

    pg.put_price("anthropic", "m", input_usd=1.0, output_usd=2.0)
    pg.put_price("anthropic", "m", input_usd=3.0, output_usd=4.0)
    price = pg.get_price("anthropic", "m")
    assert price is not None and price["input_usd"] == 3.0

    pg.save_user_page("ada", "backend", "messaging", "one")
    pg.save_user_page("ada", "backend", "messaging", "two")
    page = pg.get_user_page("ada", "backend", "messaging")
    assert page is not None and page["body"] == "two"


def test_secrets_are_encrypted_here_too(pg: JobStore) -> None:
    pg.set_setting("providers.anthropic.api_key", "sk-secret", secret=True, user_id="ada")
    assert pg.get_setting("providers.anthropic.api_key", user_id="ada") == "sk-secret"
    with pg.db.connect() as conn:
        raw = conn.execute(
            text("SELECT value_json FROM settings WHERE name = 'providers.anthropic.api_key'")
        ).scalar_one()
    assert "sk-secret" not in raw


def test_accounts_and_tokens_work(pg: JobStore) -> None:
    user = pg.create_user("ada", "correct horse", email="ada@example.com")
    assert pg.find_by_email("ADA@example.com") is not None
    assert pg.authenticate("ada@example.com", "correct horse") is not None
    pg.set_status(user.id, UserStatus.SUSPENDED)
    assert pg.authenticate("ada@example.com", "correct horse") is None

    token, secret = pg.create_token(user.id, "cli")
    assert pg.token_user(secret) is not None
    pg.revoke_token(token.id)
    assert pg.token_user(secret) is None


def test_the_rate_limiter_counts(pg: JobStore) -> None:
    assert not any(pg.hit_rate_limit("signup:a@b.co", limit=3, window_s=60) for _ in range(3))
    assert pg.hit_rate_limit("signup:a@b.co", limit=3, window_s=60)


# --- keyword search: tsvector here, FTS5 there --------------------------------------------------


def test_standards_search_finds_the_right_sections(pg: JobStore) -> None:
    index = StandardsIndex(pg.db, HashingEmbedder())
    page = """---
domain: backend
tags: [retries]
applies_to: [backend]
---

# Messaging

## Retries

A poisoned message must not stop the consumer group.

## Metrics

Every consumer reports lag.
"""
    index.reindex([page_from_text("backend", "messaging", page)], owner_id="ada")

    hits = index.search("poisoned consumer", "backend", owner_id="ada", k=5)
    assert hits, "the tsvector index found nothing"
    assert "poisoned message" in hits[0].chunk.text

    # and the layer filter holds: another account sees none of it
    assert index.search("poisoned consumer", "backend", owner_id="bob", k=5) == []


def test_browsing_returns_sections_in_page_order(pg: JobStore) -> None:
    index = StandardsIndex(pg.db, HashingEmbedder())
    page = """---
domain: backend
tags: [a]
applies_to: [backend]
---

# Messaging

## First

one

## Second

two
"""
    index.reindex([page_from_text("backend", "messaging", page)], owner_id="ada")
    headings = [h.chunk.heading for h in index.browse("backend", k=5, owner_id="ada")]
    assert headings == ["First", "Second"]


def test_a_scoped_store_keeps_accounts_apart_here_too(pg: JobStore) -> None:
    ScopedStore(pg, "ada").set_setting("jira.token", "ada-token", secret=True)
    ScopedStore(pg, "bob").set_setting("jira.token", "bob-token", secret=True)
    assert ScopedStore(pg, "ada").get_setting("jira.token") == "ada-token"
    assert ScopedStore(pg, "bob").get_setting("jira.token") == "bob-token"
