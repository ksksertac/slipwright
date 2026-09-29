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
from slipwright.store import JobNotFound, JobStore
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


def test_a_stopped_development_can_be_thrown_away(engine: Engine, repo: Path) -> None:
    """Stopping is what you do before deleting: a running development refuses to be
    deleted, and the whole point of stopping one is that it need not be kept."""
    job = engine.start(engine.create_job("health", repo).id)
    engine.cancel(job.id, by="ada")

    engine.delete_job(job.id)
    with pytest.raises(JobNotFound):
        engine.store.get(job.id)


def test_stop_is_offered_wherever_the_development_is() -> None:
    """It was offered only inside the gate block, which draws nothing while a phase is
    being built -- so the one moment somebody wants to stop a development, because it is
    running and spending, was the one moment there was no button. It is in the job's own
    header now, which is on screen in every state, and on the closed lane in the pipeline,
    which is where somebody watching it spend is actually looking."""
    web = Path(__file__).resolve().parent.parent / "web" / "src"
    header = (web / "pages" / "JobPage.tsx").read_text(encoding="utf-8")
    # the header holds it next to Delete: the two answers to "I do not want this"
    assert "<StopAction job={job} />\n          <DeleteJobButton" in header
    lane = (web / "pages" / "PipelineTab.tsx").read_text(encoding="utf-8")
    # on the lane whether it is open or shut: Retry hides when the lane is open because
    # the detail repeats it, and stopping has no twin inside to hide behind
    assert "<LaneStop jobId={lane.job_id} />" in lane
    assert "{!hasFinished(lane.state) && (" in lane
    assert "{!open && !hasFinished(lane.state) && (" not in lane
    # and Delete knows every terminal state, not two of the three: a development that was
    # stopped could not be deleted, though the server had always allowed it
    assert "if (!hasFinished(job.state)) return null;" in header
