"""Stopping a development, wherever it is.

Not a failure and not a step: the answer to "this is not worth what it is spending", which
can be true mid-phase or at a gate nobody is going to answer. What it cannot do is
interrupt a call already in flight -- the model is answering and that answer is already
paid for -- so it takes effect between steps.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine, NotAwaitingApproval
from slipwright.schemas.job import TERMINAL_STATES, JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_a_development_waiting_at_a_gate_stops_where_it_is(engine: Engine, repo: Path) -> None:
    job = engine.start(engine.create_job("health", repo).id)
    assert not job.is_terminal

    stopped = engine.cancel(job.id, by="ada")
    assert stopped.state is JobState.CANCELLED
    assert stopped.is_terminal, "it is over: nothing runs it again"
    assert "stopped by ada" in (stopped.history[-1].note or "")


def test_stopping_is_not_failing(engine: Engine, repo: Path) -> None:
    """A failure is offered a retry and counts against the project. This is neither."""
    job = engine.cancel(engine.start(engine.create_job("health", repo).id).id)
    assert job.state is not JobState.FAILED
    assert JobState.CANCELLED in TERMINAL_STATES
    with pytest.raises(NotAwaitingApproval):
        engine.retry(job.id)


def test_what_it_built_is_still_there(engine: Engine, repo: Path) -> None:
    """Stopping is not undoing: the branch and everything on it stay."""
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.approve(engine.start(engine.create_job("health", project_id=project.id).id).id)
    backlog = job.data.backlog
    assert backlog, "this test wants a development that has produced something"

    stopped = engine.cancel(job.id)
    assert stopped.data.backlog == backlog
    assert stopped.branch == job.branch


def test_it_cannot_be_stopped_twice(engine: Engine, repo: Path) -> None:
    job = engine.cancel(engine.start(engine.create_job("health", repo).id).id)
    with pytest.raises(NotAwaitingApproval):
        engine.cancel(job.id)


def test_the_endpoint_stops_it_and_refuses_afterwards(
    client: TestClient, engine: Engine, repo: Path
) -> None:
    job = engine.start(engine.create_job("health", repo).id)
    stopped = client.post(f"/api/jobs/{job.id}/cancel")
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["state"] == "cancelled"
    assert client.post(f"/api/jobs/{job.id}/cancel").status_code == 409
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_the_groups_are_told(engine: Engine, repo: Path) -> None:
    """Whoever was watching it spend is told it has stopped spending."""
    told: list[tuple[str, str]] = []
    import slipwright.engine as engine_module

    original = engine_module.notify_outcome
    engine_module.notify_outcome = lambda eng, job, kind, error=None: told.append(  # type: ignore[assignment]
        (kind, error or "")
    )
    try:
        engine.cancel(engine.start(engine.create_job("health", repo).id).id, by="ada")
    finally:
        engine_module.notify_outcome = original  # type: ignore[assignment]

    assert told and told[0][0] == "cancelled", "not announced as a failure"
    assert "stopped by ada" in told[0][1]
