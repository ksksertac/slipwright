from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from slipwright.activity import ActivityKind, job_activity, project_activity, project_progress
from slipwright.api import create_app
from slipwright.schemas.job import JobState
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
    kinds = [(i.kind, i.role) for i in items]
    assert kinds == [
        (ActivityKind.STARTED, None),
        (ActivityKind.ROLE, RoleName.ANALYST),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.INBOX, RoleName.PLANNER),
        (ActivityKind.ROLE, RoleName.PLANNER),
        (ActivityKind.APPROVAL, None),  # rejected
        (ActivityKind.ROLE, RoleName.PLANNER),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.ROLE, RoleName.DEVELOPER),
        (ActivityKind.GATE, None),
        (ActivityKind.ROLE, RoleName.DEVELOPER),
        (ActivityKind.GATE, None),
        (ActivityKind.ROLE, RoleName.QA),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.ROLE, RoleName.QA),
        (ActivityKind.APPROVAL, None),
        (ActivityKind.DONE, RoleName.DEVOPS),
    ]
    assert items[5].title.startswith("rejected: split more")
    assert items[-1].title.startswith("PR https://example.test/pr/1")
    assert items[1].has_detail  # the proposed profile JSON
    assert [i.index for i in items] == list(range(len(job.history)))

    feed = project_activity([job])
    assert [i.index for i in feed] == list(reversed(range(len(job.history))))
    assert [i.index for i in project_activity([job], limit=3)] == [16, 15, 14]


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
    assert rows[b.id].pending_approval == "profile"
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
        project = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        job = client.post(f"/api/projects/{project['id']}/jobs", json={"request": "x"}).json()
        progress = client.get(f"/api/projects/{project['id']}/progress").json()
        assert progress["pending_approvals"] == 1
        assert progress["jobs"][0]["pending_approval"] == "profile"

        feed = client.get(f"/api/projects/{project['id']}/activity").json()
        assert [i["kind"] for i in feed] == ["role", "started"]
        assert feed[0]["has_detail"] is True
        assert client.get(f"/api/projects/{project['id']}/activity?limit=1").json()[0] == feed[0]

        detail = client.get(f"/api/jobs/{job['id']}/history/{feed[0]['index']}").json()
        assert detail["to_state"] == "awaiting_profile_approval"
        assert '"language": "python"' in detail["detail"]
        assert client.get(f"/api/jobs/{job['id']}/history/99").status_code == 404
        assert client.get("/api/jobs/nope/history/0").status_code == 404
        assert client.get("/api/projects/nope/progress").status_code == 404
        assert client.get("/api/projects/nope/activity").status_code == 404
