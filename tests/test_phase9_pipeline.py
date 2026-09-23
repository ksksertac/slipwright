"""T9.9 — the pipeline view, gate edits and batch approvals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine, InvalidEdit, NotAwaitingApproval
from slipwright.pipeline import StepStatus, lane_for
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, set_plan

WEB = Path(__file__).resolve().parent.parent / "web"


def _by_key(job: Any) -> dict[str, Any]:
    return {card.key: card for card in lane_for(job).steps}


def _statuses(job: Any) -> dict[str, str]:
    return {k: c.status.value for k, c in _by_key(job).items()}


def _two_domain_engine(store: JobStore, worktrees_root: Path, seed: Profile) -> tuple[Engine, Any]:
    provider = full_provider(seed, phases=2)
    set_plan(
        provider,
        seed,
        [
            {"goal": "add the endpoint", "files": ["OK"], "domain": "backend"},
            {"goal": "show it", "files": ["OK"], "domain": "web"},
        ],
    )
    return full_engine(store, worktrees_root, seed, provider), provider


# --- the lane --------------------------------------------------------------------------


def test_lane_follows_the_job_through_every_gate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _two_domain_engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.create_job("health", project_id=project.id)
    assert _statuses(job) == {
        "backlog": "pending",
        "backlog_gate": "pending",
        "architecture": "pending",
        "architecture_gate": "pending",
        "develop": "pending",
        "qa:1": "pending",
        "test_gate:1": "pending",
        "qa:2": "pending",
        "test_gate:2": "pending",
        "devops": "pending",
        "done": "pending",
    }

    job = engine.start(job.id)  # PO ran, backlog waits
    cards = _by_key(job)
    assert cards["backlog"].status is StepStatus.DONE and cards["backlog"].role is RoleName.PO
    assert cards["backlog"].elapsed_s is not None and cards["backlog"].elapsed_s >= 0
    assert job.history[cards["backlog"].outputs[0]].note is not None
    assert job.history[cards["backlog"].outputs[0]].note.startswith("po:")  # type: ignore[union-attr]
    gate = cards["backlog_gate"]
    assert gate.status is StepStatus.WAITING and gate.pending == "backlog" and gate.editable
    assert lane_for(job).pending_approval == "backlog"

    job = engine.reject(job.id, "split it")  # PO again: the card shows the latest run
    cards = _by_key(job)
    assert cards["backlog"].status is StepStatus.DONE
    assert cards["backlog_gate"].status is StepStatus.WAITING
    assert cards["backlog"].outputs == [len(job.history) - 1]

    job = engine.approve(job.id)  # architect proposes
    cards = _by_key(job)
    assert cards["backlog_gate"].status is StepStatus.DONE
    assert cards["architecture"].status is StepStatus.DONE
    assert cards["architecture_gate"].status is StepStatus.WAITING
    assert [c.key for c in lane_for(job).steps][4:6] == ["phase:1", "phase:2"]
    phase = cards["phase:1"]
    assert phase.label == "Backend: add the endpoint" and phase.role is RoleName.BACKEND
    assert phase.domain == "backend" and phase.task_title == "step 1"
    assert phase.status is StepStatus.PENDING
    assert cards["phase:2"].role is RoleName.WEB_UI

    job = engine.approve(job.id)  # both phases built, test cases proposed
    cards = _by_key(job)
    assert cards["phase:1"].status is StepStatus.DONE and cards["phase:2"].status is StepStatus.DONE
    notes = [job.history[i].note or "" for i in cards["phase:1"].outputs]
    assert any(n.startswith("backend phase 1/2") for n in notes)
    assert any(n.startswith("build gate passed for phase 1/2") for n in notes)
    assert cards["phase:1"].finished_at is not None and cards["phase:1"].started_at is not None
    assert cards["qa:1"].status is StepStatus.DONE
    assert cards["test_gate:1"].status is StepStatus.WAITING
    assert cards["test_gate:1"].pending == "test cases" and cards["test_gate:1"].editable
    assert cards["qa:2"].status is StepStatus.PENDING

    job = engine.approve(job.id)  # tests written
    cards = _by_key(job)
    assert cards["test_gate:1"].status is StepStatus.DONE
    assert cards["qa:2"].status is StepStatus.DONE
    assert cards["test_gate:2"].status is StepStatus.WAITING
    assert cards["test_gate:2"].pending == "written tests" and not cards["test_gate:2"].editable

    job = engine.approve(job.id)  # devops
    cards = _by_key(job)
    assert job.state is JobState.DONE
    assert [k for k, c in cards.items() if c.status is not StepStatus.DONE] == []
    assert (job.history[cards["devops"].outputs[0]].note or "").startswith("PR ")


def test_lane_carries_the_architects_summary_for_the_brief(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The lane's brief reads the plan summary, so the UI has something short to show
    above the flow instead of the whole request. There is none before the plan."""
    engine, _ = _two_domain_engine(store, worktrees_root, seed)
    job = engine.create_job("health", repo)
    assert lane_for(job).summary is None

    job = engine.approve(engine.start(job.id).id)  # the architect has planned
    assert lane_for(job).summary == "2 phases"
    assert lane_for(job).request == "health"  # the request is kept whole beside it


def test_failed_job_marks_the_step_it_died_in(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _two_domain_engine(store, worktrees_root, seed)
    engine.max_build_attempts = 1
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(job.id)
    failing = job.profile.model_copy(update={"test_cmd": "false"})  # type: ignore[union-attr]
    engine.set_profile(job.id, failing)
    job = engine.approve(job.id)
    assert job.state is JobState.FAILED
    cards = _by_key(job)
    assert cards["phase:1"].status is StepStatus.FAILED
    assert cards["phase:2"].status is StepStatus.PENDING
    assert cards["qa:1"].status is StepStatus.PENDING
    assert len(job.history) - 1 in cards["phase:1"].outputs  # the failure record


def test_pipeline_endpoint_lists_lanes_newest_first(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _two_domain_engine(store, worktrees_root, seed)
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        first = client.post(f"/api/projects/{project['id']}/jobs", json={"request": "one"}).json()
        second = client.post(f"/api/projects/{project['id']}/jobs", json={"request": "two"}).json()
        body = client.get(f"/api/projects/{project['id']}/pipeline").json()
        assert [lane["job_id"] for lane in body["lanes"]] == [second["id"], first["id"]]
        assert body["waiting"] == 2
        lane = body["lanes"][0]
        assert lane["pending_approval"] == "backlog"
        keys = [s["key"] for s in lane["steps"]]
        assert keys[:5] == [
            "backlog",
            "backlog_gate",
            "architecture",
            "architecture_gate",
            "develop",
        ]
        waiting = [s for s in lane["steps"] if s["status"] == "waiting"]
        assert len(waiting) == 1 and waiting[0]["outputs"] == [2]
        assert client.get("/api/projects/nope/pipeline").status_code == 404


# --- editing at the gates -------------------------------------------------------------


def test_backlog_can_be_edited_before_approval(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _two_domain_engine(store, worktrees_root, seed)
    job = engine.start(engine.create_job("x", repo).id)
    tree = job.data.backlog
    assert tree is not None
    tree["epics"][0]["stories"][0]["tasks"][0]["title"] = "renamed by a human"
    job = engine.set_backlog(job.id, tree)
    assert job.data.backlog is not None
    assert job.data.backlog["epics"][0]["stories"][0]["tasks"][0]["title"] == "renamed by a human"

    bad = {"epics": [{"id": "e", "title": "t", "stories": []}]}
    with pytest.raises(InvalidEdit):
        engine.set_backlog(job.id, bad)
    dup = {
        "epics": [
            {
                "id": "e",
                "title": "t",
                "stories": [
                    {
                        "id": "s",
                        "title": "s",
                        "tasks": [{"id": "t1", "title": "a"}, {"id": "t1", "title": "b"}],
                    }
                ],
            }
        ]
    }
    with pytest.raises(InvalidEdit, match="unique"):
        engine.set_backlog(job.id, dup)

    job = engine.approve(job.id)  # the architect sees the edited backlog
    assert "renamed by a human" in provider.requests[-1].prompt
    with pytest.raises(NotAwaitingApproval):
        engine.set_backlog(job.id, tree)


def test_plan_edits_are_checked_like_the_architects(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _two_domain_engine(store, worktrees_root, seed)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    plan = job.data.plan
    assert plan is not None
    # reorder the phases, retag one, rename a task
    edited = {
        "phases": [
            {**plan["phases"][1], "domain": "mobile"},
            plan["phases"][0],
        ],
        "breakdown": plan["breakdown"],
        "decisions": ["mobile first"],
    }
    edited["breakdown"]["epics"][0]["stories"][0]["tasks"][0]["title"] = "renamed"
    job = engine.set_plan(job.id, edited)
    assert job.data.plan is not None
    assert [p["task_id"] for p in job.data.plan["phases"]] == ["t2", "t1"]
    assert job.data.plan["phases"][0]["domain"] == "mobile"
    assert job.data.plan["decisions"] == ["mobile first"]
    assert job.data.plan["summary"] == plan["summary"]  # kept
    tasks = job.data.plan["breakdown"]["epics"][0]["stories"][0]["tasks"]
    assert [(t["id"], t["phase"], t["title"]) for t in tasks] == [
        ("t1", 2, "renamed"),
        ("t2", 1, "step 2"),
    ]
    cards = {c.key: c for c in lane_for(job).steps}
    assert cards["phase:1"].role is RoleName.MOBILE_UI and cards["phase:1"].task_title == "step 2"

    # orphan phases and unknown tasks are refused, and the plan stays as it was
    with pytest.raises(InvalidEdit, match="t1"):
        engine.set_plan(job.id, {"phases": [plan["phases"][1]]})
    with pytest.raises(InvalidEdit, match="t9"):
        engine.set_plan(job.id, {"phases": [{**plan["phases"][0], "task_id": "t9"}]})
    with pytest.raises(InvalidEdit):
        engine.set_plan(job.id, {"phases": []})
    with pytest.raises(InvalidEdit):
        engine.set_plan(job.id, {"phases": [{"goal": "", "task_id": "t1"}]})
    assert [p["task_id"] for p in engine.store.get(job.id).data.plan["phases"]] == ["t2", "t1"]  # type: ignore[index]

    job = engine.approve(job.id)  # the edited order is what runs
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    roles = [r.role for r in provider.requests if r.role in (RoleName.MOBILE_UI, RoleName.BACKEND)]
    assert roles == [RoleName.MOBILE_UI, RoleName.BACKEND]
    with pytest.raises(NotAwaitingApproval):
        engine.set_plan(job.id, edited)


def test_edit_endpoints(store: JobStore, repo: Path, worktrees_root: Path, seed: Profile) -> None:
    engine, _ = _two_domain_engine(store, worktrees_root, seed)
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        job = client.post("/api/jobs", json={"request": "x", "repo_path": str(repo)}).json()
        job = client.get(f"/api/jobs/{job['id']}").json()
        assert client.put(f"/api/jobs/{job['id']}/plan", json={"phases": []}).status_code == 409
        tree = job["data"]["backlog"]
        tree["epics"][0]["title"] = "Edited epic"
        resp = client.put(f"/api/jobs/{job['id']}/backlog", json={"breakdown": tree})
        assert (
            resp.status_code == 200
            and resp.json()["data"]["backlog"]["epics"][0]["title"] == "Edited epic"
        )
        assert (
            client.put(
                f"/api/jobs/{job['id']}/backlog", json={"breakdown": {"epics": []}}
            ).status_code
            == 422
        )

        client.post(f"/api/jobs/{job['id']}/approve")
        job = client.get(f"/api/jobs/{job['id']}").json()
        assert job["state"] == "awaiting_architecture_approval"
        plan = job["data"]["plan"]
        resp = client.put(
            f"/api/jobs/{job['id']}/plan",
            json={"phases": list(reversed(plan["phases"])), "summary": "swapped"},
        )
        assert resp.status_code == 200, resp.text
        assert [p["task_id"] for p in resp.json()["data"]["plan"]["phases"]] == ["t2", "t1"]
        assert resp.json()["data"]["plan"]["summary"] == "swapped"
        orphan = client.put(f"/api/jobs/{job['id']}/plan", json={"phases": [plan["phases"][0]]})
        assert orphan.status_code == 422 and "t2" in orphan.json()["detail"]
        assert (
            client.put(f"/api/jobs/{job['id']}/backlog", json={"breakdown": tree}).status_code
            == 409
        )


# --- batch approvals -------------------------------------------------------------------


def test_batch_approve_and_reject_report_per_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _two_domain_engine(store, worktrees_root, seed)
    engine.handlers.pop(JobState.ARCHITECTURE)  # stop after the backlog gate
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        a = client.post("/api/jobs", json={"request": "a", "repo_path": str(repo)}).json()
        b = client.post("/api/jobs", json={"request": "b", "repo_path": str(repo)}).json()
        c = client.post("/api/jobs", json={"request": "c", "repo_path": str(repo)}).json()
        client.post(f"/api/jobs/{c['id']}/approve")  # c is no longer at a gate

        resp = client.post(
            "/api/jobs/reject", json={"job_ids": [a["id"]], "feedback": "smaller stories"}
        )
        assert resp.status_code == 200
        assert resp.json()["results"] == [
            {"job_id": a["id"], "ok": True, "state": "backlog", "error": None}
        ]
        assert client.get(f"/api/jobs/{a['id']}").json()["state"] == "awaiting_backlog_approval"
        assert "rejected: smaller stories" in [
            t["note"] for t in client.get(f"/api/jobs/{a['id']}").json()["history"]
        ]

        resp = client.post(
            "/api/jobs/approve", json={"job_ids": [a["id"], b["id"], c["id"], "nope", b["id"]]}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["approved"] == 2
        by_id = {r["job_id"]: r for r in body["results"]}
        assert len(body["results"]) == 4  # duplicates collapse
        assert by_id[a["id"]]["ok"] and by_id[a["id"]]["state"] == "architecture"
        assert by_id[b["id"]]["ok"]
        assert not by_id[c["id"]]["ok"] and "not awaiting approval" in by_id[c["id"]]["error"]
        assert not by_id["nope"]["ok"]
        for job_id in (a["id"], b["id"]):
            job = client.get(f"/api/jobs/{job_id}").json()
            assert job["state"] == "architecture"
            assert "approved" in [t["note"] for t in job["history"]]
        assert client.post("/api/jobs/approve", json={"job_ids": []}).status_code == 422


# --- the UI ----------------------------------------------------------------------------


def test_pipeline_ui_sources() -> None:
    src = (WEB / "src").rglob("*.tsx")
    text = {p.name: p.read_text(encoding="utf-8") for p in src}
    page = text["PipelineTab.tsx"]
    bar = text["BulkBar.tsx"]
    assert "Approve selected" in bar and "Reject selected" in bar
    assert "useBatchApprove" in bar and "useBatchReject" in bar
    for expected in (
        "usePipeline",
        "lane",
        "step-card",
        'type="checkbox"',
        "BulkBar",
        "Select all waiting",
        "StepPanel",
        "flow-rail",
        "lane-brief",
        "STAGE_LABEL",
        "Save & approve",
        "PlanEditor",
        "BacklogEditor",
        "TestCasesEditor",
        "ProfileForm",
    ):
        assert expected in page, expected
    assert '"pipeline"' in text["ProjectPage.tsx"] and "PipelineTab" in text["ProjectPage.tsx"]
    assert "BulkBar" in text["DashboardPage.tsx"]  # the same bulk bar on the dashboard
    hooks = (WEB / "src" / "api" / "hooks.ts").read_text(encoding="utf-8")
    assert "/api/jobs/approve" in hooks and "/api/jobs/reject" in hooks
    assert "/api/jobs/${jobId}/plan" in hooks and "/api/jobs/${jobId}/backlog" in hooks
    assert "/api/projects/${id}/pipeline" in hooks
