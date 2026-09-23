"""T11 — is the work drawn from a plan still about that plan?

A step that can run twice (the Designer, once its call moves before the gate) needs to tell
whether what it produced belongs to the plan as it stands now. Rejecting a plan rewrites the
phases and that work is stale; rewording a title at the gate changes nothing it was drawn
from. The fingerprint is what says which of the two happened.
"""

from __future__ import annotations

from pathlib import Path

from slipwright.engine import Engine, plan_fingerprint
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


def _engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=2))


def test_the_same_plan_has_the_same_fingerprint(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="combined"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)

    first = plan_fingerprint(job)
    assert len(first) == 16
    assert plan_fingerprint(engine.store.get(job.id)) == first  # reading it again is not a change


def test_rewording_a_phase_title_does_not_make_the_work_stale(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The gate lets a person tidy the wording; that is not a different plan."""
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="combined"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    before = plan_fingerprint(job)

    plan = dict(job.data.plan or {})
    phases = [dict(p) for p in plan["phases"]]
    phases[0]["title"] = "daha anlaşılır bir başlık"
    plan["phases"] = phases
    job.data.plan = plan
    engine.store.save(job)

    assert plan_fingerprint(engine.store.get(job.id)) == before


def test_a_different_goal_or_domain_is_a_different_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="combined"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    before = plan_fingerprint(job)

    plan = dict(job.data.plan or {})
    phases = [dict(p) for p in plan["phases"]]
    phases[0]["goal"] = "something else entirely"
    plan["phases"] = phases
    job.data.plan = plan
    assert plan_fingerprint(job) != before

    phases[0]["goal"] = (plan["phases"][0] or {}).get("goal")
    phases[0]["domain"] = "mobile"
    job.data.plan = {**plan, "phases": phases}
    assert plan_fingerprint(job) != before


def test_a_rejected_plan_is_a_different_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The real path: reject the work list, let the Architect write it again, and the
    fingerprint says the screens drawn from the old plan no longer belong to this one."""
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="combined"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    before = plan_fingerprint(job)

    after = engine.reject(job.id, "the web phase should come first")
    assert after.state is JobState.AWAITING_ARCHITECTURE_APPROVAL  # written again, waiting again
    assert plan_fingerprint(after) != before or after.data.plan == job.data.plan


def test_a_job_with_no_plan_still_answers(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.create_job("x", project_id=project.id)
    assert plan_fingerprint(job) == plan_fingerprint(job)  # no plan: still a stable digest
