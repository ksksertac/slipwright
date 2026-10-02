"""Pausing a development so people can work on its branch, and carrying it on after.

Stopping is for good; this is not. A paused development keeps its place -- the state, the
phase, the commit -- and carries on from there when the person who paused it says so:
as it was, or with what people pushed to the branch meanwhile. When there are phases left
to build, what they pushed is read against the plan first, so a phase somebody finished
by hand is not built a second time.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import (
    CannotSync,
    Engine,
    NotAwaitingApproval,
    PullConflict,
    RemoteMoved,
)
from slipwright.githost import GhHost
from slipwright.orchestrator import IllegalTransitionError
from slipwright.pipeline import StepStatus, lane_for
from slipwright.providers import ModelRequest
from slipwright.providers.scripted import ScriptedProvider
from slipwright.roles.specialists import DEVELOPER_ROLES
from slipwright.schemas.job import TERMINAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def _with_origin(repo: Path) -> Path:
    """Give the fixture repository a remote to push to, the way a cloned project has."""
    bare = repo.parent / "origin.git"
    subprocess.run(["git", "clone", "--bare", "-q", str(repo), str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "fetch", "-q", "origin")
    return bare


def _somebody_works_on(
    bare: Path, branch: str, files: dict[str, str], *, new: bool = False
) -> None:
    """A person checks the branch out somewhere else, writes ``files`` and pushes."""
    person = bare.parent / f"person-{len(list(bare.parent.glob('person-*')))}"
    subprocess.run(["git", "clone", "-q", str(bare), str(person)], check=True)
    _git(person, "config", "user.email", "dev@example.com")
    _git(person, "config", "user.name", "Dev")
    _git(person, "config", "core.autocrlf", "false")
    _git(person, "checkout", "-q", *(["-b", branch] if new else [branch]))
    for name, text in files.items():
        (person / name).write_bytes(text.encode())
    _git(person, "add", "-A")
    _git(person, "commit", "-q", "-m", "by hand")
    _git(person, "push", "-q", "origin", branch)


def _developer_calls(provider: ScriptedProvider) -> int:
    return sum(1 for r in provider.requests if r.role in DEVELOPER_ROLES)


def _paused_in_phase_one(
    engine: Engine, provider: ScriptedProvider, repo: Path, *, push: bool
) -> Job:
    """A development paused while its first phase's specialist was answering -- from the
    page, so the pause arrives with the call in flight."""
    job = engine.create_job("health", repo)
    developer = provider.replies[next(iter(DEVELOPER_ROLES))]

    def answer(request: ModelRequest) -> Any:
        if _developer_calls(provider) == 1:
            engine.pause(job.id, push=push, by="ada")
        return developer

    for role in DEVELOPER_ROLES:
        provider.replies[role] = answer
    job = engine.approve(engine.start(job.id).id)  # the backlog
    return engine.approve(job.id)  # the plan: the first phase starts and is paused


@pytest.fixture
def provider(seed: Profile) -> ScriptedProvider:
    return full_provider(seed, phases=3)


@pytest.fixture
def engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider
) -> Engine:
    return full_engine(store, worktrees_root, seed, provider)


@pytest.fixture
def hosted(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider
) -> Engine:
    """An engine that pushes and pulls for real, to a bare repository beside the fixture."""
    return full_engine(store, worktrees_root, seed, provider, git_host=GhHost(token=None))


def test_a_paused_development_waits_where_it_was_and_carries_on_from_there(
    engine: Engine, repo: Path
) -> None:
    job = engine.approve(engine.start(engine.create_job("health", repo).id).id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL

    paused = engine.pause(job.id, by="ada")
    assert paused.state is JobState.PAUSED
    assert paused.state not in TERMINAL_STATES, "paused is not over"
    assert "paused by ada" in (paused.history[-1].note or "")
    with pytest.raises(NotAwaitingApproval):
        engine.approve(job.id)  # the gate it was paused at is not open while paused

    carried = engine.carry_on(job.id, by="ada")
    assert carried.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert carried.data.plan == job.data.plan


def test_a_pause_waits_for_the_call_in_flight_and_nothing_further_is_asked(
    engine: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    job = _paused_in_phase_one(engine, provider, repo, push=False)
    assert job.state is JobState.PAUSED
    assert _developer_calls(provider) == 1
    assert (job.data.pause or {})["from_state"] == JobState.BUILD_GATE.value
    assert job.worktree_path is not None
    assert (job.worktree_path / "OK").exists(), "what the call in flight wrote is kept"

    job = engine.carry_on(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL, "every phase built, QA asks next"
    assert _developer_calls(provider) == 3, "the paused phase was not written twice"


def test_a_paused_development_is_not_carried_on_by_the_server_starting(
    engine: Engine, repo: Path
) -> None:
    job = engine.pause(engine.start(engine.create_job("health", repo).id).id)
    engine.resume_all()
    assert engine.store.get(job.id).state is JobState.PAUSED


def test_a_paused_development_can_still_be_stopped_for_good(engine: Engine, repo: Path) -> None:
    job = engine.pause(engine.start(engine.create_job("health", repo).id).id)
    assert engine.cancel(job.id).state is JobState.CANCELLED
    with pytest.raises(NotAwaitingApproval):
        engine.carry_on(job.id)


def test_a_paused_development_is_not_re_run_around_its_carry_on(
    engine: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    """A re-run would carry it on without asking whether anybody pushed meanwhile."""
    job = _paused_in_phase_one(engine, provider, repo, push=False)
    with pytest.raises(IllegalTransitionError):
        engine.rerun(job.id, "tests")
    assert engine.store.get(job.id).state is JobState.PAUSED


def test_it_cannot_be_paused_twice_or_carried_on_unpaused(engine: Engine, repo: Path) -> None:
    job = engine.pause(engine.start(engine.create_job("health", repo).id).id)
    with pytest.raises(NotAwaitingApproval):
        engine.pause(job.id)
    engine.carry_on(job.id)
    with pytest.raises(NotAwaitingApproval):
        engine.carry_on(job.id)


def test_a_push_is_refused_where_there_is_nowhere_to_push(engine: Engine, repo: Path) -> None:
    job = engine.start(engine.create_job("health", repo).id)
    with pytest.raises(CannotSync, match="no remote"):
        engine.pause(job.id, push=True)
    assert engine.store.get(job.id).state is not JobState.PAUSED, "refused, not half done"


def test_pausing_with_a_push_sends_the_half_written_phase(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    """A phase is committed only once its build passes; people picking the branch up need
    what the specialist had written so far, so that goes too."""
    bare = _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    pause = job.data.pause or {}
    assert pause["pushed"] and not pause["push_error"]
    assert _git(bare, "show", f"{job.branch}:OK") == "yes\n"


def test_carrying_on_without_a_pull_builds_the_phase_as_if_it_had_never_stopped(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    job = hosted.carry_on(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert job.worktree_path is not None
    subjects = _git(job.worktree_path, "log", "--format=%s")
    assert "work in progress" not in subjects, "the commit made for the push was taken back"
    assert "slipwright: phase 1: step 1" in subjects


def test_carrying_on_without_a_pull_is_refused_when_somebody_pushed(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    """Building beside commits it has never seen would have its last push refused, after
    every phase had been paid for."""
    bare = _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    _somebody_works_on(bare, job.branch, {"HAND": "done by hand\n"})

    assert hosted.sync_status(job.id)["moved"] is True
    with pytest.raises(RemoteMoved):
        hosted.carry_on(job.id)
    assert hosted.store.get(job.id).state is JobState.PAUSED


def _reads(provider: ScriptedProvider, statuses: list[str]) -> None:
    provider.discovery["reconcile"] = {
        "summary": "somebody wrote the first two steps",
        "phases": [
            {"number": n, "status": s, "evidence": "HAND"} for n, s in enumerate(statuses, 1)
        ],
    }


def test_phases_finished_by_hand_are_not_built_again(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    bare = _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    _somebody_works_on(bare, job.branch, {"HAND": "steps one and two\n"})
    _reads(provider, ["done", "done", "untouched"])
    asked = _developer_calls(provider)

    job = hosted.carry_on(job.id, pull=True)
    assert job.state is JobState.AWAITING_RECONCILE_APPROVAL, "a person approves the reading"
    assert (job.data.reconcile or {})["resume_phase"] == 3
    assert job.worktree_path is not None
    assert (job.worktree_path / "HAND").read_text() == "steps one and two\n"

    job = hosted.approve(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert _developer_calls(provider) == asked + 1, "only the third phase was built"
    assert set(job.data.phase_outcomes) == {"1", "2"}
    lane = lane_for(job)
    by_hand = {c.key for c in lane.steps if c.by_hand}
    assert by_hand == {"phase:1", "phase:2"}


def test_a_phase_finished_after_one_that_was_not_is_built_again(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    """The phase before it may still change what it needs: only an unbroken run of
    finished phases is passed over."""
    bare = _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    _somebody_works_on(bare, job.branch, {"HAND": "step two\n"})
    _reads(provider, ["partial", "done", "untouched"])

    job = hosted.carry_on(job.id, pull=True)
    assert (job.data.reconcile or {})["resume_phase"] == 1
    job = hosted.approve(job.id)
    assert job.data.phase_outcomes == {}
    told = [m.text for m in job.data.inbox]
    assert any("partly written already" in t for t in told), "its specialist was told"


def test_a_reading_sent_back_is_read_again_with_what_was_said(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    bare = _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    _somebody_works_on(bare, job.branch, {"HAND": "x\n"})
    _reads(provider, ["done", "done", "done"])
    job = hosted.carry_on(job.id, pull=True)

    _reads(provider, ["done", "untouched", "untouched"])
    job = hosted.reject(job.id, "step two is not finished")
    assert job.state is JobState.AWAITING_RECONCILE_APPROVAL
    assert (job.data.reconcile or {})["resume_phase"] == 2
    assert "step two is not finished" in provider.requests[-1].prompt


def test_every_phase_finished_by_hand_goes_straight_to_qa(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    bare = _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    _somebody_works_on(bare, job.branch, {"HAND": "all of it\n"})
    _reads(provider, ["done", "done", "done"])
    asked = _developer_calls(provider)

    job = hosted.approve(hosted.carry_on(job.id, pull=True).id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert _developer_calls(provider) == asked


def test_a_pull_with_nothing_new_carries_on_as_it_was(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=True)
    job = hosted.carry_on(job.id, pull=True)
    assert job.state is JobState.AWAITING_TEST_APPROVAL, "no reading: nothing was pushed"
    assert "nothing new had been pushed" in " ".join(t.note or "" for t in job.history)


def test_a_conflicting_pull_leaves_it_paused_and_its_work_where_it_was(
    hosted: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    bare = _with_origin(repo)
    job = _paused_in_phase_one(hosted, provider, repo, push=False)
    # somebody started the same branch on their own and wrote the same file differently
    _somebody_works_on(bare, job.branch, {"OK": "no\n"}, new=True)

    with pytest.raises(PullConflict) as caught:
        hosted.carry_on(job.id, pull=True)
    assert caught.value.files == ["OK"]
    job = hosted.store.get(job.id)
    assert job.state is JobState.PAUSED
    assert job.worktree_path is not None
    assert (job.worktree_path / "OK").read_text() == "yes\n"
    assert _git(job.worktree_path, "status", "--porcelain").strip() == "A  OK"


def test_the_lane_shows_where_it_was_paused(
    engine: Engine, provider: ScriptedProvider, repo: Path
) -> None:
    job = _paused_in_phase_one(engine, provider, repo, push=False)
    lane = lane_for(job)
    assert lane.state is JobState.PAUSED
    assert [c.key for c in lane.steps if c.status is StepStatus.PAUSED] == ["phase:1"]
    assert lane.running_key is None


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_the_endpoints_pause_and_carry_on(client: TestClient, engine: Engine, repo: Path) -> None:
    job = engine.start(engine.create_job("health", repo).id)

    sync = client.get(f"/api/jobs/{job.id}/sync").json()
    assert sync["can_push"] is False and "no remote" in sync["why_not"]
    assert client.post(f"/api/jobs/{job.id}/pause", json={"push": True}).status_code == 409

    paused = client.post(f"/api/jobs/{job.id}/pause", json={"push": False})
    assert paused.status_code == 200, paused.text
    assert paused.json()["state"] == "paused"
    assert client.post(f"/api/jobs/{job.id}/pause").status_code == 409

    carried = client.post(f"/api/jobs/{job.id}/carry-on", json={"pull": False})
    assert carried.status_code == 200, carried.text
    assert carried.json()["state"] == "awaiting_backlog_approval"
    assert client.post(f"/api/jobs/{job.id}/carry-on").status_code == 409
    assert client.post("/api/jobs/nope/pause").status_code == 404
