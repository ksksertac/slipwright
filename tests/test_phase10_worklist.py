"""T10.4 — one work list before anything is built.

With the combined plan gate the Product Owner and the Architect run back to back and the
person approves a single list, grouped by the agent that will do the work, down to QA and
DevOps. The job is stored throughout, so a list left unread survives a restart.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from slipwright.worklist import work_list
from tests.pipeline import full_engine, full_provider


def _engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=2))


def test_the_backlog_flows_into_the_architecture_and_stops_at_one_gate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="combined"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL  # not the backlog gate
    notes = [t.note or "" for t in job.history]
    assert any("the architect continues" in n for n in notes)
    assert not any(t.to_state is JobState.AWAITING_BACKLOG_APPROVAL for t in job.history)
    assert job.data.backlog and job.data.plan  # both are there to read and edit

    job = engine.approve(job.id)
    assert job.state is not JobState.AWAITING_ARCHITECTURE_APPROVAL  # the work started


def test_a_project_can_still_approve_the_two_steps_separately(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="separate"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL


def test_the_work_list_says_who_does_what_before_anything_is_built(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="combined"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)

    listed = work_list(job)
    assert listed.editable and listed.tasks > 0 and listed.phases == 2
    roles = [g.role for g in listed.groups]
    assert roles[0] is RoleName.PO and roles[1] is RoleName.ARCHITECT
    # every specialist that has a phase appears, and QA and DevOps close the list
    assert roles[-2:] == [RoleName.QA, RoleName.DEVOPS]
    assert all(g.label and g.summary for g in listed.groups)

    po = next(g for g in listed.groups if g.role is RoleName.PO)
    assert all(i.kind == "backlog" and i.editable for i in po.items)
    assert all(" › " in i.detail for i in po.items)  # which epic and story it belongs to

    phases = [i for g in listed.groups for i in g.items if i.kind == "phase"]
    assert len(phases) == 2 and all(i.phase and i.editable for i in phases)
    tail = [i for g in listed.groups for i in g.items if i.kind == "step"]
    assert any("pull request" in i.title for i in tail)

    # once the work has started the list is a record, not a form
    started = engine.approve(job.id)
    assert work_list(started).editable is False


def test_the_list_survives_a_restart_and_is_served_by_the_api(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo, plan_gate="combined"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)

    # a new engine over the same store is what a restart looks like
    restarted = _engine(store, worktrees_root, seed)
    again = restarted.store.get(job.id)
    assert again.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert work_list(again).tasks == work_list(job).tasks

    with TestClient(create_app(restarted, resume_on_startup=False, require_auth=False)) as client:
        body = client.get(f"/api/jobs/{job.id}/worklist").json()
        assert body["editable"] and body["groups"][0]["role"] == "po"
        assert [g["role"] for g in body["groups"]][-2:] == ["qa", "devops"]
        assert client.get("/api/jobs/nope/worklist").status_code == 404

        # the plan gate is where the list is edited: the existing editors still apply
        first = body["groups"][0]["items"][0]
        edited = client.put(
            f"/api/jobs/{job.id}/backlog",
            json={
                "breakdown": {
                    **job.data.backlog,
                    "epics": _retitled(job.data.backlog, first["id"], "değişmiş görev"),
                }
            },
        )
        assert edited.status_code == 200
        after = client.get(f"/api/jobs/{job.id}/worklist").json()
        assert after["groups"][0]["items"][0]["title"] == "değişmiş görev"


def _retitled(backlog: dict, task_id: str, title: str) -> list[dict]:
    epics = [dict(e) for e in backlog["epics"]]
    for epic in epics:
        epic["stories"] = [dict(s) for s in epic["stories"]]
        for story in epic["stories"]:
            story["tasks"] = [
                {**t, "title": title} if t["id"] == task_id else dict(t) for t in story["tasks"]
            ]
    return epics


def test_a_project_made_from_the_ui_reads_one_work_list(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The engine's own default is the older two-gate flow, so nothing that drives it
    directly changes; a project created through the API asks for the one list."""
    engine = _engine(store, worktrees_root, seed)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        made = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        assert made["plan_gate"] == "combined"
        patched = client.patch(f"/api/projects/{made['id']}", json={"plan_gate": "separate"})
        assert patched.status_code == 200 and patched.json()["plan_gate"] == "separate"
    assert engine.create_project(Project(name="plain", repo_path=repo)).plan_gate == "separate"
