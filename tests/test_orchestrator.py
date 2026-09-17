from __future__ import annotations

from pathlib import Path

import pytest

from slipwright.orchestrator import IllegalTransitionError, Orchestrator
from slipwright.schemas.job import Job, JobState
from slipwright.store import JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs.sqlite3")


def _job(**overrides: object) -> Job:
    base: dict[str, object] = {"request": "ship a fix", "repo_path": Path("/repo")}
    base.update(overrides)
    return Job.model_validate(base)


def test_advance_persists_transition_before_side_effect(store: JobStore) -> None:
    orchestrator = Orchestrator(store)
    job = store.create(_job())
    seen: list[str] = []

    def side_effect(updated: Job) -> Job:
        seen.append(updated.state.value)
        return updated

    advanced = orchestrator.advance(
        job, JobState.BACKLOG, note="start analysis", side_effect=side_effect
    )

    assert advanced.state is JobState.BACKLOG
    assert advanced.history[-1].from_state is JobState.CREATED
    assert advanced.history[-1].to_state is JobState.BACKLOG
    assert advanced.history[-1].note == "start analysis"
    assert seen == ["backlog"]
    assert store.get(job.id).state is JobState.BACKLOG


def test_illegal_transition_rejected(store: JobStore) -> None:
    orchestrator = Orchestrator(store)
    job = store.create(_job())

    with pytest.raises(IllegalTransitionError, match="created.*architecture"):
        orchestrator.advance(job, JobState.ARCHITECTURE)


def test_resume_continues_from_persisted_state(store: JobStore) -> None:
    orchestrator = Orchestrator(store)
    job = store.create(_job())
    orchestrator.advance(job, JobState.BACKLOG)

    calls: list[JobState] = []

    def handle_analyzing(current: Job) -> Job:
        calls.append(current.state)
        return orchestrator.advance(current, JobState.AWAITING_BACKLOG_APPROVAL, note="analyst ok")

    resumed = orchestrator.resume(job.id, handlers={JobState.BACKLOG: handle_analyzing})

    assert resumed.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert calls == [JobState.BACKLOG]
