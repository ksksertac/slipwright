"""T9.8 — the supervisor at the gates: manual / assisted / auto."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from slipwright.activity import ActivityKind, job_activity, overview
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.pipeline import lane_for
from slipwright.providers import ModelRequest, ProviderTimeoutError
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project, SupervisorSettings
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

WEB = Path(__file__).resolve().parent.parent / "web"

APPROVE = {
    "summary": "fine",
    "decision": "approve",
    "confidence": 0.95,
    "risk": "low",
    "reasons": ["matches the request", "small change"],
}
RISKY = {
    "summary": "touches auth",
    "decision": "approve",
    "confidence": 0.9,
    "risk": "high",
    "reasons": ["changes the login flow"],
}
UNSURE = {
    "summary": "meh",
    "decision": "approve",
    "confidence": 0.5,
    "risk": "low",
    "reasons": ["hard to tell"],
}
REJECT = {
    "summary": "drifts",
    "decision": "reject",
    "confidence": 0.9,
    "risk": "low",
    "reasons": ["adds a second endpoint"],
    "feedback": "drop the extra endpoint",
}


def _context(req: ModelRequest) -> dict[str, Any]:
    text = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    ctx: dict[str, Any] = json.loads(text)
    return ctx


def _engine(
    store: JobStore, worktrees_root: Path, seed: Profile, verdicts: list[Any]
) -> tuple[Engine, Any]:
    provider = full_provider(seed, phases=1)
    calls: list[int] = []

    def sup(req: ModelRequest) -> Any:
        n = len(calls)
        calls.append(n)
        verdict = verdicts[min(n, len(verdicts) - 1)]
        if isinstance(verdict, Exception):
            raise verdict
        return verdict

    provider.replies[RoleName.SUPERVISOR] = sup
    engine = full_engine(store, worktrees_root, seed, provider, supervisor_mode=None)
    return engine, provider


def _project(engine: Engine, repo: Path, **kw: Any) -> Project:
    return engine.create_project(
        Project(name="demo", repo_path=repo, supervisor=SupervisorSettings(**kw))
    )


def _supervisions(provider: Any) -> list[ModelRequest]:
    return [r for r in provider.requests if r.role is RoleName.SUPERVISOR]


def test_assisted_records_a_recommendation_and_never_moves_the_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, [REJECT, APPROVE])
    project = _project(engine, repo)  # assisted is the default
    assert project.supervisor.mode == "assisted"
    job = engine.start(engine.create_job("health", project_id=project.id).id)

    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    (req,) = _supervisions(provider)
    ctx = _context(req)
    assert ctx["gate"] == "backlog" and ctx["material"]["backlog"]["epics"]
    assert "standards" in ctx and req.model == seed.roles[RoleName.SUPERVISOR].model
    assert job.data.supervision is not None
    assert job.data.supervision["decision"] == "reject"
    assert job.data.supervision["acted"] == "none" and job.data.supervision["gate"] == "backlog"
    note = job.history[-1].note or ""
    assert note == "supervisor: recommends reject (confidence 0.90, risk low)"
    items = job_activity(job)
    assert (items[-1].kind, items[-1].role) == (ActivityKind.ROLE, RoleName.SUPERVISOR)
    lane = lane_for(job)
    gate = next(c for c in lane.steps if c.key == "backlog_gate")
    assert (gate.recommendation, gate.confidence, gate.risk) == ("reject", 0.9, "low")
    row = overview(1, [job]).waiting[0]
    assert (row.recommendation, row.confidence, row.risk) == ("reject", 0.9, "low")

    job = engine.approve(job.id)  # the human decides anyway
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert len(_supervisions(provider)) == 2
    assert _context(_supervisions(provider)[1])["gate"] == "architecture"
    assert _context(_supervisions(provider)[1])["material"]["plan"]["phases"]
    assert job.data.supervision is not None and job.data.supervision["decision"] == "approve"
    assert job.data.auto_approvals == 0


def test_manual_never_asks(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, [APPROVE])
    project = _project(engine, repo, mode="manual")
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert _supervisions(provider) == [] and job.data.supervision is None


def test_auto_approves_low_risk_and_stops_at_high_risk(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, [APPROVE, RISKY])
    project = _project(engine, repo, mode="auto")
    job = engine.start(engine.create_job("health", project_id=project.id).id)

    # the backlog was approved by the supervisor, the architecture waits (high risk)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    notes = [t.note or "" for t in job.history]
    assert any(
        n.startswith("approved by supervisor (confidence 0.95): matches the request; small change")
        for n in notes
    )
    assert job.data.auto_approvals == 1
    assert job.data.supervision is not None
    assert job.data.supervision["acted"] == "none"
    assert job.data.supervision["blockers"] == ["risk high"]
    assert "waits for you: risk high" in (job.history[-1].note or "")
    lane = lane_for(job)
    cards = {c.key: c for c in lane.steps}
    assert cards["backlog_gate"].auto_approved and cards["backlog_gate"].status.value == "done"
    assert cards["architecture_gate"].recommendation == "approve"
    assert not cards["architecture_gate"].auto_approved
    items = job_activity(job)
    auto = [i for i in items if i.kind is ActivityKind.APPROVAL and i.role is RoleName.SUPERVISOR]
    assert len(auto) == 1


def test_auto_never_rejects_and_respects_threshold_cap_and_final_gate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    # rejecting recommendation: waits
    engine, _ = _engine(store, worktrees_root, seed, [REJECT])
    project = _project(engine, repo, mode="auto")
    job = engine.start(engine.create_job("a", project_id=project.id).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert job.data.supervision is not None
    assert job.data.supervision["blockers"] == ["recommends rejecting"]

    # low confidence: waits
    engine2, _ = _engine(store, worktrees_root, seed, [UNSURE])
    project2 = engine2.create_project(
        Project(
            name="p2", repo_path=repo, supervisor=SupervisorSettings(mode="auto", threshold=0.8)
        )
    )
    job2 = engine2.start(engine2.create_job("b", project_id=project2.id).id)
    assert job2.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert job2.data.supervision is not None
    assert job2.data.supervision["blockers"] == ["confidence 0.50 < 0.80"]

    # everything approvable: the cap stops it, and the final gate is never automatic
    engine3, provider3 = _engine(store, worktrees_root, seed, [APPROVE])
    project3 = engine3.create_project(
        Project(name="p3", repo_path=repo, supervisor=SupervisorSettings(mode="auto", cap=2))
    )
    job3 = engine3.start(engine3.create_job("c", project_id=project3.id).id)
    # backlog + architecture approved automatically, then the test-case gate hits the cap
    assert job3.state is JobState.AWAITING_TEST_APPROVAL and job3.data.qa_stage == 1
    assert job3.data.auto_approvals == 2
    assert job3.data.supervision is not None
    assert job3.data.supervision["blockers"] == ["cap of 2 automatic approval(s) reached"]
    job3 = engine3.approve(job3.id)  # the human approves the cases; tests are written
    assert job3.state is JobState.AWAITING_TEST_APPROVAL and job3.data.qa_stage == 2
    assert job3.data.supervision is not None
    assert "the final gate is never automatic" in job3.data.supervision["blockers"]
    written = _context(_supervisions(provider3)[-1])
    assert (
        written["gate"] == "written tests" and "tests/t.txt" in written["material"]["written_tests"]
    )

    # with a bigger cap and the final gate allowed the whole job runs through
    engine4, _ = _engine(store, worktrees_root, seed, [APPROVE])
    project4 = engine4.create_project(
        Project(
            name="p4",
            repo_path=repo,
            supervisor=SupervisorSettings(mode="auto", cap=10, allow_final_gate=True),
        )
    )
    job4 = engine4.start(engine4.create_job("d", project_id=project4.id).id)
    assert job4.state is JobState.DONE
    assert job4.data.auto_approvals == 4  # backlog, architecture, test cases, written tests


def test_supervisor_error_falls_back_to_manual(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    gone = ProviderTimeoutError("gone")
    engine, _ = _engine(store, worktrees_root, seed, [gone, gone, gone, APPROVE])  # 2 retries
    project = _project(engine, repo, mode="auto")
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert job.data.supervision is not None and job.data.supervision["acted"] == "error"
    assert (job.history[-1].note or "").startswith("supervisor failed: timeout")
    assert sum(1 for t in job.history if "supervisor attempt" in (t.note or "")) == 2
    assert job.data.auto_approvals == 0
    job = engine.approve(job.id)  # and the next gate works again
    assert job.state is JobState.AWAITING_TEST_APPROVAL


def test_undo_reaches_the_next_role_through_the_inbox(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, [APPROVE, RISKY])
    project = _project(engine, repo, mode="auto")
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        job = client.post(f"/api/projects/{project.id}/jobs", json={"request": "health"}).json()
        job = client.get(f"/api/jobs/{job['id']}").json()
        assert job["state"] == "awaiting_architecture_approval"
        assert job["data"]["supervision"]["acted"] == "none"  # the architecture gate waits
        # the backlog approval was automatic; nothing to undo any more on the current record
        assert client.post(f"/api/jobs/{job['id']}/undo", json={"feedback": "x"}).status_code == 409

        dash = client.get("/api/overview").json()
        assert dash["waiting"][0]["recommendation"] == "approve"
        assert dash["waiting"][0]["risk"] == "high"
        assert dash["auto_approved"] == []

    # a job whose last gate was auto-approved and is now running shows up as undoable
    engine2, provider2 = _engine(store, worktrees_root, seed, [APPROVE])
    engine2.handlers.pop(JobState.ARCHITECTURE)  # stop right after the automatic approval
    project2 = engine2.create_project(
        Project(name="p2", repo_path=repo, supervisor=SupervisorSettings(mode="auto"))
    )
    job2 = engine2.start(engine2.create_job("health", project_id=project2.id).id)
    assert job2.state is JobState.ARCHITECTURE and job2.data.auto_approvals == 1
    assert overview(1, [job2]).auto_approved[0].job_id == job2.id
    job2 = engine2.undo_auto_approval(job2.id, "the backlog misses the audit story")
    assert job2.data.supervision is not None and job2.data.supervision["undone"]
    assert [m.text for m in job2.data.inbox] == [
        "[the human overruled the supervisor's approval of the backlog] "
        "the backlog misses the audit story"
    ]
    assert (job2.history[-1].note or "") == "undo: the backlog misses the audit story"
    assert overview(1, [job2]).auto_approved == []
    engine2.handlers[JobState.ARCHITECTURE] = engine2._architecture
    job2 = engine2.resume(job2.id)  # the architect reads the message
    assert (
        "audit story" in [r for r in provider2.requests if r.role is RoleName.ARCHITECT][-1].prompt
    )


def test_webhook_and_event_on_automatic_approval(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(204)

    engine, _ = _engine(store, worktrees_root, seed, [APPROVE, RISKY])
    engine.http_transport = httpx.MockTransport(handler)
    engine.store.set_setting("notifications.webhook_url", "https://hooks.example/slipwright")
    project = _project(engine, repo, mode="auto")
    with engine.events.subscribe() as events:
        job = engine.start(engine.create_job("health", project_id=project.id).id)
        types = []
        while not events.empty():
            types.append(events.get_nowait().type)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert "supervisor.auto_approved" in types
    assert len(posted) == 1
    assert posted[0]["url"] == "https://hooks.example/slipwright"
    assert posted[0]["body"]["gate"] == "backlog" and posted[0]["body"]["job_id"] == job.id

    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        assert (
            client.get("/api/settings/notifications").json()["webhook_url"].startswith("https://")
        )
        assert (
            client.put("/api/settings/notifications", json={"webhook_url": "ftp://x"}).status_code
            == 400
        )
        assert (
            client.put("/api/settings/notifications", json={"webhook_url": ""}).json()[
                "webhook_url"
            ]
            is None
        )


def test_project_supervisor_settings_through_the_api(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, [APPROVE])
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        created = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        assert created["supervisor"] == {
            "mode": "assisted",
            "threshold": 0.8,
            "cap": 3,
            "allow_final_gate": False,
        }
        resp = client.patch(
            f"/api/projects/{created['id']}",
            json={
                "supervisor": {
                    "mode": "auto",
                    "threshold": 0.9,
                    "cap": 1,
                    "allow_final_gate": False,
                }
            },
        )
        assert resp.status_code == 200 and resp.json()["supervisor"]["mode"] == "auto"
        assert (
            client.patch(
                f"/api/projects/{created['id']}", json={"supervisor": {"mode": "yolo"}}
            ).status_code
            == 422
        )


def test_supervisor_ui_sources() -> None:
    text = {p.name: p.read_text(encoding="utf-8") for p in (WEB / "src").rglob("*.tsx")}
    assert (
        "recommendation" in text["PipelineTab.tsx"]
        and "Select all recommended" in text["PipelineTab.tsx"]
    )
    assert "auto_approved" in text["DashboardPage.tsx"] and "Undo" in text["DashboardPage.tsx"]
    assert (
        "supervisor" in text["ProjectDialogs.tsx"]
        and "allow_final_gate" in text["ProjectDialogs.tsx"]
    )
    assert "Recommendation" in text["GateActions.tsx"] or "recommend" in text["GateActions.tsx"]
    events = (WEB / "src" / "api" / "events.ts").read_text(encoding="utf-8")
    assert "supervisor.auto_approved" in events
