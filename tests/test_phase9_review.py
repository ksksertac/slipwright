"""T9.5 — the standards review after every phase."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.board import project_board
from slipwright.engine import Engine
from slipwright.pipeline import StepStatus, lane_for
from slipwright.providers import ModelRequest
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.fakes import FakeJira
from tests.pipeline import full_engine, full_provider, set_plan

HUMAN = "ada@example.com"
WEB = Path(__file__).resolve().parent.parent / "web"

BLOCKING = {
    "section": "Kafka consumers and retries",
    "file": "OK",
    "line": 1,
    "severity": "blocking",
    "message": "offsets are committed before the side effect is durable",
    "fix": "commit after the write",
}
ADVISORY = {
    "section": "Naming",
    "file": "OK",
    "severity": "advisory",
    "message": "prefer a descriptive name",
}


def _context(req: ModelRequest) -> dict[str, Any]:
    text = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    ctx: dict[str, Any] = json.loads(text)
    return ctx


def _reviews(provider: Any) -> list[ModelRequest]:
    return [r for r in provider.requests if r.role is RoleName.QA and "phase_diff" in _context(r)]


def _engine(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    *,
    verdicts: list[list[dict[str, Any]]],
    review: str | None = None,
) -> tuple[Engine, Any]:
    """An engine whose QA reviewer answers with ``verdicts`` in turn (the last one
    repeats); QA's test stages keep their canned replies."""
    provider = full_provider(seed, phases=2)
    set_plan(
        provider,
        seed,
        [
            {"goal": "consume the topic", "files": ["OK"], "domain": "backend"},
            {"goal": "show the count", "files": ["OK"], "domain": "web"},
        ],
    )
    base_qa = provider.replies[RoleName.QA]
    calls: list[int] = []

    def qa(req: ModelRequest) -> Any:
        ctx = _context(req)
        if "phase_diff" not in ctx:
            return base_qa(req) if callable(base_qa) else base_qa
        n = len(calls)
        calls.append(n)
        verdict = verdicts[min(n, len(verdicts) - 1)]
        return {"summary": "reviewed", "violations": verdict}

    provider.replies[RoleName.QA] = qa
    engine = full_engine(store, worktrees_root, seed, provider, review=review)
    return engine, provider


def _start(engine: Engine, repo: Path, *, review: str = "advisory") -> Any:
    project = engine.create_project(Project(name="demo", repo_path=repo, review=review))  # type: ignore[arg-type]
    job = engine.start(engine.create_job("kafka", project_id=project.id).id)
    job = engine.approve(job.id)  # backlog
    return engine.approve(job.id)  # architecture -> develop


def test_reviewer_sees_the_phase_diff_and_the_specialists_standards(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, verdicts=[[]])
    job = _start(engine, repo)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    reviews = _reviews(provider)
    assert len(reviews) == 2  # one per phase
    first = _context(reviews[0])
    assert first["current_phase"]["number"] == 1 and first["current_phase"]["domain"] == "backend"
    assert "+yes" in first["phase_diff"] or "OK" in first["phase_diff"]
    assert first["standards"]["domain"] == "backend"  # the backend specialist's sections
    assert _context(reviews[1])["standards"]["domain"] == "web"
    assert reviews[0].model == seed.roles[RoleName.QA].model
    notes = [t.note or "" for t in job.history if (t.note or "").startswith("review phase")]
    assert notes == ["review phase 1/2: clean", "review phase 2/2: clean"]
    assert [r["verdict"] for r in job.data.reviews] == ["passed", "passed"]
    moves = [(t.from_state, t.to_state) for t in job.history if t.from_state is not t.to_state]
    assert (JobState.BUILD_GATE, JobState.REVIEW) in moves
    assert (JobState.REVIEW, JobState.DEVELOPING) in moves and (
        JobState.REVIEW,
        JobState.QA,
    ) in moves


def test_advisory_project_records_violations_and_never_blocks(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, verdicts=[[BLOCKING, ADVISORY]])
    job = _start(engine, repo, review="advisory")
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert len(_reviews(provider)) == 2  # no fix rounds
    dev = [r for r in provider.requests if r.role in (RoleName.BACKEND, RoleName.WEB_UI)]
    assert len(dev) == 2 and not any("standards_review" in _context(r) for r in dev)
    notes = [t.note or "" for t in job.history if (t.note or "").startswith("review phase")]
    assert notes[0] == "review phase 1/2: 2 violation(s), 1 blocking, 1 advisory"
    assert job.data.reviews[0]["verdict"] == "passed (advisory)"
    assert job.data.reviews[0]["blocking"] == 1 and job.data.review_violations == []
    # the board carries the counts on the task
    board = project_board(job.project_id or "", [job])
    tasks = [t for e in board.epics for s in e.stories for t in s.tasks]
    assert [(t.phase, t.violations, t.blocking) for t in tasks] == [(1, 2, 1), (2, 2, 1)]


def test_blocking_project_sends_the_phase_back_twice_then_asks_the_human(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, verdicts=[[BLOCKING]] * 3 + [[]])
    job = _start(engine, repo, review="blocking")

    assert job.state is JobState.AWAITING_REVIEW_APPROVAL
    assert job.data.phase_index == 1  # phase 1 is built; the gate decides whether it stands
    assert job.data.review_rounds == 2
    reviews = _reviews(provider)
    assert len(reviews) == 3  # original + two fix rounds, all on phase 1
    assert [_context(r)["current_phase"]["number"] for r in reviews] == [1, 1, 1]
    assert [_context(r)["review_round"] for r in reviews] == [0, 1, 2]
    backend = [r for r in provider.requests if r.role is RoleName.BACKEND]
    assert len(backend) == 3
    assert "standards_review" not in _context(backend[0])
    fix = _context(backend[1])["standards_review"]
    assert fix["round"] == 1 and fix["violations"][0]["section"] == "Kafka consumers and retries"
    assert "standards_review" in backend[1].prompt  # the instructions mention it
    notes = [t.note or "" for t in job.history if (t.note or "").startswith("review phase")]
    assert notes == [
        "review phase 1/2: 1 violation(s), 1 blocking, 0 advisory; fix round 1/2",
        "review phase 1/2: 1 violation(s), 1 blocking, 0 advisory; fix round 2/2",
        "review phase 1/2: 1 violation(s), 1 blocking, 0 advisory after 2 fix round(s); "
        "needs your decision",
    ]
    assert [r["verdict"] for r in job.data.reviews] == [
        "fix round 1/2",
        "fix round 2/2",
        "needs your decision",
    ]
    # the fix rounds are ordinary phases through the build gate, each committed
    fixes = [t.note or "" for t in job.history if "review fix" in (t.note or "")]
    assert len(fixes) == 2 and fixes[0].startswith("backend phase 1/2, review fix 1:")

    cards = {c.key: c for c in lane_for(job).steps}
    assert cards["phase:1"].status is StepStatus.RUNNING
    gate = cards["review_gate:1"]
    assert gate.status is StepStatus.WAITING and gate.pending == "review" and gate.gate
    assert lane_for(job).pending_approval == "review"
    assert [c.key for c in lane_for(job).steps][4:7] == ["phase:1", "review_gate:1", "phase:2"]
    board = project_board(job.project_id or "", [job])
    tasks = [t for e in board.epics for s in e.stories for t in s.tasks]
    assert tasks[0].status.value == "in_progress" and tasks[0].blocking == 1

    # accepting the violations continues with phase 2
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert job.data.review_violations == [] and job.data.review_rounds == 0
    assert "approved phase 1 despite the review" in [t.note for t in job.history]
    assert len(_reviews(provider)) == 4  # phase 2 reviewed once, clean
    assert [r["phase"] for r in job.data.reviews] == [1, 1, 1, 2]


def test_rejecting_at_the_review_gate_reworks_the_phase(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, verdicts=[[BLOCKING]] * 3 + [[]])
    job = _start(engine, repo, review="blocking")
    assert job.state is JobState.AWAITING_REVIEW_APPROVAL

    job = engine.reject(job.id, "actually fix the offset commit")
    # the specialist got the human's feedback with the violations and the reviewer passed it
    backend = [r for r in provider.requests if r.role is RoleName.BACKEND]
    assert len(backend) == 4
    ctx = _context(backend[3])["standards_review"]
    assert ctx["feedback"] == "actually fix the offset commit" and ctx["round"] == 0
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert [r["phase"] for r in job.data.reviews] == [1, 1, 1, 1, 2]
    cards = {c.key: c for c in lane_for(job).steps}
    assert cards["review_gate:1"].status is StepStatus.DONE
    assert cards["phase:1"].status is StepStatus.DONE


def test_review_off_skips_the_step(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, provider = _engine(store, worktrees_root, seed, verdicts=[[BLOCKING]])
    job = _start(engine, repo, review="off")
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert _reviews(provider) == [] and job.data.reviews == []
    assert not any(t.to_state is JobState.REVIEW for t in job.history)


def test_blocking_findings_are_commented_on_the_jira_task(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = FakeJira(email="bot@example.com")
    jira.accounts[HUMAN] = "Ada"
    engine, _ = _engine(store, worktrees_root, seed, verdicts=[[BLOCKING], []])
    engine.http_transport = jira.transport
    engine.update_jira_settings(
        site_url="https://acme.atlassian.net/", email=HUMAN, token="jira_secret"
    )
    project = engine.create_project(
        Project(name="demo", repo_path=repo, jira_project_key="DEM", review="blocking")
    )
    job = engine.start(engine.create_job("kafka", project_id=project.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL  # round 1 blocked, round 2 clean
    assert job.data.jira_last_error is None, job.data.jira_last_error
    task_key = job.data.jira_keys["t1"]
    comments = [c for c in jira.comments.get(task_key, []) if "standards review" in c]
    assert len(comments) == 1
    assert "1 blocking violation(s) (fix round 1/2)" in comments[0]
    assert "[Kafka consumers and retries] OK:1: offsets are committed" in comments[0]
    assert "review:1:0" in job.data.jira_marks


def test_project_review_mode_is_settable_through_the_api(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, verdicts=[[]])
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        created = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)})
        assert created.status_code == 201 and created.json()["review"] == "advisory"
        pid = created.json()["id"]
        strict = client.post(
            "/api/projects", json={"name": "strict", "repo_path": str(repo), "review": "blocking"}
        )
        assert strict.status_code == 201 and strict.json()["review"] == "blocking"
        resp = client.patch(f"/api/projects/{pid}", json={"review": "blocking"})
        assert resp.status_code == 200 and resp.json()["review"] == "blocking"
        assert client.patch(f"/api/projects/{pid}", json={"review": "loud"}).status_code == 422
        assert client.get(f"/api/projects/{pid}").json()["review"] == "blocking"


def test_review_ui_sources() -> None:
    text = {p.name: p.read_text(encoding="utf-8") for p in (WEB / "src").rglob("*.tsx")}
    assert "awaiting_review_approval" in text["ui.tsx"]
    assert '"review"' in text["GateActions.tsx"]
    assert "ReviewGate" in text["JobPage.tsx"] and "ViolationsTable" in text["Review.tsx"]
    assert "review" in text["ProjectDialogs.tsx"]  # off / advisory / blocking
    assert "blocking" in text["ProjectPage.tsx"]  # the board badge
