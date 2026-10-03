"""Deleting a development: everywhere it reached, and kept to be read.

The delete that came before took the rows away and left the host as it was -- the branch,
the draft pull request, and the code itself once somebody had merged it. Deleting a
development now takes those back: the pull request is closed, the branch deleted, what was
merged reverted on the base branch, its Jira issues moved to Won't Do. The development
stays in the list, marked deleted, and nothing moves it again.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine, JobRemoved
from slipwright.githost import GhHost
from slipwright.jira import JiraClient, JiraTransition
from slipwright.pipeline import lane_for
from slipwright.providers.scripted import ScriptedProvider
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.store.sqlite import JobInProgress
from tests.pipeline import full_engine, full_provider
from tests.test_pause import _git, _paused_in_phase_one, _with_origin


class Host(GhHost):
    """Pushes, fetches and deletes for real against a bare repository; the pull request
    is the one part ``gh`` would do, so it is played here."""

    def __init__(self) -> None:
        super().__init__(token=None)
        self.closed: list[str] = []
        self.squashed: str | None = None

    def close_pr(self, worktree: Path, pr_url: str) -> bool:
        self.closed.append(pr_url)
        return True

    def merged_commit(self, worktree: Path, pr_url: str) -> str | None:
        return self.squashed


@pytest.fixture
def provider(seed: Profile) -> ScriptedProvider:
    return full_provider(seed, phases=3)


@pytest.fixture
def host() -> Host:
    return Host()


@pytest.fixture
def engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider, host: Host
) -> Engine:
    return full_engine(store, worktrees_root, seed, provider, git_host=host)


def _person(bare: Path, name: str) -> Path:
    """Somebody's own clone of the project, ready to commit."""
    person = bare.parent / name
    subprocess.run(["git", "clone", "-q", str(bare), str(person)], check=True)
    _git(person, "config", "user.email", "dev@example.com")
    _git(person, "config", "user.name", "Dev")
    _git(person, "config", "core.autocrlf", "false")
    return person


def _merged(bare: Path, branch: str, *, squash: bool = False) -> str:
    """Somebody merges the development's pull request into main; returns main's tip."""
    person = _person(bare, "merger")
    _git(person, "fetch", "-q", "origin", branch)
    if squash:
        _git(person, "merge", "-q", "--squash", "FETCH_HEAD")
        _git(person, "commit", "-q", "-m", "the app (#1)")
    else:
        _git(person, "merge", "-q", "--no-ff", "-m", "Merge pull request #1", "FETCH_HEAD")
    _git(person, "push", "-q", "origin", "main")
    return _git(person, "rev-parse", "HEAD").strip()


def _paused_and_pushed(engine: Engine, provider: ScriptedProvider, repo: Path) -> Job:
    job = _paused_in_phase_one(engine, provider, repo, push=True)
    assert job.state is JobState.PAUSED
    assert (job.data.pause or {}).get("pushed"), "the branch went to the host"
    # as the first phase's own push would have opened it
    job.data.draft_pr_url = "https://github.com/acme/app/pull/1"
    return engine.store.save(job)


def test_a_paused_development_is_deleted_and_stays_to_be_read(
    engine: Engine, provider: ScriptedProvider, repo: Path, host: Host
) -> None:
    bare = _with_origin(repo)
    job = _paused_and_pushed(engine, provider, repo)
    draft = job.data.draft_pr_url
    assert draft and _git(bare, "branch", "--list", job.branch).strip()

    removed = engine.remove_job(job.id, by="ada")

    assert removed.state is JobState.CANCELLED, "no longer paused: nothing carries it on"
    assert removed.is_removed
    assert removed.data.removed is not None
    assert removed.data.removed["by"] == "ada"
    assert "deleted by ada" in (removed.history[-1].note or "")
    assert host.closed == [draft], "its pull request is closed"
    assert removed.data.removed["branch_deleted"] is True
    assert not _git(bare, "branch", "--list", job.branch).strip(), "its branch is gone"
    assert removed.worktree_path is None and not (engine.workspace.worktrees_root / job.id).exists()
    assert not _git(repo, "branch", "--list", job.branch).strip()
    assert lane_for(removed).removed is True
    # the base branch was never touched: nothing of it had been merged
    assert _git(bare, "log", "--format=%s", "main").strip() == "initial"


def test_nothing_moves_a_deleted_development_again(
    engine: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    _with_origin(repo)
    job = engine.remove_job(_paused_and_pushed(engine, provider, repo).id)

    with pytest.raises(JobRemoved):
        engine.retry(job.id)
    with pytest.raises(JobRemoved):
        engine.replan(job.id, "try it another way")
    with pytest.raises(JobRemoved):
        engine.rerun(job.id, "tests")
    with pytest.raises(JobRemoved):
        engine.carry_on(job.id)
    with pytest.raises(JobRemoved):
        engine.remove_job(job.id)
    assert engine.store.get(job.id).state is JobState.CANCELLED


def test_a_development_that_is_still_going_is_not_deleted(engine: Engine, repo: Path) -> None:
    job = engine.start(engine.create_job("health", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL

    with pytest.raises(JobInProgress):
        engine.remove_job(job.id)
    assert not engine.store.get(job.id).is_removed


def test_a_finished_development_keeps_its_state_and_is_marked_deleted(
    engine: Engine, repo: Path
) -> None:
    job = engine.cancel(engine.start(engine.create_job("health", repo).id).id)
    assert job.state is JobState.CANCELLED

    removed = engine.remove_job(job.id, by="ada")
    assert removed.state is JobState.CANCELLED and removed.is_removed
    assert removed.data.removed is not None and removed.data.removed["errors"] == []


def test_work_merged_into_main_is_reverted_there(
    engine: Engine, provider: ScriptedProvider, repo: Path, host: Host
) -> None:
    bare = _with_origin(repo)
    job = _paused_and_pushed(engine, provider, repo)
    merged = _merged(bare, job.branch)
    assert _git(bare, "show", "main:OK") == "yes\n", "the phase is on main"

    removed = engine.remove_job(job.id, by="ada")

    report = removed.data.removed or {}
    assert report["errors"] == []
    assert report["reverted"]["onto"] == "main"
    tip = _git(bare, "rev-parse", "main").strip()
    assert tip == report["reverted"]["commit"]
    assert _git(bare, "rev-parse", f"{tip}^").strip() == merged, "on top, never forced"
    assert "OK" not in _git(bare, "ls-tree", "--name-only", "main").split()
    assert "deleted in Slipwright by ada" in _git(bare, "log", "-1", "--format=%B", "main")
    assert host.closed == [], "a merged pull request has nothing to close"
    assert not _git(bare, "branch", "--list", job.branch).strip()


def test_a_squash_merge_is_reverted_through_the_commit_the_host_made(
    engine: Engine, provider: ScriptedProvider, repo: Path, host: Host
) -> None:
    bare = _with_origin(repo)
    job = _paused_and_pushed(engine, provider, repo)
    host.squashed = _merged(bare, job.branch, squash=True)

    removed = engine.remove_job(job.id)

    report = removed.data.removed or {}
    assert report["errors"] == [] and report["reverted"]["commits"] == 1
    assert "OK" not in _git(bare, "ls-tree", "--name-only", "main").split()


def test_a_revert_that_clashes_with_later_work_is_reported_not_forced(
    engine: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    bare = _with_origin(repo)
    job = _paused_and_pushed(engine, provider, repo)
    _merged(bare, job.branch)
    later = _person(bare, "later")
    (later / "OK").write_bytes(b"changed after the merge\n")
    _git(later, "commit", "-q", "-am", "built on it")
    _git(later, "push", "-q", "origin", "main")
    before = _git(bare, "rev-parse", "main").strip()

    removed = engine.remove_job(job.id)

    report = removed.data.removed or {}
    assert removed.is_removed, "deleted all the same"
    assert report["reverted"] is None
    assert any("main was not reverted" in e and "OK" in e for e in report["errors"])
    assert _git(bare, "rev-parse", "main").strip() == before, "main is left as it was"
    assert "not done: main was not reverted" in (removed.history[-1].detail or "")


class _Jira(JiraClient):
    """A board offering the moves in ``offered`` per issue, recording what is sent."""

    def __init__(self, offered: dict[str, list[str]]) -> None:
        self.offered = offered
        self.moved: list[tuple[str, str]] = []
        self.calls = 0

    def transitions(self, key: str) -> list[JiraTransition]:
        self.calls += 1
        return [
            JiraTransition(id=str(i), name=n) for i, n in enumerate(self.offered.get(key, []))
        ]

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        self.calls += 1
        self.moved.append((path.split("/")[-2], kw["json"]["transition"]["id"]))
        return httpx.Response(204)


def test_its_jira_issues_are_moved_to_wont_do_and_hear_nothing_more(
    engine: Engine, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = engine.cancel(engine.start(engine.create_job("health", repo).id).id)
    job.data.jira_keys = {"e1": "APP-1", "s1": "APP-2"}
    engine.store.save(job)
    jira = _Jira({"APP-1": ["Start", "Won’t Do"], "APP-2": ["Start", "Done"]})

    class Sync:
        client = jira
        project = type("P", (), {"jira_transitions": {}})()

    monkeypatch.setattr(engine, "_jira_sync_for", lambda job: Sync())
    removed = engine.remove_job(job.id)

    report = removed.data.removed or {}
    assert report["jira_closed"] == ["APP-1"], "Won't Do, whichever apostrophe the board uses"
    assert report["jira_left"] == ["APP-2"], "never Done: the work was not done"
    assert jira.moved == [("APP-1", "1")]
    calls = jira.calls
    engine._jira_reconcile(engine.store.get(job.id))
    assert jira.calls == calls, "nothing further is sent"


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_the_endpoint_deletes_and_every_action_after_it_is_refused(
    client: TestClient, engine: Engine, repo: Path
) -> None:
    going = engine.start(engine.create_job("health", repo).id)
    assert client.post(f"/api/jobs/{going.id}/remove").status_code == 409

    paused = client.post(f"/api/jobs/{going.id}/pause", json={"push": False})
    assert paused.json()["state"] == "paused"
    gone = client.post(f"/api/jobs/{going.id}/remove")
    assert gone.status_code == 200, gone.text
    body: dict[str, Any] = gone.json()
    assert body["state"] == "cancelled" and body["data"]["removed"] is not None

    assert client.post(f"/api/jobs/{going.id}/remove").status_code == 409
    for action, payload in [
        ("carry-on", {}),
        ("retry", {}),
        ("replan", {"note": "another way"}),
        ("rerun", {"step": "tests"}),
        ("message", {"text": "hello"}),
    ]:
        refused = client.post(f"/api/jobs/{going.id}/{action}", json=payload)
        assert refused.status_code == 409, (action, refused.text)
    assert client.get(f"/api/jobs/{going.id}").status_code == 200, "still there to read"
    assert client.post("/api/jobs/nope/remove").status_code == 404
