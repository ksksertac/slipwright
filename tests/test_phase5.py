from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from slipwright.engine import WORKING_STATES, Engine
from slipwright.githost import CiState, CiStatus
from slipwright.providers import ModelRequest
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.roles.specialists import DEVELOPER_ROLES
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile, RoleName, load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace
from slipwright.workspace import git as g

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"
PY = sys.executable
CHECK = f"\"{PY}\" -c \"import sys; sys.exit(0 if open('OK').read().strip() == 'yes' else 1)\""
TRUE = f'"{PY}" -c "print(\'built\')"'


class FakeHost:
    def __init__(self) -> None:
        self.prs: list[str] = []
        self.lock = threading.Lock()

    def push(self, worktree: Path, branch: str) -> None:
        pass

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        with self.lock:
            self.prs.append(branch)
            return f"https://example.test/pr/{len(self.prs)}"

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        return CiStatus(CiState.SUCCESS, summary="ci: success")


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE).model_copy(update={"build_cmd": TRUE, "test_cmd": CHECK})


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


DOMAINS = ["general", "backend", "web", "mobile"]


def _provider(seed: Profile, phases: int = 2) -> ScriptedProvider:
    """Phases cycle through the domains so every specialist gets a turn."""
    p = canned(seed)
    p.replies[RoleName.PLANNER] = {
        "summary": f"{phases} phases",
        "phases": [
            {"goal": f"step {i + 1}", "files": ["OK"], "domain": DOMAINS[i % len(DOMAINS)]}
            for i in range(phases)
        ],
    }
    for role in DEVELOPER_ROLES:
        p.replies[role] = {
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


def _engine(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider
) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8700, end=8799))
    return Engine(
        store, ws, seed_profile=seed, provider=provider, git_host=FakeHost(), ci_poll_s=0.0
    )


def _drive(engine: Engine, job: Job) -> Job:
    """Approve every gate until the job ends or reaches a state the engine cannot run."""
    while True:
        if job.is_terminal:
            return job
        if job.state in APPROVAL_STATES:
            job = engine.approve(job.id)
        elif job.state in WORKING_STATES and job.state not in engine.handlers:
            return job
        else:
            job = engine.resume(job.id)


def _requests(provider: ScriptedProvider, role: RoleName) -> list[ModelRequest]:
    return [r for r in provider.requests if r.role is role]


def _context(req: ModelRequest) -> dict[str, Any]:
    import json

    ctx = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    data: dict[str, Any] = json.loads(ctx)
    return data


# --- T5.1 inbox steering ------------------------------------------------------------------


def test_message_queued_mid_plan_reaches_next_developer_once(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, phases=2)
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_PLAN_APPROVAL

    job = engine.message(job.id, "use snake_case everywhere")
    assert [m.pending for m in job.data.inbox] == [True]

    job = engine.approve(job.id)  # plan approved -> developer phase 1, phase 2, qa stage 1

    dev = [r for r in provider.requests if r.role in DEVELOPER_ROLES]  # phase 1 general, 2 backend
    assert len(dev) == 2
    assert _context(dev[0])["messages_from_human"] == ["use snake_case everywhere"]
    assert "messages_from_human" not in _context(dev[1])  # never replayed
    qa = _requests(provider, RoleName.QA)
    assert "messages_from_human" not in _context(qa[0])

    job = store.get(job.id)
    (msg,) = job.data.inbox
    assert msg.consumed_by == "developer" and msg.consumed_at is not None
    consumed = [t for t in job.history if (t.note or "").startswith("inbox:")]
    assert len(consumed) == 1
    assert consumed[0].note == "inbox: 1 message(s) consumed by developer"
    assert "use snake_case everywhere" in (consumed[0].detail or "")
    assert consumed[0].from_state is JobState.DEVELOPING
    assert consumed[0].to_state is JobState.DEVELOPING


def test_every_role_drains_the_inbox(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, phases=1)
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.create_job("x", repo)
    seen: dict[str, str] = {}
    n = 0
    while not job.is_terminal:
        n += 1
        engine.message(job.id, f"note {n}")
        job = engine.approve(job.id) if job.state in APPROVAL_STATES else engine.start(job.id)
        for m in store.get(job.id).data.inbox:
            if m.consumed_by:
                seen[m.text] = m.consumed_by
    assert job.state is JobState.DONE
    assert set(seen.values()) == {r.value for r in PIPELINE_ROLES if r not in DEVELOPER_ROLES} | {
        "developer"
    }
    assert all(not m.pending for m in store.get(job.id).data.inbox)


# --- T5.2 per-role model routing ----------------------------------------------------------


PIPELINE_ROLES = [r for r in RoleName if r is not RoleName.SUPERVISOR]  # gates are manual here


def _assert_routing(provider: ScriptedProvider, profile: Profile) -> None:
    for role in PIPELINE_ROLES:
        reqs = _requests(provider, role)
        assert reqs, f"{role.value} was never invoked"
        for req in reqs:
            assert req.model == profile.roles[role].model, role
            assert req.thinking_depth is profile.roles[role].thinking_depth, role


def test_each_role_uses_exactly_the_model_named_in_the_profile(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, phases=4)
    engine = _engine(store, worktrees_root, seed, provider)
    job = _drive(engine, engine.start(engine.create_job("x", repo).id))
    assert job.state is JobState.DONE
    _assert_routing(provider, seed)
    # the example profile routes DevOps to a different, smaller model than Developer
    assert seed.roles[RoleName.DEVOPS].model != seed.roles[RoleName.DEVELOPER].model


def test_switching_models_in_the_profile_changes_routing_without_code_changes(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    data = seed.model_dump(mode="json")
    depths = ["off", "low", "medium", "high", "max"]
    for i, role in enumerate(RoleName):
        data["roles"][role.value]["model"] = f"model-{i}-for-{role.value}"
        data["roles"][role.value]["thinking_depth"] = depths[i % len(depths)]
    swapped = Profile.model_validate(data)
    provider = _provider(swapped, phases=4)
    engine = _engine(store, worktrees_root, swapped, provider)

    job = _drive(engine, engine.start(engine.create_job("x", repo).id))

    assert job.state is JobState.DONE
    _assert_routing(provider, swapped)
    assert {r.model for r in provider.requests} == {
        f"model-{i}-for-{role.value}" for i, role in enumerate(RoleName) if role in PIPELINE_ROLES
    }


# --- T5.3 dashboard -----------------------------------------------------------------------
# The server-rendered dashboard was replaced by the React app in T8.7; its flows are listed
# in web/PARITY.md and covered by tests/test_phase8.py.


# --- definition of done -------------------------------------------------------------------


def test_two_jobs_run_concurrently_end_to_end_without_interference(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, phases=2)
    engine = _engine(store, worktrees_root, seed, provider)
    jobs = [engine.create_job(f"job {i}", repo) for i in range(2)]
    results: dict[str, Job] = {}
    errors: list[BaseException] = []

    def run(job: Job) -> None:
        try:
            results[job.id] = _drive(engine, engine.start(job.id))
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert errors == []
    done = [results[j.id] for j in jobs]
    assert [j.state for j in done] == [JobState.DONE, JobState.DONE]
    assert len({j.worktree_path for j in done}) == 2
    assert len({j.port for j in done}) == 2
    assert len({j.branch for j in done}) == 2
    for j in done:
        assert j.worktree_path is not None
        assert (j.worktree_path / "OK").read_text(encoding="utf-8") == "yes\n"
        assert g.run(j.worktree_path, "branch", "--show-current").stdout.strip() == j.branch
    assert not (repo / "OK").exists()  # the source checkout is untouched
    assert sorted(engine.git_host.prs) == sorted(j.branch for j in done)  # type: ignore[attr-defined]


@pytest.mark.parametrize("stop_at", sorted(WORKING_STATES, key=lambda s: s.value))
def test_restart_at_every_phase_resumes_the_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile, stop_at: JobState
) -> None:
    provider = _provider(seed, phases=2)
    engine_a = _engine(store, worktrees_root, seed, provider)
    engine_a.handlers.pop(stop_at)  # process "dies" the moment the job enters this state
    job = _drive(engine_a, engine_a.start(engine_a.create_job("x", repo).id))
    assert job.state is stop_at
    assert store.get(job.id).state is stop_at

    engine_b = _engine(store, worktrees_root, seed, provider)
    job = _drive(engine_b, engine_b.resume(job.id))

    assert job.state is JobState.DONE
    assert job.data.phase_index == 2
    assert len(engine_b.git_host.prs) == 1  # type: ignore[attr-defined]


def test_approval_states_never_advance_without_approve(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, phases=1)
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)
    gates: list[JobState] = []
    while not job.is_terminal:
        assert job.state in APPROVAL_STATES
        gates.append(job.state)
        before = len(provider.requests)
        for _ in range(3):
            assert engine.resume(job.id).state is job.state
            assert engine.resume_all()[0].state is job.state
            assert store.get(job.id).state is job.state
        assert len(provider.requests) == before  # no role was invoked at the gate
        job = engine.approve(job.id)
    assert gates == [
        JobState.AWAITING_PROFILE_APPROVAL,
        JobState.AWAITING_PLAN_APPROVAL,
        JobState.AWAITING_TEST_APPROVAL,
        JobState.AWAITING_TEST_APPROVAL,
    ]
    assert job.state is JobState.DONE
