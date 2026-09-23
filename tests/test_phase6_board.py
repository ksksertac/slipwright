from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.board import TaskStatus, breakdown_of, job_epics, project_board
from slipwright.roles.results import ArchitectResult, POResult
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import BREAKDOWN, FALSE, full_engine, full_provider, full_seed

SEED = full_seed()


def _statuses(job: Job) -> list[str]:
    return [t.status.value for e in job_epics(job) for s in e.stories for t in s.tasks]


def _plan(phases: list[dict[str, Any]]) -> dict[str, Any]:
    return {"summary": "s", "profile": SEED.model_dump(mode="json"), "phases": phases}


# --- T6.2 work breakdown ------------------------------------------------------------------


def test_architect_phases_must_name_tasks_once() -> None:
    ok = ArchitectResult.model_validate(
        _plan([{"goal": "a", "task_id": "t1"}, {"goal": "b", "task_id": "t2"}])
    )
    assert [p.task_id for p in ok.phases] == ["t1", "t2"]
    with pytest.raises(ValueError, match="has no task_id"):
        ArchitectResult.model_validate(_plan([{"goal": "a"}]))
    with pytest.raises(ValueError, match="more than one phase"):
        ArchitectResult.model_validate(
            _plan([{"goal": "a", "task_id": "t1"}, {"goal": "b", "task_id": "t1"}])
        )
    with pytest.raises(ValueError, match="unique"):
        POResult.model_validate(
            {
                "summary": "s",
                "breakdown": {
                    "epics": [
                        {
                            "title": "e",
                            "stories": [
                                {
                                    "title": "s",
                                    "tasks": [
                                        {"id": "t1", "title": "a"},
                                        {"id": "t1", "title": "b"},
                                    ],
                                }
                            ],
                        }
                    ]
                },
            }
        )


def test_backlog_reaches_the_board_and_the_architect_numbers_the_tasks(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=2)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("Add a /health endpoint", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert job_epics(job) == []  # backlog not approved yet: not on the board
    backlog = breakdown_of(job)
    assert backlog is not None and [t.phase for t in backlog.tasks()] == [None, None]

    job = engine.approve(job.id)  # backlog approved -> architect proposes the plan
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert '"backlog"' in provider.requests[-1].prompt  # the architect saw the backlog
    breakdown = breakdown_of(job)
    assert breakdown is not None
    assert [t.phase for t in breakdown.tasks()] == [1, 2]  # numbered by the plan
    stored = (job.data.plan or {})["breakdown"]["epics"][0]["stories"][0]["tasks"]
    assert stored[1]["title"] == "step 2"
    assert (job.data.plan or {})["decisions"] == ["write OK"]
    # the tree is on the board (Jira gets it at backlog approval), all still to do
    statuses = [t.status.value for e in job_epics(job) for s in e.stories for t in s.tasks]
    assert statuses == ["todo", "todo"]


def test_board_statuses_change_task_by_task(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=4, breakdown=BREAKDOWN)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    job = engine.approve(job.id)  # backlog
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert all(
        t.status is TaskStatus.TODO for e in job_epics(job) for s in e.stories for t in s.tasks
    )

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
    # the same fix twice stops at the decision gate: the task is still in progress
    assert job.state is JobState.AWAITING_DECISION
    assert _statuses(job) == ["in_progress", "todo"]
    job = engine.approve(engine.approve(job.id).id)  # two more tries exhaust the gate
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
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        project = client.post(
            "/api/projects",
            json={"name": "demo", "repo_path": str(repo), "plan_gate": "separate"},
        ).json()
        ids = [
            client.post(f"/api/projects/{project['id']}/jobs", json={"request": r}).json()["id"]
            for r in ("one", "two")
        ]
        for n, job_id in enumerate(ids):
            board = client.get(f"/api/projects/{project['id']}/board").json()
            assert {e["job_id"] for e in board["epics"]} == set(ids[:n])  # backlog not approved
            client.post(f"/api/jobs/{job_id}/approve")  # backlog
            client.post(f"/api/jobs/{job_id}/approve")  # architecture -> runs to the QA gate
        board = client.get(f"/api/projects/{project['id']}/board").json()
        assert [e["job_id"] for e in board["epics"]] == [ids[0], ids[0], ids[1], ids[1]]
        assert (board["tasks_done"], board["tasks_total"]) == (8, 8)
        assert board["epics"][0]["stories"][0]["tasks"][0]["status"] == "done"
        assert client.get("/api/projects/nope/board").status_code == 404
