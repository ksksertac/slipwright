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
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


@pytest.fixture
def seed() -> Profile:
    """Example profile whose build and test commands always pass (see tests/pipeline.py)."""
    from tests.pipeline import full_seed

    return full_seed()
