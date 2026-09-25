from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from slipwright.activity import (
    ActivityKind,
    activity_by_day,
    job_activity,
    project_activity,
    project_progress,
    role_work,
)
from slipwright.api import create_app
from slipwright.schemas.job import JobState, utcnow
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import BREAKDOWN, full_engine, full_provider

# --- T6.3 progress and activity feed ------------------------------------------------------


def test_activity_feed_lists_the_whole_pipeline_in_order(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=2, breakdown=None)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    engine.message(job.id, "keep it small")
    job = engine.approve(job.id)  # profile -> plan proposed
    job = engine.reject(job.id, "split more")  # planner re-runs
    job = engine.approve(job.id)  # plan -> develop x2 -> qa stage 1
    job = engine.approve(job.id)  # tests written
    job = engine.approve(job.id)  # devops -> done
    assert job.state is JobState.DONE

    items = job_activity(job)  # chronological
    retrievals = [i for i in items if i.kind is ActivityKind.STANDARDS]
    assert [i.role for i in retrievals][:3] == [RoleName.PO, RoleName.ARCHITECT, RoleName.ARCHITECT]
    assert retrievals[0].title.startswith("standards (po):") and retrievals[0].has_detail
    items = [i for i in items if i.kind is not ActivityKind.STANDARDS]
    kinds = [(i.kind, i.role) for i in items]
    assert kinds == [
        (ActivityKind.STARTED, None),
        (ActivityKind.ROLE, RoleName.PO),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.INBOX, RoleName.ARCHITECT),
        (ActivityKind.ROLE, RoleName.ARCHITECT),
        (ActivityKind.APPROVAL, None),  # rejected
        (ActivityKind.ROLE, RoleName.ARCHITECT),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.ROLE, RoleName.BACKEND),
        (ActivityKind.GATE, None),
        (ActivityKind.ROLE, RoleName.QA),  # standards review of phase 1 (advisory)
        (ActivityKind.ROLE, RoleName.BACKEND),
        (ActivityKind.GATE, None),
        (ActivityKind.ROLE, RoleName.QA),  # review of phase 2
        (ActivityKind.ROLE, RoleName.QA),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.ROLE, RoleName.QA),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.ROLE, RoleName.DEVOPS),  # how this is deployed: nothing to (T11.6)
        (ActivityKind.DONE, RoleName.DEVOPS),
    ]
    assert items[5].title.startswith("rejected: split more")
    assert items[-1].title.startswith("PR https://example.test/pr/1")
    assert items[1].has_detail  # the proposed profile JSON
    assert [i.index for i in job_activity(job)] == list(range(len(job.history)))

    feed = project_activity([job])
    assert [i.index for i in feed] == list(reversed(range(len(job.history))))
    last = len(job.history) - 1
    assert [i.index for i in project_activity([job], limit=3)] == [last, last - 1, last - 2]


def test_progress_counts_tasks_and_approvals(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=4, breakdown=BREAKDOWN)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    a = engine.start(engine.create_job("a", project_id=project.id).id)
    b = engine.start(engine.create_job("b", project_id=project.id).id)
    a = engine.approve(a.id)
    a = engine.approve(a.id)  # a: developed, waiting for test approval
    progress = project_progress(project.id, [a, b])
    assert progress.pending_approvals == 2
    assert progress.jobs_running == 0
    assert (progress.tasks_done, progress.tasks_total) == (4, 4)  # b's plan is not approved
    rows = {r.job_id: r for r in progress.jobs}
    assert rows[a.id].pending_approval == "test cases"
    assert rows[a.id].current_phase == "qa stage 1"
    assert rows[b.id].pending_approval == "backlog"
    assert (rows[b.id].tasks_done, rows[b.id].tasks_total) == (0, 0)
    assert progress.last_activity == max(a.history[-1].at, b.history[-1].at)

    a = engine.approve(a.id)
    a = engine.approve(a.id)
    progress = project_progress(project.id, [a, b])
    assert progress.jobs_done == 1
    assert rows[a.id].pr_url is None and progress.jobs[0].pr_url == "https://example.test/pr/1"


def test_progress_activity_and_detail_endpoints(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        project = client.post(
            "/api/projects",
            json={"name": "demo", "repo_path": str(repo), "plan_gate": "separate"},
        ).json()
        job = client.post(f"/api/projects/{project['id']}/jobs", json={"request": "x"}).json()
        progress = client.get(f"/api/projects/{project['id']}/progress").json()
        assert progress["pending_approvals"] == 1
        assert progress["jobs"][0]["pending_approval"] == "backlog"

        feed = client.get(f"/api/projects/{project['id']}/activity").json()
        assert [i["kind"] for i in feed] == ["role", "standards", "started"]
        assert feed[0]["has_detail"] is True
        assert client.get(f"/api/projects/{project['id']}/activity?limit=1").json()[0] == feed[0]

        detail = client.get(f"/api/jobs/{job['id']}/history/{feed[0]['index']}").json()
        assert detail["to_state"] == "awaiting_backlog_approval"
        assert '"epics"' in detail["detail"]
        assert client.get(f"/api/jobs/{job['id']}/history/99").status_code == 404
        assert client.get("/api/jobs/nope/history/0").status_code == 404
        assert client.get("/api/projects/nope/progress").status_code == 404
        assert client.get("/api/projects/nope/activity").status_code == 404


# --- what the dashboard charts ------------------------------------------------------------


def test_overview_carries_the_two_series_the_dashboard_charts(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The day series is a fixed-width window with its quiet days kept — a chart that
    drops the empty days lies about the pace — and the role series is busiest first."""
    provider = full_provider(seed, phases=2, breakdown=None)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    for _ in range(4):
        job = engine.approve(job.id)
    assert job.state is JobState.DONE

    with TestClient(create_app(engine, require_auth=False, resume_on_startup=False)) as client:
        body = client.get("/api/overview").json()

    days = body["by_day"]
    assert len(days) == 14
    assert [d["day"] for d in days] == sorted(d["day"] for d in days)  # oldest first
    assert days[-1]["day"] == utcnow().date().isoformat()
    assert sum(d["events"] for d in days) == len(job.history)
    assert sum(d["finished"] for d in days) == 1  # the one development that reached done
    assert days[0]["events"] == 0  # a fortnight ago nothing happened, and the day is kept

    roles = body["by_role"]
    assert [r["role"] for r in roles] == [
        r["role"] for r in sorted(roles, key=lambda r: (-r["runs"], r["label"]))
    ]
    assert {r["role"] for r in roles} == {r.value for r in RoleName}
    by_role = {r["role"]: r["runs"] for r in roles}
    assert by_role["po"] >= 1 and by_role["architect"] >= 1 and by_role["qa"] >= 1
    assert roles[0]["runs"] == max(r["runs"] for r in roles)  # the busiest leads


def test_activity_by_day_is_empty_but_shaped_with_no_jobs() -> None:
    days = activity_by_day([], days=14)
    assert len(days) == 14 and all(d.events == 0 and d.finished == 0 for d in days)
    assert role_work([]) and all(r.runs == 0 for r in role_work([]))
