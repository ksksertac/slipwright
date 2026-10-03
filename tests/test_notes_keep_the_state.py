"""A note in a development's history never moves it.

A phase written ahead (T16.3) runs on a copy of the job taken while it was developing. Its
retry note was written as a move to the state that copy held, so while the run had gone on
to review, the job was put back in developing -- and the run's next save crashed it:
"review crashed: save() cannot change state (developing -> review)".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slipwright.engine import Engine
from slipwright.invoke import InvokeError, InvokeErrorKind, RoleResult
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


def _engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=2))


def test_a_retry_note_from_an_old_copy_leaves_the_job_where_the_run_has_it(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    # the copy a phase written ahead holds: taken when the job was somewhere else
    old = job.model_copy(deep=True)
    old.state = JobState.DEVELOPING
    answers = iter(
        [
            InvokeError(kind=InvokeErrorKind.PROVIDER_ERROR, message="overloaded"),
            None,
        ]
    )

    def run(job: Any, **_: Any) -> RoleResult:
        error = next(answers)
        return RoleResult(
            role=RoleName.BACKEND,
            model="m",
            thinking_depth=ThinkingDepth.OFF,
            error=error,
            raw_text=None if error else "{}",
        )

    engine._call_with_retries(RoleName.BACKEND, run, old, retries=1)

    now = engine.store.get(job.id)
    assert now.state is JobState.AWAITING_BACKLOG_APPROVAL, "the note moved nothing"
    assert "attempt 1 failed: provider_error" in (now.history[-1].note or "")
    assert now.history[-1].from_state is now.history[-1].to_state
    engine.store.save(job)  # the run's own save, which used to crash here


def test_a_note_is_written_at_the_state_the_job_is_in(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = engine.start(engine.create_job("x", repo).id)

    noted = engine.store.note(job.id, "jira: 2 update(s)", "APP-1, APP-2")

    assert noted.state is job.state
    assert noted.history[-1].note == "jira: 2 update(s)"
    assert noted.history[-1].from_state is noted.history[-1].to_state is job.state
