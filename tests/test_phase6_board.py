from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.board import TaskStatus, breakdown_of, job_epics, project_board
from slipwright.engine import Engine
from slipwright.githost import CiState, CiStatus
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.roles.results import PlannerResult
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName, load_profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"
PY = sys.executable
TRUE = f'"{PY}" -c "print(1)"'
FALSE = f'"{PY}" -c "raise SystemExit(1)"'


class FakeHost:
    def push(self, worktree: Path, branch: str) -> None:
        pass

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        return "https://example.test/pr/1"

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        return CiStatus(CiState.SUCCESS, summary="ci: success")


BREAKDOWN: dict[str, Any] = {
    "epics": [
        {
            "id": "e1",
            "title": "Health endpoint",
            "stories": [
                {
                    "id": "s1",
                    "title": "As an operator I can probe liveness",
                    "tasks": [
                        {"id": "t1", "title": "Add route", "phase": 1},
                        {"id": "t2", "title": "Add response model", "phase": 2},
                    ],
                },
                {
                    "id": "s2",
                    "title": "As an operator I see the version",
                    "tasks": [{"id": "t3", "title": "Expose version", "phase": 3}],
                },
            ],
        },
        {
            "id": "e2",
            "title": "Documentation",
            "stories": [
                {
                    "id": "s3",
                    "title": "As a developer I read about /health",
                    "tasks": [{"id": "t4", "title": "Document it", "phase": 4}],
                }
            ],
        },
    ]
}


def full_provider(
    seed: Profile, phases: int = 4, breakdown: dict[str, Any] | None = None
) -> ScriptedProvider:
    p = canned(seed)
    plan: dict[str, Any] = {
        "summary": f"{phases} phases",
        "phases": [{"goal": f"step {i + 1}", "files": ["OK"]} for i in range(phases)],
    }
    if breakdown is not None:
        plan["breakdown"] = breakdown
    p.replies[RoleName.PLANNER] = plan
    p.replies[RoleName.DEVELOPER] = {
        "summary": "wrote OK",
        "phase_complete": True,
        "changes": [{"path": "OK", "content": "yes\n"}],
    }
    p.replies[RoleName.QA] = lambda req: (
        {"summary": "cases", "test_cases": [{"name": "smoke", "description": "OK is yes"}]}
        if '"stage": 1' in req.prompt
        else {"summary": "tests", "changes": [{"path": "tests/t.txt", "content": "ok\n"}]}
    )
    return p


def full_engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider, **kw: Any
) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8300, end=8399))
    kw.setdefault("git_host", FakeHost())
    return Engine(store, ws, seed_profile=seed, provider=provider, ci_poll_s=0.0, **kw)


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE).model_copy(update={"build_cmd": TRUE, "test_cmd": TRUE})


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


def _statuses(job: Job) -> list[str]:
    return [t.status.value for e in job_epics(job) for s in e.stories for t in s.tasks]


def _plan(phases: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": "s",
        "phases": phases,
        "breakdown": {"epics": [{"title": "e", "stories": [{"title": "s", "tasks": tasks}]}]},
    }


# --- T6.2 work breakdown ------------------------------------------------------------------


def test_breakdown_schema_rejects_orphans() -> None:
    phases = [{"goal": "a"}, {"goal": "b"}]
    ok = PlannerResult.model_validate(
        _plan(phases, [{"title": "t1", "phase": 1}, {"title": "t2", "phase": 2}])
    )
    assert ok.breakdown is not None
    assert [t.phase for t in ok.breakdown.tasks()] == [1, 2]
    with pytest.raises(ValueError, match="no task references"):
        PlannerResult.model_validate(_plan(phases, [{"title": "t", "phase": 1}]))
    with pytest.raises(ValueError, match="referenced by both"):
        PlannerResult.model_validate(
            _plan(
                phases,
                [
                    {"title": "t1", "phase": 1},
                    {"title": "t2", "phase": 1},
                    {"title": "t3", "phase": 2},
                ],
            )
        )
    with pytest.raises(ValueError, match="references phase 3"):
        PlannerResult.model_validate(
            _plan(phases, [{"title": "t1", "phase": 1}, {"title": "t2", "phase": 3}])
        )


def test_plan_without_breakdown_gets_a_default_one(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=2)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("Add a /health endpoint", repo).id)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_PLAN_APPROVAL
    breakdown = breakdown_of(job)
    assert breakdown is not None
    assert [e.title for e in breakdown.epics] == ["Add a /health endpoint"]
    assert [t.phase for t in breakdown.tasks()] == [1, 2]
    stored = (job.data.plan or {})["breakdown"]["epics"][0]["stories"][0]["tasks"]
    assert stored[1]["title"] == "step 2"
    assert job_epics(job) == []  # not approved yet: not on the board
    assert "breakdown" in provider.requests[-1].prompt  # the planner was asked for one


def test_board_statuses_change_task_by_task(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=4, breakdown=BREAKDOWN)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    job = engine.approve(job.id)  # profile
    assert job.state is JobState.AWAITING_PLAN_APPROVAL
    assert project_board(project.id, [job]).epics == []

    # step one handler at a time: remove the next handler so ``_run`` stops after each
    develop, gate = engine.handlers[JobState.DEVELOPING], engine.handlers[JobState.BUILD_GATE]
    engine.handlers.pop(JobState.BUILD_GATE)
    job = engine.approve(job.id)  # plan approved -> developing -> build_gate (stops)
    assert job.state is JobState.BUILD_GATE
    seen = [_statuses(job)]
    for _ in range(4):
        engine.handlers[JobState.BUILD_GATE] = gate
        engine.handlers.pop(JobState.DEVELOPING)
        job = engine.resume(job.id)  # gate passes -> developing or qa
        seen.append(_statuses(job))
        if job.state is not JobState.DEVELOPING:
            break
        engine.handlers[JobState.DEVELOPING] = develop
        engine.handlers.pop(JobState.BUILD_GATE)
        job = engine.resume(job.id)  # develop -> build_gate (stops)
        seen.append(_statuses(job))
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    # a task is in progress from the moment its job enters ``developing`` for its phase
    distinct = [s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]]
    assert distinct == [
        ["in_progress", "todo", "todo", "todo"],
        ["done", "in_progress", "todo", "todo"],
        ["done", "done", "in_progress", "todo"],
        ["done", "done", "done", "in_progress"],
        ["done", "done", "done", "done"],
    ]
    board = project_board(project.id, [job])
    assert (board.tasks_done, board.tasks_total) == (4, 4)
    assert [e.status for e in board.epics] == [TaskStatus.DONE, TaskStatus.DONE]
    assert board.epics[0].stories[0].tasks[0].files == ["OK"]
    assert board.epics[0].stories[0].tasks[0].id == "t1"

    engine.handlers[JobState.DEVELOPING] = develop
    job = engine.approve(job.id)  # tests written
    job = engine.approve(job.id)  # devops -> done
    assert job.state is JobState.DONE
    assert _statuses(job) == ["done"] * 4


def test_board_marks_the_failing_task(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    broken = seed.model_copy(update={"test_cmd": FALSE})
    provider = full_provider(broken, phases=2)
    engine = full_engine(store, worktrees_root, broken, provider)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert job.state is JobState.FAILED
    assert _statuses(job) == ["failed", "todo"]
    (epic,) = job_epics(job)
    assert epic.status is TaskStatus.FAILED
    assert epic.stories[0].status is TaskStatus.FAILED


def test_board_endpoint_merges_jobs(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=4, breakdown=BREAKDOWN)
    engine = full_engine(store, worktrees_root, seed, provider)
    with TestClient(create_app(engine, resume_on_startup=False)) as client:
        project = client.post("/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        ids = [
            client.post(f"/projects/{project['id']}/jobs", json={"request": r}).json()["id"]
            for r in ("one", "two")
        ]
        for n, job_id in enumerate(ids):
            client.post(f"/jobs/{job_id}/approve")  # profile
            board = client.get(f"/projects/{project['id']}/board").json()
            assert {e["job_id"] for e in board["epics"]} == set(ids[:n])  # plan not approved
            client.post(f"/jobs/{job_id}/approve")  # plan -> runs to the QA gate
        board = client.get(f"/projects/{project['id']}/board").json()
        assert [e["job_id"] for e in board["epics"]] == [ids[0], ids[0], ids[1], ids[1]]
        assert (board["tasks_done"], board["tasks_total"]) == (8, 8)
        assert board["epics"][0]["stories"][0]["tasks"][0]["status"] == "done"
        assert client.get("/projects/nope/board").status_code == 404
