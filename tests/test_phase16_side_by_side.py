"""T16.3: phases that need nothing still being built have their answers written side by
side. The model's answer is where a phase's time goes; each phase is still applied, built,
reviewed, committed and pushed in its turn."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import BudgetSettings, Project
from slipwright.store import JobStore
from slipwright.workspace import git as g
from tests.pipeline import full_engine, full_provider


def _context(request: Any) -> dict[str, Any]:
    text = request.prompt
    body = text[text.index("Context:\n") + len("Context:\n") : text.index("\n\nRespond with")]
    return dict(json.loads(body))


def _drive(engine, job: Job) -> Job:  # type: ignore[no-untyped-def]
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            return job
        job = engine.approve(job.id)
    return job


def _scripted(seed: Profile, together: threading.Barrier | None) -> Any:
    """Three phases: 1 and 2 need nothing, 3 needs both. With ``together``, phases 1 and 2
    each wait at the barrier for the other -- which only one at a time never passes."""
    provider = full_provider(seed, phases=3)
    plan = provider.replies[RoleName.ARCHITECT]
    assert isinstance(plan, dict)
    plan["phases"] = [
        {**plan["phases"][0], "files": ["a.py"], "depends_on": []},
        {**plan["phases"][1], "files": ["b.py"], "depends_on": []},
        {**plan["phases"][2], "files": ["c.py"], "depends_on": [1, 2]},
    ]
    order: list[int] = []

    def develop(req: Any) -> dict[str, Any]:
        number = int(_context(req)["current_phase"]["number"])
        order.append(number)
        if together is not None and number in (1, 2):
            together.wait(timeout=20)
        name = {1: "a.py", 2: "b.py", 3: "c.py"}[number]
        return {"summary": f"phase {number}", "changes": [{"path": name, "content": f"{number}\n"}]}

    provider.replies[RoleName.BACKEND] = develop
    return provider, order


def _project(engine, repo: Path, parallel: int) -> Project:  # type: ignore[no-untyped-def]
    return engine.create_project(
        Project(name="p", repo_path=repo, budget=BudgetSettings(max_parallel_phases=parallel))
    )


def test_two_phases_that_need_nothing_are_written_at_once(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider, order = _scripted(seed, threading.Barrier(2))
    engine = full_engine(store, worktrees_root, seed, provider)
    project = _project(engine, repo, 3)
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = _drive(engine, engine.approve(engine.approve(job.id).id))

    assert job.state is JobState.DONE  # the barrier was passed: 1 and 2 were written together
    assert sorted(order) == [1, 2, 3] and order[-1] == 3  # 3 needed both, and waited
    notes = [t.note or "" for t in job.history]
    assert any("phase(s) 2: their answers are written alongside phase 1" in n for n in notes)
    # still applied and committed one at a time, in plan order
    assert job.worktree_path is not None
    subjects = g.run(job.worktree_path, "log", "--format=%s").stdout.splitlines()
    phases = [s.split(":")[1].strip() for s in subjects if s.startswith("slipwright: phase")]
    assert phases == ["phase 3/3", "phase 2/3", "phase 1/3"]
    # each call counted against its own phase
    counted = {e["phase"] for e in job.data.invocation_log if e["role"] == "backend"}
    assert counted == {1, 2, 3}


def test_one_at_a_time_writes_nothing_ahead(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider, order = _scripted(seed, None)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = _project(engine, repo, 1)
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = _drive(engine, engine.approve(engine.approve(job.id).id))

    assert job.state is JobState.DONE
    assert order == [1, 2, 3]
    assert not any("written alongside" in (t.note or "") for t in job.history)


def test_a_phase_that_needs_the_one_being_built_waits_its_turn(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider, order = _scripted(seed, None)
    plan = provider.replies[RoleName.ARCHITECT]
    assert isinstance(plan, dict)
    plan["phases"][1]["depends_on"] = [1]  # 2 needs 1 now: nothing can go ahead
    engine = full_engine(store, worktrees_root, seed, provider)
    project = _project(engine, repo, 3)
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = _drive(engine, engine.approve(engine.approve(job.id).id))

    assert job.state is JobState.DONE
    assert order == [1, 2, 3]
    assert not any("written alongside" in (t.note or "") for t in job.history)
