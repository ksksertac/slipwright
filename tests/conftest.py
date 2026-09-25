import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from slipwright.schemas.profile import Profile
from slipwright.store import JobStore


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small git repository with one commit on ``main``."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "core.autocrlf", "false")
    (path / "README.md").write_bytes(b"# fixture repo\n")  # bytes: no CRLF translation
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "initial")
    return path


@pytest.fixture
def worktrees_root(tmp_path: Path) -> Path:
    return tmp_path / "worktrees"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    """The store every test writes through.

    SQLite by default, which is what the suite wants: a file per test, no server, fast.
    Setting ``SLIPWRIGHT_TEST_DATABASE_URL`` runs the *whole suite* against PostgreSQL
    instead, on a schema emptied before each test -- which is how the dialect-specific
    things (upserts, the tsvector index, a column called ``text``) get exercised by every
    test rather than only by the handful written for them.
    """
    url = os.environ.get("SLIPWRIGHT_TEST_DATABASE_URL", "")
    if not url:
        with JobStore(tmp_path / "jobs.sqlite3") as s:
            yield s
        return

    from sqlalchemy import text

    from slipwright.secrets import generate_key

    key = generate_key()
    scratch = JobStore(url, secret_key=key)
    with scratch.db.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    scratch.close()
    with JobStore(url, secret_key=key) as s:
        yield s


@pytest.fixture
def seed() -> Profile:
    """Example profile whose build and test commands always pass (see tests/pipeline.py)."""
    from tests.pipeline import full_seed

    return full_seed()
