"""T11 — "try a different way": the other door out of a failed development.

`retry` continues from the step that failed, with the same plan and the same phase. That
is the right answer when the step was unlucky and the wrong one when the plan is what
failed: a phase whose scope cannot reach the error, a task nobody wrote down. Retrying
then walks into the same wall, which is what the person is looking at when they ask for it
to be done differently.

`replan` is that door. What the person wants tried instead goes to the Product Owner with
the failure beside it, the backlog is written again (and can gain the task it was missing),
the Architect plans the phases again, and both come back through the usual gates. It is a
partial start-over, not a new development: the worktree, the branch and every commit on it
stay where they are.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import EmptyApproval, NotAwaitingApproval
from slipwright.providers import ModelRequest, ProviderRefusalError
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


def _failed_in_a_phase(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> tuple[Any, Any]:
    """A development that got through planning and died building its only phase."""
    provider = full_provider(seed, phases=1)

    def boom(_req: ModelRequest) -> Any:
        raise ProviderRefusalError("the phase cannot be done as written")

    provider.replies[RoleName.BACKEND] = boom
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)
    assert job.state is JobState.FAILED
    return engine, job


def test_a_different_way_goes_back_to_the_plan_not_to_the_step(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, job = _failed_in_a_phase(store, repo, worktrees_root, seed)
    worktree, branch = job.worktree_path, job.branch

    job = engine.replan(job.id, "split the API phase in two", run=False)

    # back to the Product Owner, where the backlog is written again -- not to developing,
    # which is where a plain retry would have continued
    assert job.state is JobState.BACKLOG
    assert job.history[-1].note == "planning it a different way: split the API phase in two"
    assert job.data.phase_index == 0
    # nothing is thrown away: the same branch, the same worktree
    assert job.worktree_path == worktree and job.branch == branch


def test_the_agents_are_told_what_to_try_and_what_failed(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Planning it again around the same failure needs the failure in front of it."""
    engine, job = _failed_in_a_phase(store, repo, worktrees_root, seed)
    job = engine.replan(job.id, "let routing be exported in its own phase", run=False)

    assert job.data.feedback is not None
    assert "let routing be exported in its own phase" in job.data.feedback
    assert "planned a different way rather than tried again" in job.data.feedback
    assert "backend failed" in job.data.feedback  # the note the failure was recorded with


def test_the_counters_that_made_it_give_up_start_over(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, job = _failed_in_a_phase(store, repo, worktrees_root, seed)
    job = engine.replan(job.id, "try it differently", run=False)
    assert job.data.build_attempts == 0
    assert job.data.review_rounds == 0
    assert job.data.reject_rounds == 0
    assert job.data.ci_attempts == 0
    assert job.data.qa_stage == 1
    assert job.data.last_build_output is None


def test_it_runs_the_whole_way_through_on_the_new_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The point of the door is that the development finishes through it."""
    engine, job = _failed_in_a_phase(store, repo, worktrees_root, seed)
    # whatever was wrong with the phase is no longer wrong
    provider = engine.provider
    assert provider is not None
    provider.replies[RoleName.BACKEND] = full_provider(seed, phases=1).replies[RoleName.BACKEND]

    job = engine.replan(job.id, "smaller phases this time")
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL  # the usual gates, in order
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL


def test_only_a_failed_development_can_be_planned_again(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, job = _failed_in_a_phase(store, repo, worktrees_root, seed)
    with pytest.raises(EmptyApproval, match="what should be tried instead"):
        engine.replan(job.id, "   ", run=False)

    job = engine.replan(job.id, "differently", run=False)
    with pytest.raises(NotAwaitingApproval):
        engine.replan(job.id, "again", run=False)  # not failed any more


def test_replan_endpoint(store: JobStore, repo: Path, worktrees_root: Path, seed: Profile) -> None:
    engine, job = _failed_in_a_phase(store, repo, worktrees_root, seed)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        assert client.post(f"/api/jobs/{job.id}/replan", json={"note": ""}).status_code == 422
        resp = client.post(f"/api/jobs/{job.id}/replan", json={"note": "smaller phases"})
        assert resp.status_code == 200 and resp.json()["state"] == "backlog"
        assert client.post(f"/api/jobs/{job.id}/replan", json={"note": "x"}).status_code == 409


def test_the_third_door_is_offered_in_the_ui() -> None:
    from tests.test_phase9_review import WEB

    gate = (WEB / "src" / "components" / "GateActions.tsx").read_text(encoding="utf-8")
    assert "Try a different way" in gate and "ReplanModal" in gate
    tr = (WEB / "src" / "i18n" / "tr.ts").read_text(encoding="utf-8")
    assert "Farklı yol ile dene" in tr
