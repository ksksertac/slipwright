"""T9.7 — budgets, retries, loop detection, the supervisor's choice on a failed build gate,
context hygiene."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.pipeline import lane_for
from slipwright.providers import ModelRequest, ProviderError, ProviderTimeoutError
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import BudgetSettings, Project, SupervisorSettings
from slipwright.store import JobStore
from tests.pipeline import FALSE, full_engine, full_provider

WEB = Path(__file__).resolve().parent.parent / "web"


def _context(req: ModelRequest) -> dict[str, Any]:
    text = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    ctx: dict[str, Any] = json.loads(text)
    return ctx


# --- budgets -------------------------------------------------------------------------------


def test_invocation_budget_fails_the_job_with_the_reason(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=2))
    project = engine.create_project(
        Project(name="demo", repo_path=repo, budget=BudgetSettings(max_invocations=3))
    )
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(job.id)  # PO (1), architect (2)
    job = engine.approve(job.id)  # backend phase 1 (3), review is the 4th call: refused
    assert job.state is JobState.FAILED
    assert job.history[-1].note == "budget exhausted: 3 model calls (limit 3)"
    assert job.data.invocations == 3
    assert len(job.data.invocation_log) == 3
    entry = job.data.invocation_log[-1]
    assert entry["role"] == "developer" and entry["phase"] == 1 and entry["prompt_chars"] > 100
    assert entry["attempts"] == 1 and entry["ok"] is True


def test_wall_clock_budget(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    project = engine.create_project(
        Project(name="demo", repo_path=repo, budget=BudgetSettings(max_wall_clock_s=60))
    )
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL  # well within a minute
    # pretend the job started long ago
    first = job.history[0].model_copy(
        update={"at": job.history[0].at.replace(year=job.history[0].at.year - 1)}
    )
    job.history[0] = first
    assert engine._budget_problem(job) is not None
    assert "elapsed (limit 60s)" in (engine._budget_problem(job) or "")


def test_token_budget_counts_usage(seed: Profile, repo: Path, tmp_path: Path) -> None:
    from slipwright.schemas.job import Job

    engine = full_engine(
        JobStore(tmp_path / "j.sqlite3"), tmp_path / "wt", seed, full_provider(seed)
    )
    job = Job(id="j", request="x", repo_path=repo)
    job.data.tokens_used = 5000
    assert engine._budget_problem(job) is None  # no project: unlimited
    engine.store.close()


# --- retries -------------------------------------------------------------------------------


def test_retry_then_success_is_recorded(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    base = provider.replies[RoleName.PO]
    calls: list[int] = []

    def flaky(req: ModelRequest) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise ProviderTimeoutError("slow")
        if len(calls) == 2:
            raise ProviderError("502 bad gateway")
        return base

    provider.replies[RoleName.PO] = flaky
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    notes = [t.note or "" for t in job.history if "retrying" in (t.note or "")]
    assert notes == [
        "po attempt 1 failed: timeout; retrying in 0s (1/2 retries used)",
        "po attempt 2 failed: provider_error; retrying in 0s (2/2 retries used)",
    ]
    assert job.data.invocation_log[0]["attempts"] == 3 and job.data.invocations == 3


def test_refusals_are_not_retried_and_retries_are_per_role(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    from slipwright.providers import ProviderRefusalError

    provider = full_provider(seed, phases=1)
    calls: list[int] = []

    def refuse(req: ModelRequest) -> Any:
        calls.append(1)
        raise ProviderRefusalError("no")

    provider.replies[RoleName.PO] = refuse
    data = seed.model_dump(mode="json")
    data["roles"]["po"]["retries"] = 5
    seed5 = Profile.model_validate(data)
    engine = full_engine(store, worktrees_root, seed5, provider)
    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.FAILED and len(calls) == 1
    assert job.history[-1].note == "po failed: refused"

    # a role with retries=0 gets exactly one attempt
    data["roles"]["po"]["retries"] = 0
    seed0 = Profile.model_validate(data)
    calls.clear()

    def timeout(req: ModelRequest) -> Any:
        calls.append(1)
        raise ProviderTimeoutError("slow")

    provider.replies[RoleName.PO] = timeout
    engine0 = full_engine(store, worktrees_root, seed0, provider)
    job0 = engine0.start(engine0.create_job("y", repo).id)
    assert job0.state is JobState.FAILED and len(calls) == 1
    assert job0.history[-1].note == "po failed: timeout"


def test_backoff_doubles(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile, monkeypatch: Any
) -> None:
    import slipwright.engine as engine_module

    slept: list[float] = []
    monkeypatch.setattr(engine_module.time, "sleep", lambda s: slept.append(s))
    provider = full_provider(seed, phases=1)

    def timeout(req: ModelRequest) -> Any:
        raise ProviderTimeoutError("slow")

    provider.replies[RoleName.PO] = timeout
    engine = full_engine(store, worktrees_root, seed, provider, retry_backoff_s=1.5)
    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.FAILED
    assert slept == [1.5, 3.0]


# --- loop detection ----------------------------------------------------------------------------


def test_loop_stops_at_the_decision_gate_and_the_human_decides(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    broken = seed.model_copy(update={"test_cmd": FALSE})
    provider = full_provider(broken, phases=1)
    engine = full_engine(store, worktrees_root, broken, provider)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)

    assert job.state is JobState.AWAITING_DECISION
    assert (
        job.history[-1].note == "loop detected: developer produced the same output twice in a row"
    )
    assert job.data.resume_state == "developing"
    assert lane_for(job).pending_approval == "decision"
    dev = [r for r in provider.requests if r.role is RoleName.DEVELOPER]
    assert len(dev) == 2

    # reject with feedback: the specialist runs again and reads the feedback from the inbox;
    # the same answer twice more brings the job back to the gate (attempts 3 and 4)
    job = engine.reject(job.id, "the test expects yes, write yes")
    dev = [r for r in provider.requests if r.role is RoleName.DEVELOPER]
    assert len(dev) == 4
    assert "the test expects yes, write yes" in dev[2].prompt
    assert "the test expects yes, write yes" not in dev[3].prompt  # delivered exactly once
    inbox = [t.note or "" for t in job.history if (t.note or "").startswith("inbox:")]
    assert inbox and "consumed by developer" in inbox[-1]
    assert "rejected: the test expects yes, write yes" in [t.note for t in job.history]
    # the same answer again: back at the gate, not a silent third round
    assert job.state is JobState.AWAITING_DECISION


def test_different_outputs_never_trip_the_loop_check(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    broken = seed.model_copy(update={"test_cmd": FALSE})
    provider = full_provider(broken, phases=1)
    n: list[int] = []

    def dev(req: ModelRequest) -> Any:
        n.append(1)
        return {
            "summary": f"try {len(n)}",
            "phase_complete": True,
            "changes": [{"path": "OK", "content": f"try {len(n)}\n"}],
        }

    for role in (RoleName.DEVELOPER, RoleName.BACKEND):
        provider.replies[role] = dev
    engine = full_engine(store, worktrees_root, broken, provider)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)
    assert job.state is JobState.FAILED  # three honest attempts, then the usual failure
    assert job.history[-1].note == "build gate failed 3 times on phase 1"


def test_decision_gate_api_and_pipeline_card(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    broken = seed.model_copy(update={"test_cmd": FALSE})
    engine = full_engine(store, worktrees_root, broken, full_provider(broken, phases=1))
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        project = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        job = client.post(f"/api/projects/{project['id']}/jobs", json={"request": "x"}).json()
        client.post(f"/api/jobs/{job['id']}/approve")
        client.post(f"/api/jobs/{job['id']}/approve")
        job = client.get(f"/api/jobs/{job['id']}").json()
        assert job["state"] == "awaiting_decision"
        lanes = client.get(f"/api/projects/{project['id']}/pipeline").json()["lanes"]
        gate = next(s for s in lanes[0]["steps"] if s["key"] == "decision_gate")
        assert gate["status"] == "waiting" and gate["pending"] == "decision"
        assert (
            lanes[0]["steps"].index(gate)
            == [s["key"] for s in lanes[0]["steps"]].index("phase:1") + 1
        )
        progress = client.get(f"/api/projects/{project['id']}/progress").json()
        assert progress["jobs"][0]["pending_approval"] == "decision"
        resp = client.post(f"/api/jobs/{job['id']}/reject", json={"feedback": "look again"})
        assert resp.status_code == 200 and resp.json()["state"] == "developing"


# --- the supervisor on a failed build gate ------------------------------------------------------


def _choice_engine(
    store: JobStore, worktrees_root: Path, seed: Profile, choices: list[str]
) -> tuple[Engine, Any]:
    broken = seed.model_copy(update={"test_cmd": FALSE})
    provider = full_provider(broken, phases=1)
    n: list[int] = []

    def dev(req: ModelRequest) -> Any:  # distinct outputs: no loop
        n.append(1)
        return {
            "summary": f"try {len(n)}",
            "phase_complete": True,
            "changes": [{"path": "OK", "content": f"try {len(n)}\n"}],
        }

    for role in (RoleName.DEVELOPER, RoleName.BACKEND):
        provider.replies[role] = dev
    sup_calls: list[dict[str, Any]] = []

    def sup(req: ModelRequest) -> Any:
        ctx = _context(req)
        sup_calls.append(ctx)
        if "failed_build_gate" not in ctx["material"]:
            return {"summary": "ok", "decision": "approve", "confidence": 0.9, "risk": "low"}
        asked = sum(1 for c in sup_calls if "failed_build_gate" in c["material"])
        choice = choices[min(asked - 1, len(choices) - 1)]
        return {
            "summary": "decided",
            "decision": choice,
            "confidence": 0.8,
            "risk": "medium",
            "reasons": [f"because {choice}"],
        }

    provider.replies[RoleName.SUPERVISOR] = sup
    engine = full_engine(store, worktrees_root, broken, provider, supervisor_mode=None)
    engine._sup_calls = sup_calls  # type: ignore[attr-defined]
    return engine, provider


def test_supervisor_chooses_fix(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _choice_engine(store, worktrees_root, seed, ["fix"])
    project = engine.create_project(
        Project(name="demo", repo_path=repo, supervisor=SupervisorSettings(mode="assisted"))
    )
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(engine.approve(job.id).id)
    assert job.state is JobState.FAILED  # fix, fix, then out of attempts
    notes = [t.note or "" for t in job.history]
    assert "supervisor: fix (because fix)" in notes
    assert any("supervisor: same specialist fixes (because fix)" in n for n in notes)
    calls = engine._sup_calls  # type: ignore[attr-defined]
    asked = [c for c in calls if "failed_build_gate" in c["material"]]
    assert len(asked) == 2  # attempts 1 and 2 (the third failure ends the job)
    assert asked[0]["material"]["failed_build_gate"]["phase"]["number"] == 1
    assert "exit 1" in asked[0]["material"]["failed_build_gate"]["output"]


def test_supervisor_chooses_replan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _choice_engine(store, worktrees_root, seed, ["replan"])
    project = engine.create_project(
        Project(name="demo", repo_path=repo, supervisor=SupervisorSettings(mode="assisted"))
    )
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(engine.approve(job.id).id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert any("supervisor: re-plan (because replan)" in (t.note or "") for t in job.history)
    architect = [r for r in provider.requests if r.role is RoleName.ARCHITECT]
    assert len(architect) == 2
    ctx = _context(architect[-1])
    assert "failed the build gate" in ctx["feedback"] and "previous_plan" in ctx
    assert job.data.phase_index == 0 and job.data.build_attempts == 0


def test_supervisor_asks_the_human(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _choice_engine(store, worktrees_root, seed, ["ask_human", "fix"])
    project = engine.create_project(
        Project(name="demo", repo_path=repo, supervisor=SupervisorSettings(mode="assisted"))
    )
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(engine.approve(job.id).id)
    assert job.state is JobState.AWAITING_DECISION
    assert "supervisor: asks you (because ask_human)" in (job.history[-1].note or "")
    assert job.data.resume_state == "developing"
    dev = [r for r in provider.requests if r.role is RoleName.DEVELOPER]
    assert len(dev) == 1
    job = engine.approve(job.id)  # continue: the specialist fixes (attempt 2), then 3, then fails
    assert job.state is JobState.FAILED
    assert len([r for r in provider.requests if r.role is RoleName.DEVELOPER]) == 3


def test_manual_projects_keep_the_old_behaviour(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _choice_engine(store, worktrees_root, seed, ["replan"])
    project = engine.create_project(
        Project(name="demo", repo_path=repo, supervisor=SupervisorSettings(mode="manual"))
    )
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(engine.approve(job.id).id)
    assert job.state is JobState.FAILED
    assert [r for r in provider.requests if r.role is RoleName.SUPERVISOR] == []


# --- context hygiene ---------------------------------------------------------------------------


def test_roles_get_an_outline_not_the_whole_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=2)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    dev = _context(next(r for r in provider.requests if r.role is RoleName.DEVELOPER))
    assert "breakdown" not in dev["plan"] and [p["goal"] for p in dev["plan"]["phases"]]
    assert "files" not in dev["plan"]["phases"][0]  # other phases' file lists are noise
    assert dev["current_phase"]["files"] == ["OK"]  # its own phase in full
    qa = _context(
        next(r for r in provider.requests if r.role is RoleName.QA and "stage" in _context(r))
    )
    assert "breakdown" not in qa["plan"] and "branch_diff" in qa
    architect = _context(next(r for r in provider.requests if r.role is RoleName.ARCHITECT))
    assert "branch_diff" not in architect and "phase_diff" not in architect
    assert all(e["prompt_chars"] > 0 for e in job.data.invocation_log)


def test_hardening_ui_sources() -> None:
    text = {p.name: p.read_text(encoding="utf-8") for p in (WEB / "src").rglob("*.tsx")}
    assert "awaiting_decision" in text["ui.tsx"]
    assert '"decision"' in text["GateActions.tsx"]
    assert "DecisionGate" in text["JobPage.tsx"] and "invocation_log" in text["JobPage.tsx"]
    assert (
        "budget" in text["ProjectDialogs.tsx"] and "max_invocations" in text["ProjectDialogs.tsx"]
    )
