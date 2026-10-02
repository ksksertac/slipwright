"""A phase that spends its budget waits aside while the phases that need nothing of it go
on; the person is asked about it when its turn comes again."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import BudgetSettings, Project
from slipwright.store import JobStore
from slipwright.workspace import git as g
from tests.pipeline import PY, full_engine, full_provider

# the build fails while a file called FAIL is in the checkout
GATE = f'"{PY}" -c "import os, sys; sys.exit(1 if os.path.exists(\'FAIL\') else 0)"'


def _context(request: Any) -> dict[str, Any]:
    text = request.prompt
    body = text[text.index("Context:\n") + len("Context:\n") : text.index("\n\nRespond with")]
    return dict(json.loads(body))


def _drive(engine, job: Job) -> Job:  # type: ignore[no-untyped-def]
    for _ in range(40):
        if job.state not in APPROVAL_STATES or job.state is JobState.AWAITING_DECISION:
            return job
        job = engine.approve(job.id)
    return job


def test_a_stuck_phase_waits_while_the_others_go_on(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    seed = seed.model_copy(update={"test_cmd": GATE})
    provider = full_provider(seed, phases=3)
    plan = provider.replies[RoleName.ARCHITECT]
    assert isinstance(plan, dict)
    plan["phases"] = [
        {**plan["phases"][0], "goal": "stuck", "files": ["a.py", "FAIL"], "depends_on": []},
        {**plan["phases"][1], "goal": "free", "files": ["b.py"], "depends_on": []},
        {**plan["phases"][2], "goal": "after stuck", "files": ["c.py"], "depends_on": [1]},
    ]
    written: list[str] = []

    def develop(req: Any) -> dict[str, Any]:
        goal = str(_context(req)["current_phase"]["goal"])
        written.append(goal)
        if goal == "stuck":  # never gets through its gate
            return {
                "summary": "x",
                "changes": [
                    {"path": "a.py", "content": f"{len(written)}\n"},
                    {"path": "FAIL", "content": "x\n"},
                ],
            }
        name = {"free": "b.py", "after stuck": "c.py"}[goal]
        return {"summary": goal, "changes": [{"path": name, "content": "ok\n"}]}

    provider.replies[RoleName.BACKEND] = develop
    stage_qa = provider.replies[RoleName.QA]

    def qa(req: Any) -> Any:
        if "spent its budget" in req.prompt:
            return {"summary": "loops", "recommendation": "Drop the FAIL file."}
        if "A build gate failed on this branch" in req.prompt:
            return {"summary": "the code", "gate_verdict": "code_is_wrong"}
        return stage_qa(req)  # type: ignore[operator]

    provider.replies[RoleName.QA] = qa
    engine = full_engine(store, worktrees_root, seed, provider, max_build_attempts=50)
    project = engine.create_project(
        Project(
            name="p",
            repo_path=repo,
            budget=BudgetSettings(max_phase_calls=4, max_parallel_phases=1),
        )
    )
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = _drive(engine, engine.approve(engine.approve(job.id).id))

    # "free" was built while "stuck" waited, and then the person is asked about "stuck"
    assert job.state is JobState.AWAITING_DECISION
    assert job.data.decision_kind == "phase_budget"
    assert job.data.recommendation == "Drop the FAIL file."
    goals = [p["goal"] for p in (job.data.plan or {})["phases"]]
    assert goals == ["free", "stuck", "after stuck"]
    assert (job.data.plan or {})["phases"][2]["depends_on"] == [2]  # still needs "stuck"
    assert job.data.phase_index == 1  # on "stuck" again
    assert "after stuck" not in written  # it needs "stuck", so it waited too
    assert job.worktree_path is not None
    subjects = g.run(job.worktree_path, "log", "--format=%s").stdout
    assert "phase 1/3: free" in subjects  # committed while "stuck" waited
    # its work in progress is back where it was
    assert (job.worktree_path / "FAIL").exists() and (job.worktree_path / "a.py").exists()
    notes = [t.note or "" for t in job.history]
    assert any("phase 1 spent its budget and waits: phase(s) 1 need nothing" in n for n in notes)
