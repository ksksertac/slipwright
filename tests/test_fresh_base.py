"""A development starts from the repository as the host has it now.

The checkout is cloned once and pull requests are merged on the host, so its HEAD stays
where it was cloned. Every development used to branch from that HEAD: an Android app
merged two days before was not in the checkout the Product Owner and the Architect read,
so they planned to write it again from nothing -- and a mobile developer was paid to."""

from __future__ import annotations

import subprocess
from pathlib import Path

from slipwright.githost import GhHost
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import git as g
from tests.pipeline import FakeHost, full_engine, full_provider


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def _host_moves_on(repo: Path, tmp_path: Path) -> str:
    """Give ``repo`` an origin, then merge something there the checkout never sees.
    Returns the commit the host's main is at."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "origin", "main")
    elsewhere = tmp_path / "elsewhere"
    subprocess.run(["git", "clone", "-q", str(remote), str(elsewhere)], check=True)
    _git(elsewhere, "config", "user.email", "test@example.com")
    _git(elsewhere, "config", "user.name", "Test")
    (elsewhere / "App.tsx").write_bytes(b"export default function App() {}\n")
    _git(elsewhere, "add", "App.tsx")
    _git(elsewhere, "commit", "-q", "-m", "the app, merged on the host")
    _git(elsewhere, "push", "-q", "origin", "main")
    return g.head_commit(elsewhere)


def test_a_development_starts_from_what_was_merged_on_the_host(
    store: JobStore, repo: Path, tmp_path: Path, worktrees_root: Path, seed: Profile
) -> None:
    merged = _host_moves_on(repo, tmp_path)
    assert not (repo / "App.tsx").exists()  # the checkout itself never pulled it

    engine = full_engine(store, worktrees_root, seed, full_provider(seed), git_host=GhHost())
    job = engine.start(engine.create_job("build the APK on merge", repo).id)

    assert job.worktree_path is not None
    assert (job.worktree_path / "App.tsx").exists()  # what the agents read has the app
    assert job.data.base_commit == merged


def test_a_host_that_cannot_be_reached_does_not_stop_a_development(
    store: JobStore, repo: Path, tmp_path: Path, worktrees_root: Path, seed: Profile
) -> None:
    _git(repo, "remote", "add", "origin", str(tmp_path / "nowhere.git"))
    head = g.head_commit(repo)

    engine = full_engine(store, worktrees_root, seed, full_provider(seed), git_host=GhHost())
    job = engine.start(engine.create_job("build the APK on merge", repo).id)

    assert job.worktree_path is not None  # started, from the checkout as it is
    assert job.data.base_commit == head


def test_a_host_that_names_a_commit_the_checkout_lacks_is_not_branched_from(
    store: JobStore, repo: Path, tmp_path: Path, worktrees_root: Path, seed: Profile
) -> None:
    _git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    head = g.head_commit(repo)

    class Liar(FakeHost):
        def fetch(self, worktree: Path, branch: str) -> str | None:
            return "0" * 40

    engine = full_engine(store, worktrees_root, seed, full_provider(seed), git_host=Liar())
    job = engine.start(engine.create_job("build the APK on merge", repo).id)

    assert job.data.base_commit == head
