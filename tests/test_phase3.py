from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from slipwright.engine import Engine
from slipwright.gates import build_gate
from slipwright.providers import ModelRequest
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName, load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"
PY = sys.executable

# The gate passes only when the Developer wrote "yes" into OK.
CHECK = f"\"{PY}\" -c \"import sys; sys.exit(0 if open('OK').read().strip() == 'yes' else 1)\""
TRUE = f'"{PY}" -c "print(\'built\')"'


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE).model_copy(update={"build_cmd": TRUE, "test_cmd": CHECK})


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


def _engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider
) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8500, end=8599))
    engine = Engine(store, ws, seed_profile=seed, provider=provider)
    engine.handlers.pop(JobState.QA, None)  # phase 3 ends when the job reaches QA
    return engine


def _plan(*goals: str) -> dict[str, Any]:
    return {
        "summary": f"{len(goals)} phases",
        "phases": [{"goal": g, "files": ["OK"]} for g in goals],
    }


def _dev(answers: Callable[[ModelRequest], str]) -> Callable[[ModelRequest], dict[str, Any]]:
    def reply(req: ModelRequest) -> dict[str, Any]:
        return {
            "summary": "wrote OK",
            "phase_complete": True,
            "changes": [{"path": "OK", "content": answers(req) + "\n"}],
        }

    return reply


def _provider(seed: Profile, plan: dict[str, Any], dev: Any) -> ScriptedProvider:
    p = canned(seed)
    p.replies[RoleName.PLANNER] = plan
    p.replies[RoleName.DEVELOPER] = dev
    return p


def _to_plan_gate(engine: Engine, repo: Path) -> Job:
    job = engine.start(engine.create_job("make OK say yes", repo).id)
    assert job.state is JobState.AWAITING_PROFILE_APPROVAL
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_PLAN_APPROVAL
    return job


def _phase_number(req: ModelRequest) -> int:
    ctx = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    return int(json.loads(ctx)["current_phase"]["number"])


# --- T3.1 planner -------------------------------------------------------------------------


def test_planner_produces_plan_and_stops_at_gate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, _plan("first", "second"), _dev(lambda _: "yes"))
    engine = _engine(store, worktrees_root, seed, provider)

    job = _to_plan_gate(engine, repo)

    assert job.data.plan is not None
    assert [p["goal"] for p in job.data.plan["phases"]] == ["first", "second"]
    assert job.data.phase_index == 0
    assert job.history[-1].note == "planner: 2 phases (2 phases)"
    assert json.loads(job.history[-1].detail or "{}")["phases"][1]["goal"] == "second"
    planner_req = [r for r in provider.requests if r.role is RoleName.PLANNER][0]
    assert planner_req.model == seed.roles[RoleName.PLANNER].model
    assert "make OK say yes" in planner_req.prompt


def test_plan_reject_reruns_with_feedback_bounded_to_three_rounds(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, _plan("only"), _dev(lambda _: "yes"))
    engine = _engine(store, worktrees_root, seed, provider)
    job = _to_plan_gate(engine, repo)

    for round_no in (1, 2, 3):
        job = engine.reject(job.id, f"too vague ({round_no})")
        assert job.state is JobState.AWAITING_PLAN_APPROVAL
        req = provider.requests[-1]
        assert req.role is RoleName.PLANNER
        assert f"too vague ({round_no})" in req.prompt
        assert '"previous_plan"' in req.prompt and '"only"' in req.prompt

    planner_calls = len([r for r in provider.requests if r.role is RoleName.PLANNER])
    assert planner_calls == 4  # initial + 3 re-runs

    job = engine.reject(job.id, "still no")
    assert job.state is JobState.FAILED
    assert "rejected 4 times" in (job.history[-1].note or "")
    assert len([r for r in provider.requests if r.role is RoleName.PLANNER]) == planner_calls


# --- T3.2 developer -----------------------------------------------------------------------


def test_developer_runs_one_phase_per_invocation_and_records_diffs(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, _plan("first", "second"), _dev(lambda _: "yes"))
    engine = _engine(store, worktrees_root, seed, provider)
    job = _to_plan_gate(engine, repo)

    job = engine.approve(job.id)

    assert job.state is JobState.QA
    dev_reqs = [r for r in provider.requests if r.role is RoleName.DEVELOPER]
    assert [_phase_number(r) for r in dev_reqs] == [1, 2]
    assert all(r.model == seed.roles[RoleName.DEVELOPER].model for r in dev_reqs)
    assert job.data.phase_index == 2

    states = [(t.from_state, t.to_state) for t in job.history]
    assert states[-4:] == [
        (JobState.DEVELOPING, JobState.BUILD_GATE),
        (JobState.BUILD_GATE, JobState.DEVELOPING),
        (JobState.DEVELOPING, JobState.BUILD_GATE),
        (JobState.BUILD_GATE, JobState.QA),
    ]
    diffs = [t.detail for t in job.history if t.to_state is JobState.BUILD_GATE]
    assert len(diffs) == 2
    assert "+yes" in (diffs[0] or "")
    assert diffs[1] == "(no changes)"  # phase two rewrote the same content

    # each passed phase is a commit on the job branch
    assert job.worktree_path is not None
    log = subprocess.run(
        ["git", "-C", str(job.worktree_path), "log", "--format=%s"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert log[0] == "slipwright: phase 1: first"
    assert (job.worktree_path / "OK").read_text(encoding="utf-8") == "yes\n"


def test_phase_progress_persists_so_restart_resumes_mid_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, _plan("first", "second"), _dev(lambda _: "yes"))
    engine_a = _engine(store, worktrees_root, seed, provider)
    job = _to_plan_gate(engine_a, repo)

    # "die" right after the first gate passes: the DEVELOPING handler disappears
    real_gate = engine_a.handlers[JobState.BUILD_GATE]

    def gate_then_die(current: Job) -> Job:
        engine_a.handlers.pop(JobState.DEVELOPING)
        return real_gate(current)

    engine_a.handlers[JobState.BUILD_GATE] = gate_then_die
    job = engine_a.approve(job.id)
    assert job.state is JobState.DEVELOPING
    assert store.get(job.id).data.phase_index == 1

    engine_b = _engine(store, worktrees_root, seed, provider)
    job = engine_b.resume(job.id)

    assert job.state is JobState.QA
    dev_reqs = [r for r in provider.requests if r.role is RoleName.DEVELOPER]
    assert [_phase_number(r) for r in dev_reqs] == [1, 2]


def test_developer_without_write_permission_fails_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    data = seed.model_dump(mode="json")
    data["roles"]["developer"]["permissions"] = ["read_files"]
    seed = Profile.model_validate(data)
    provider = _provider(seed, _plan("first"), _dev(lambda _: "yes"))
    engine = _engine(store, worktrees_root, seed, provider)
    job = _to_plan_gate(engine, repo)

    job = engine.approve(job.id)

    assert job.state is JobState.FAILED
    assert "PermissionError" in (job.history[-1].note or "")


# --- T3.3 build gate ----------------------------------------------------------------------


def test_build_gate_runs_profile_commands(seed: Profile, tmp_path: Path) -> None:
    (tmp_path / "OK").write_text("no\n", encoding="utf-8")
    failed = build_gate(seed, tmp_path)
    assert not failed.ok
    assert "built" in failed.output and "[test: exit 1]" in failed.output

    (tmp_path / "OK").write_text("yes\n", encoding="utf-8")
    passed = build_gate(seed, tmp_path)
    assert passed.ok
    assert "[test: exit 0]" in passed.output


def test_gate_passes_first_try(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, _plan("first"), _dev(lambda _: "yes"))
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.approve(_to_plan_gate(engine, repo).id)

    assert job.state is JobState.QA
    assert job.data.build_attempts == 0
    assert len([r for r in provider.requests if r.role is RoleName.DEVELOPER]) == 1


def test_gate_failure_feeds_output_back_and_passes_on_retry(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    def answers(req: ModelRequest) -> str:
        return "yes" if '"build_failure":' in req.prompt else "no"

    provider = _provider(seed, _plan("first"), _dev(answers))
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.approve(_to_plan_gate(engine, repo).id)

    assert job.state is JobState.QA
    dev_reqs = [r for r in provider.requests if r.role is RoleName.DEVELOPER]
    assert len(dev_reqs) == 2
    assert "[test: exit 1]" in dev_reqs[1].prompt  # the captured gate output
    notes = [t.note or "" for t in job.history]
    assert any("build gate failed on phase 1 (attempt 1/3)" in n for n in notes)
    assert any("fix attempt 1" in n for n in notes)
    assert job.data.build_attempts == 0


def test_gate_exhausts_retries_and_fails_with_output(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, _plan("first"), _dev(lambda _: "no"))
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.approve(_to_plan_gate(engine, repo).id)

    assert job.state is JobState.FAILED
    assert len([r for r in provider.requests if r.role is RoleName.DEVELOPER]) == 3
    assert job.history[-1].note == "build gate failed 3 times on phase 1"
    assert "[test: exit 1]" in (job.history[-1].detail or "")
    assert job.data.build_attempts == 3
