"""T11 — the rules an agent works to belong to the account that set them.

Slipwright ships a corpus of standards. On a hosted installation one person rewriting a
page must not rewrite it for everybody, so a rewritten page is stored against that
account and *shadows* the shipped one for them alone. Deleting it is "back to the
default"; nothing is destroyed by editing.

Three layers, most specific first: the project's own overrides, then the account's, then
the pages that ship.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slipwright.engine import Engine
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.standards import page_from_text
from slipwright.standards.index import HashingEmbedder, StandardsIndex
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

PAGE = """---
domain: backend
tags: [retries, messaging]
applies_to: [backend]
---

# Messaging

## Retries

{rule}
"""


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8600, end=8699)),
        seed_profile=seed,
    )


@pytest.fixture
def index(store: JobStore) -> StandardsIndex:
    return StandardsIndex(store.db, HashingEmbedder())


# --- the store ---------------------------------------------------------------------------


def test_a_rewritten_page_is_kept_against_its_account(store: JobStore) -> None:
    store.save_user_page("ada", "backend", "messaging", PAGE.format(rule="ada retries twice"))
    mine = store.get_user_page("ada", "backend", "messaging")
    assert mine is not None and "ada retries twice" in mine["body"]
    assert store.get_user_page("bob", "backend", "messaging") is None
    assert [p["name"] for p in store.user_pages("ada")] == ["messaging"]
    assert store.user_pages("bob") == []


def test_deleting_a_page_is_going_back_to_the_default(store: JobStore) -> None:
    store.save_user_page("ada", "backend", "messaging", PAGE.format(rule="mine"))
    assert store.delete_user_page("ada", "backend", "messaging") is True
    assert store.get_user_page("ada", "backend", "messaging") is None
    # and asking again is not an error: there is simply nothing of theirs left
    assert store.delete_user_page("ada", "backend", "messaging") is False


def test_the_fingerprint_moves_only_when_a_page_does(store: JobStore) -> None:
    before = store.pages_fingerprint("ada")
    store.save_user_page("ada", "backend", "messaging", PAGE.format(rule="one"))
    after = store.pages_fingerprint("ada")
    assert after != before
    assert store.pages_fingerprint("ada") == after  # unchanged, so unchanged
    store.save_user_page("ada", "backend", "messaging", PAGE.format(rule="two"))
    assert store.pages_fingerprint("ada") != after


# --- the index ----------------------------------------------------------------------------


def test_an_account_reads_its_own_page_and_nobody_elses(index: StandardsIndex) -> None:
    index.reindex(
        [page_from_text("backend", "messaging", PAGE.format(rule="ada retries twice"))],
        owner_id="ada",
    )
    index.reindex(
        [page_from_text("backend", "messaging", PAGE.format(rule="bob never retries"))],
        owner_id="bob",
    )

    def text_for(owner: str) -> str:
        return " ".join(h.chunk.text for h in index.search("retries", "backend", owner_id=owner))

    assert "ada retries twice" in text_for("ada")
    assert "bob never retries" not in text_for("ada")
    assert "bob never retries" in text_for("bob")
    # somebody with no page of their own sees neither
    assert text_for("carol") == ""


def test_a_rewritten_page_replaces_the_shipped_one_rather_than_joining_it(
    index: StandardsIndex,
) -> None:
    """Both would otherwise be read into the same prompt, contradicting each other."""
    shipped = page_from_text("backend", "messaging", PAGE.format(rule="retry three times"))
    index.reindex([shipped.__class__(**{**shipped.__dict__, "scope": "global"})])
    index.reindex(
        [page_from_text("backend", "messaging", PAGE.format(rule="never retry"))],
        owner_id="ada",
    )

    read = " ".join(h.chunk.text for h in index.search("retry", "backend", owner_id="ada", k=10))
    assert "never retry" in read
    assert "retry three times" not in read
    # and the account that changed nothing still reads the shipped page
    theirs = " ".join(h.chunk.text for h in index.search("retry", "backend", owner_id="bob", k=10))
    assert "retry three times" in theirs


def test_the_project_layer_wins_over_the_account_layer(index: StandardsIndex) -> None:
    index.reindex(
        [page_from_text("backend", "messaging", PAGE.format(rule="the account says twice"))],
        owner_id="ada",
    )
    project_page = page_from_text("backend", "messaging", PAGE.format(rule="this repo says once"))
    index.reindex(
        [project_page.__class__(**{**project_page.__dict__, "scope": "project"})],
        project_id="p1",
    )
    read = " ".join(
        h.chunk.text
        for h in index.search("says", "backend", owner_id="ada", project_id="p1", k=10)
    )
    assert "this repo says once" in read
    assert "the account says twice" not in read


# --- through the engine ----------------------------------------------------------------------


def test_an_agent_is_given_its_owners_rules(engine: Engine, repo: Path) -> None:
    """A page one account wrote reaches that account's agents and no others.

    The request has to be one the page actually answers: retrieval is a search, so a page
    about retries is read when the work is about retries, and not otherwise.
    """
    engine.store.save_user_page(
        "ada", "backend", "messaging", PAGE.format(rule="ada's own retry rule")
    )

    def rules_read_for(owner: str, name: str) -> str:
        project = engine.store.create_project(
            Project(name=name, repo_path=repo, owner_id=owner)
        )
        job = engine.create_job("retries on the messaging consumer", project_id=project.id)
        retrieved = engine.standards_for(job, RoleName.BACKEND, engine.seed_profile)
        assert retrieved is not None
        # what actually reaches the prompt, not the index's own listing of it
        return " ".join(str(s.get("text", "")) for s in retrieved.sections)

    assert "ada's own retry rule" in rules_read_for("ada", "ada's")
    assert "ada's own retry rule" not in rules_read_for("bob", "bob's")


def test_reindexing_an_account_is_skipped_when_nothing_moved(engine: Engine) -> None:
    engine.store.save_user_page("ada", "backend", "messaging", PAGE.format(rule="one"))
    first = engine.reindex_standards(owner_id="ada")
    assert first["skipped"] is False and first["added"] >= 1
    assert engine.reindex_standards(owner_id="ada")["skipped"] is True
    engine.store.save_user_page("ada", "backend", "messaging", PAGE.format(rule="two"))
    assert engine.reindex_standards(owner_id="ada")["skipped"] is False
