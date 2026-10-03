"""A development's history is read without its details unless one is opened.

One QA note once carried a 145 MB diff of node_modules. The page that follows a
development asks for it every time anything happens, and every one of those requests
loaded, parsed and sent the whole of it: two cores busy, memory swinging by gigabytes and
forty gigabytes sent in six hours. A detail is now bounded when it is written, and the
lists and the page are given each entry's size; the entry somebody opens is read alone.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.store.sqlite import DETAIL_TAIL, MAX_DETAIL
from tests.pipeline import full_engine, full_provider, full_seed


@pytest.fixture
def seed() -> Profile:
    return full_seed()


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _job_with(engine: Engine, repo: Path, detail: str) -> tuple[str, int]:
    job = engine.create_job("count the visitors", repo)
    job = engine.store.update_state(job.id, job.state, note="a big diff", detail=detail)
    return job.id, len(job.history) - 1


def test_a_detail_too_large_is_cut_keeping_its_start_and_its_end(
    engine: Engine, store: JobStore, repo: Path
) -> None:
    start, end = "diff --git a/src/app.py b/src/app.py\n", "\nerror: the last line\n"
    huge = start + "x" * (MAX_DETAIL * 3) + end
    job_id, index = _job_with(engine, repo, huge)

    kept = store.get(job_id).history[index].detail
    assert kept is not None
    assert len(kept) < MAX_DETAIL + 100
    assert kept.startswith(start)  # a diff's file list is at its start...
    assert kept.endswith(end)  # ...and a build log's error at its end
    assert "characters cut here" in kept
    assert len(kept[-DETAIL_TAIL:]) == DETAIL_TAIL
    # a detail that fits is written as it came
    _, small = _job_with(engine, repo, "a small log")
    assert store.get(store.list()[-1].id).history[small].detail == "a small log"


def test_a_job_read_without_details_carries_their_sizes(
    engine: Engine, store: JobStore, repo: Path
) -> None:
    job_id, index = _job_with(engine, repo, "+" * 1000)

    light = store.get(job_id, details=False)

    entry = light.history[index]
    assert entry.detail is None
    assert entry.detail_size == 1000
    assert entry.has_detail
    assert [j.history[index].detail for j in store.list(details=False)] == [None]
    # the entry read on its own is whole
    whole = store.transition(job_id, index)
    assert whole is not None and whole.detail == "+" * 1000
    assert store.transition(job_id, len(light.history)) is None


def test_the_page_is_sent_sizes_and_fetches_the_one_entry_it_opens(
    client: TestClient, engine: Engine, repo: Path
) -> None:
    job_id, index = _job_with(engine, repo, "diff --git a/a b/a\n+one line\n")

    job = client.get(f"/api/jobs/{job_id}").json()
    sent = job["history"][index]
    assert sent["detail"] is None
    assert sent["detail_size"] == len("diff --git a/a b/a\n+one line\n")
    listed = client.get("/api/jobs").json()
    assert listed[0]["history"][index]["detail"] is None

    opened = client.get(f"/api/jobs/{job_id}/history/{index}").json()
    assert opened["detail"] == "diff --git a/a b/a\n+one line\n"
    assert client.get(f"/api/jobs/{job_id}/history/999").status_code == 404
    assert client.get("/api/jobs/nope/history/0").status_code == 404


def test_the_activity_feed_still_knows_an_entry_has_a_detail(
    client: TestClient, engine: Engine, repo: Path
) -> None:
    job_id, _ = _job_with(engine, repo, "a log")
    feed = client.get("/api/activity").json()
    mine = [item for item in feed if item["job_id"] == job_id and item["title"] == "a big diff"]
    assert mine and mine[0]["has_detail"] is True


def test_sizes_are_filled_in_for_the_history_written_before_them(tmp_path: Path) -> None:
    from alembic import command
    from sqlalchemy import text

    from slipwright.store.db import Database
    from slipwright.store.migrate import _config, migrate
    from slipwright.store.schema import metadata

    db = Database(str(tmp_path / "old.sqlite3"))
    try:
        metadata.create_all(db.engine)
        with db.begin() as conn:
            conn.execute(text("ALTER TABLE job_history DROP COLUMN detail_size"))
            conn.execute(text("DROP TABLE worker_calls"))  # (0015)
            conn.execute(text("ALTER TABLE workers DROP COLUMN lent_by"))
            conn.execute(text("ALTER TABLE worker_codes DROP COLUMN lent_by"))
            conn.execute(text("ALTER TABLE worker_codes DROP COLUMN pair_key"))
            conn.execute(text("ALTER TABLE workers DROP COLUMN about_json"))  # (0016)
            conn.execute(
                text(
                    "INSERT INTO jobs (id, request, title, repo_path, state, created_at,"
                    " updated_at) VALUES ('j1', 'r', 't', '/r', :state, '2026-01-01',"
                    " '2026-01-01')"
                ),
                {"state": JobState.DONE.value},
            )
            for detail in ("twelve chars", None):
                conn.execute(
                    text(
                        "INSERT INTO job_history (job_id, from_state, to_state, at, note,"
                        " detail) VALUES ('j1', 'created', 'done', '2026-01-01', 'n', :d)"
                    ),
                    {"d": detail},
                )
        command.stamp(_config(db), "0013_job_messages")

        migrate(db)

        with db.connect() as conn:
            sizes = [
                r[0] for r in conn.execute(text("SELECT detail_size FROM job_history ORDER BY seq"))
            ]
        assert sizes == [12, None]
    finally:
        db.dispose()
