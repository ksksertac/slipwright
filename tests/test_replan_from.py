"""A re-plan picks up where it failed. It used to start the development over: the
Architect wrote every phase again, the Designer drew every screen again, and the phases
already built and committed were built a second time -- to fix the last one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from slipwright.engine import EmptyApproval, Engine
from slipwright.roles import architect, designer
from slipwright.roles.results import PlanPhase
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import PY, full_engine, full_provider, past_design

# the build fails while a file called FAIL is in the checkout
GATE = f'"{PY}" -c "import os, sys; sys.exit(1 if os.path.exists(\'FAIL\') else 0)"'


def _context(request: Any) -> dict[str, Any]:
    text = request.prompt
    body = text[text.index("Context:\n") + len("Context:\n") : text.index("\n\nRespond with")]
    return dict(json.loads(body))


def _drive(engine: Engine, job: Job) -> Job:
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            return job
        job = past_design(engine, job)
        if job.state in APPROVAL_STATES:
            job = engine.approve(job.id)
    return job


def _scripted(seed: Profile, domains: list[str] | None = None) -> Any:
    """Three tasks; phase 2 as first planned breaks the build, and the re-plan splits it."""
    provider = full_provider(seed, phases=3, domains=domains)
    domain = (domains or ["general"])[0]
    first = provider.replies[RoleName.ARCHITECT]

    def plan(req: Any) -> dict[str, Any]:
        if "kept_phases" not in _context(req):
            return dict(first)  # type: ignore[arg-type]
        return {
            **first,  # type: ignore[dict-item]
            "summary": "phase 2 in two parts",
            "phases": [
                {
                    "goal": "step 2a",
                    "files": ["OK"],
                    "task_id": "t2",
                    "domain": domain,
                    "depends_on": [1],
                },
                {
                    "goal": "step 2b",
                    "files": ["OK"],
                    "task_id": "t2",
                    "domain": domain,
                    "depends_on": [2],
                },
                {
                    "goal": "step 3",
                    "files": ["OK"],
                    "task_id": "t3",
                    "domain": domain,
                    "depends_on": [3],
                },
            ],
        }

    provider.replies[RoleName.ARCHITECT] = plan
    built: list[str] = []

    def develop(req: Any) -> dict[str, Any]:
        goal = str(_context(req)["current_phase"]["goal"])
        built.append(goal)
        if goal == "step 2":
            return {"summary": "breaks it", "changes": [{"path": "FAIL", "content": "x\n"}]}
        return {
            "summary": goal,
            "changes": [
                {"path": "OK", "content": f"{goal} {len(built)}\n"},
                {"path": "FAIL", "content": None},
            ],
        }

    for role in (RoleName.BACKEND, RoleName.MOBILE_UI):
        provider.replies[role] = develop
    stage_one = provider.replies[RoleName.QA]

    def qa(req: Any) -> Any:
        if "A build gate failed on this branch" in req.prompt:
            return {"summary": "the code", "gate_verdict": "code_is_wrong"}
        return stage_one(req)  # type: ignore[operator]

    provider.replies[RoleName.QA] = qa
    return provider, built


def test_a_supervisors_replan_keeps_the_built_phases_and_may_split_one(
    store: JobStore,
    repo: Path,
    worktrees_root: Path,
    seed: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = seed.model_copy(update={"test_cmd": GATE})
    provider, built = _scripted(seed)
    engine = full_engine(store, worktrees_root, seed, provider)
    monkeypatch.setattr(engine, "_failed_gate_choice", lambda *a, **k: ("replan", "split it"))
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    asked = [_context(r) for r in provider.requests if r.role is RoleName.ARCHITECT]
    assert [p["goal"] for p in asked[-1]["kept_phases"]] == ["step 1"]
    replan = [r for r in provider.requests if r.role is RoleName.ARCHITECT][-1]
    assert "re-plan from phase 2" in replan.prompt
    plan = job.data.plan or {}
    assert [p["goal"] for p in plan["phases"]] == ["step 1", "step 2a", "step 2b", "step 3"]
    assert job.data.phase_index == 1  # it picks up at the first new phase

    job = _drive(engine, job)
    assert job.state is JobState.DONE
    assert built == ["step 1", "step 2", "step 2a", "step 2b", "step 3"]  # step 1 once
    tasks = {
        t["id"]: t.get("phase")
        for e in plan["breakdown"]["epics"]
        for s in e["stories"]
        for t in s["tasks"]
    }
    assert tasks == {"t1": 1, "t2": 3, "t3": 4}  # a split task is done with its last part


def test_a_replan_does_not_draw_screens_its_tasks_already_have(
    store: JobStore,
    repo: Path,
    worktrees_root: Path,
    seed: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = seed.model_copy(update={"test_cmd": GATE})
    provider, _built = _scripted(seed, domains=["mobile"])
    engine = full_engine(store, worktrees_root, seed, provider)
    monkeypatch.setattr(engine, "_failed_gate_choice", lambda *a, **k: ("replan", "split it"))
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)
    job = past_design(engine, job)
    if job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL:
        job = engine.approve(job.id)

    drawn = sum(1 for r in provider.requests if r.role is RoleName.DESIGNER)
    job = _drive(engine, job)
    assert job.state is JobState.DONE
    assert sum(1 for r in provider.requests if r.role is RoleName.DESIGNER) == drawn == 1


def test_a_phase_out_of_budget_can_be_planned_again_from_where_it_is(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=3)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(job.id, run=False)  # the backlog; the plan is drawn next
    job = engine.approve(engine._run(job).id, run=False)  # noqa: SLF001
    # as a phase-budget stop leaves it, two phases in
    job = store.get(job.id)
    job.data.phase_index = 1
    job.data.decision_kind = "phase_budget"
    job.data.recommendation = "split phase 2"
    job.data.resume_state = JobState.DEVELOPING.value
    store.save(job)
    store.update_state(job.id, JobState.AWAITING_DECISION, note="phase 2 took 8 model calls")

    with pytest.raises(EmptyApproval):
        engine.replan_phase(job.id, "  ")
    job = engine.replan_phase(job.id, "split phase 2 in two", run=False)

    assert job.state is JobState.ARCHITECTURE
    assert job.data.replan_from == 1 and job.data.phase_index == 1
    assert "split phase 2 in two" in (job.data.feedback or "")
    assert job.data.decision_kind is None


def test_a_task_may_take_several_phases_and_is_mapped_to_its_last() -> None:
    phases = [
        PlanPhase(goal="a", task_id="t1", files=["x"]),
        PlanPhase(goal="b, part 1", task_id="t2", files=["x"]),
        PlanPhase(goal="b, part 2", task_id="t2", files=["x"]),
    ]
    assert architect.phase_task_map(phases, ["t1", "t2"]) == {"t1": 1, "t2": 3}
    assert "no phase implements" in str(architect.phase_task_map(phases[:1], ["t1", "t2"]))


def test_only_a_task_with_no_screen_sends_the_designer_back(store: JobStore, repo: Path) -> None:
    job = Job(request="x", repo_path=repo)
    job.data.plan = {
        "phases": [
            {"goal": "a", "task_id": "t1", "domain": "mobile"},
            {"goal": "b", "task_id": "t2", "domain": "mobile"},
            {"goal": "c", "task_id": "t3", "domain": "backend"},
        ]
    }
    job.data.design = {"screens": [{"id": "s1", "task_id": "t1"}]}
    assert designer.unscreened(job) == ["t2"]
    assert designer.needs_drawing(job)
    job.data.design["screens"].append({"id": "s2", "task_id": "t2"})
    assert not designer.needs_drawing(job)
