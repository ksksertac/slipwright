"""T14.2: what nothing here can build waits for a machine that can -- deferred, never
failed -- and everything else goes on meanwhile."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from slipwright.board import job_epics
from slipwright.engine import Engine
from slipwright.gates import toolchains
from slipwright.pipeline import lane_for
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import PlatformCommands, Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import TRUE, full_engine, full_provider

IOS_BUILD = TRUE.replace("print(1)", "print('ios-built')")


@pytest.fixture(autouse=True)
def _no_xcode_here(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever machine runs the tests, it cannot build iOS unless a test says so."""
    monkeypatch.setattr(toolchains, "can_build", lambda platform, *a, **k: False)


def _with_ios(seed: Profile) -> Profile:
    return seed.model_copy(
        update={"platforms": [PlatformCommands(platform="ios", build_cmd=IOS_BUILD, test_cmd=TRUE)]}
    )


def _provider(seed: Profile, domains: list[str], ios_at: int) -> Any:
    provider = full_provider(seed, phases=len(domains), domains=domains)
    provider.replies[RoleName.ARCHITECT]["phases"][ios_at]["platform"] = "ios"
    return provider


def _drive(engine: Engine, job: Job) -> Job:
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            return job
        job = engine.approve(job.id)
    raise AssertionError(f"still at {job.state}")


def _lend_ios(engine: Engine, owner: str | None = None) -> None:
    """A Mac of ``owner``'s is there -- as far as deciding what to wake goes. Nothing is
    sent to it: the tests that use this only look at who would be woken."""
    engine.remote_platforms = lambda asked: frozenset({"ios"}) if asked == owner else frozenset()  # type: ignore[method-assign]


def _can_build_ios_here(monkeypatch: pytest.MonkeyPatch) -> None:
    """This machine itself becomes one that builds iOS: a server started again on a Mac.
    A worker building it remotely is T14.3's to show (test_phase14_workers)."""
    monkeypatch.setattr(toolchains, "can_build", lambda platform, *a, **k: platform == "ios")


def test_the_rest_is_built_and_the_ios_phase_waits_for_a_mac(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    seed = _with_ios(seed)
    engine = full_engine(store, worktrees_root, seed, _provider(seed, ["backend", "mobile"], 1))
    job = _drive(engine, engine.start(engine.create_job("an api and an app", repo).id))

    assert job.state is JobState.AWAITING_BUILDER
    assert job.data.waiting_platforms == ["ios"]
    assert job.data.phase_index == 1  # the backend phase is built and committed
    assert job.data.build_attempts == 0  # waiting is not a failed attempt
    assert "waiting for a builder: phase 2/2 and after need ios" in (job.history[-1].note or "")
    assert not [r for r in engine.provider.requests if r.role is RoleName.MOBILE_UI]
    statuses = [t.status.value for e in job_epics(job) for s in e.stories for t in s.tasks]
    assert statuses == ["done", "todo"]  # the app's task is still to do, not failed
    lane = lane_for(job)
    card = next(s for s in lane.steps if s.key == "builder_gate")
    assert card.status.value == "waiting" and card.label == "Waiting for a Mac: iOS"
    keys = [s.key for s in lane.steps]
    assert keys.index("builder_gate") == keys.index("phase:2") - 1
    assert lane.pending_approval is None  # nobody can approve a Mac into existence


def test_a_builder_arriving_carries_the_development_on(
    store: JobStore,
    repo: Path,
    worktrees_root: Path,
    seed: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = _with_ios(seed)
    engine = full_engine(store, worktrees_root, seed, _provider(seed, ["backend", "mobile"], 1))
    job = _drive(engine, engine.start(engine.create_job("an api and an app", repo).id))
    assert engine.waiting_for_builders(None) == []  # still nothing that can build it

    _can_build_ios_here(monkeypatch)
    assert engine.waiting_for_builders(None) == [job.id]
    job = _drive(engine, engine.resume(job.id))

    assert job.state is JobState.DONE
    assert any("a builder for ios is here" in (t.note or "") for t in job.history)
    assert "ios-built" in next(
        t.detail or "" for t in job.history if t.note == "build gate passed for phase 2/2"
    )
    assert next(s for s in lane_for(job).steps if s.key == "builder_gate").status.value == "done"


def test_the_ios_phase_goes_last_so_the_rest_is_not_held_up(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    seed = _with_ios(seed)
    provider = _provider(seed, ["mobile", "backend", "backend"], 0)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _drive(engine, engine.start(engine.create_job("an app first", repo).id))

    assert job.state is JobState.AWAITING_BUILDER
    phases = (job.data.plan or {})["phases"]
    assert [p.get("platform") for p in phases] == [None, None, "ios"]
    assert job.data.phase_index == 2  # both backend phases built
    assert any("1 phase(s) wait until last" in (t.note or "") for t in job.history)
    # the board follows the new order: the backend tasks are done, the app's is not
    statuses = {t.id: t.status.value for e in job_epics(job) for s in e.stories for t in s.tasks}
    assert statuses == {"t1": "todo", "t2": "done", "t3": "done"}


def test_another_accounts_mac_never_wakes_the_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    seed = _with_ios(seed)
    engine = full_engine(store, worktrees_root, seed, _provider(seed, ["backend", "mobile"], 1))
    job = _drive(engine, engine.start(engine.create_job("an api and an app", repo).id))

    _lend_ios(engine, owner="somebody-else")
    assert engine.waiting_for_builders(None) == []
    assert engine.waiting_for_builders("somebody-else") == []
    assert engine.resume(job.id).state is JobState.AWAITING_BUILDER  # a restart changes nothing


def test_the_wait_is_announced_once(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    seed = _with_ios(seed)
    engine = full_engine(store, worktrees_root, seed, _provider(seed, ["backend", "mobile"], 1))
    job = _drive(engine, engine.start(engine.create_job("an api and an app", repo).id))
    job = engine.resume(job.id)
    assert job.data.notified.count("awaiting_builder:1") == 1
