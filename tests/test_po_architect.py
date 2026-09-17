from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from slipwright.engine import Engine, NotAwaitingApproval
from slipwright.providers import ProviderTimeoutError
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.roles.architect import accepted_profile, phase_task_map
from slipwright.roles.results import ArchitectResult, PlanPhase
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName, load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


def _engine(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    provider: ScriptedProvider,
    *,
    stop_after: JobState = JobState.ARCHITECTURE,
) -> Engine:
    """An engine that stops right after the backlog gate (default) or, with
    ``stop_after=JobState.DEVELOPING``, right after the architecture gate."""
    ws = Workspace(worktrees_root, PortAllocator(start=8300, end=8399))
    engine = Engine(
        store,
        ws,
        seed_profile=seed,
        provider=provider,
        supervisor_mode="manual",
        retry_backoff_s=0.0,
    )
    engine.handlers.pop(stop_after, None)
    return engine


def _moves(job: Job) -> list[JobState]:
    """State changes only: retrieval / inbox records sit on the same state."""
    return [t.to_state for t in job.history if t.from_state is not t.to_state]


# --- product owner --------------------------------------------------------------------


def test_po_sees_worktree_and_job_stops_at_backlog_approval(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    (repo / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "manifest"], check=True, capture_output=True
    )
    provider = canned(seed)
    engine = _engine(store, worktrees_root, seed, provider)

    job = engine.create_job("add a /health endpoint", repo)
    job = engine.start(job.id)

    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert job.worktree_path is not None and job.worktree_path.is_dir()
    assert job.port is not None
    assert job.profile is None  # the architect proposes it later
    (request,) = provider.requests
    assert request.role is RoleName.PO
    assert request.model == seed.roles[RoleName.PO].model
    assert "pyproject.toml" in request.prompt
    assert "[project]" in request.prompt
    assert "add a /health endpoint" in request.prompt
    assert _moves(job) == [
        JobState.BACKLOG,
        JobState.AWAITING_BACKLOG_APPROVAL,
    ]
    # the proposed backlog is on the record and on the job
    assert job.history[-1].detail is not None
    assert json.loads(job.history[-1].detail)["epics"][0]["id"] == "e1"
    assert job.data.backlog is not None
    assert job.data.backlog["epics"][0]["stories"][0]["tasks"][0]["id"] == "t1"


def test_approve_leaves_gate_and_reject_reruns_po_with_feedback(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = canned(seed)
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)

    job = engine.reject(job.id, "split the story, one task per endpoint")

    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    assert len(provider.requests) == 2
    assert "split the story, one task per endpoint" in provider.requests[1].prompt
    assert "previous_backlog" in provider.requests[1].prompt
    assert '"id": "t1"' in provider.requests[1].prompt  # the rejected backlog, verbatim
    assert _moves(job) == [
        JobState.BACKLOG,
        JobState.AWAITING_BACKLOG_APPROVAL,
        JobState.BACKLOG,
        JobState.AWAITING_BACKLOG_APPROVAL,
    ]
    assert any("rejected: split the story" in (t.note or "") for t in job.history)

    job = engine.approve(job.id)
    assert job.state is JobState.ARCHITECTURE
    assert job.data.feedback is None
    assert len(provider.requests) == 2  # approval invokes nobody in this phase


def test_approve_and_reject_refused_outside_gate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed, canned(seed))
    job = engine.create_job("x", repo)

    with pytest.raises(NotAwaitingApproval):
        engine.approve(job.id)
    with pytest.raises(NotAwaitingApproval):
        engine.reject(job.id, "no")
    assert store.get(job.id).state is JobState.CREATED


def test_po_failure_moves_job_to_failed(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    def boom(_: object) -> str:
        raise ProviderTimeoutError("model went away")

    engine = _engine(store, worktrees_root, seed, ScriptedProvider({RoleName.PO: boom}))
    job = engine.start(engine.create_job("x", repo).id)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "po failed: timeout after 3 attempts"  # 2 retries (T9.7)
    assert "model went away" in (job.history[-1].detail or "")
    retries = [t.note or "" for t in job.history if "retrying" in (t.note or "")]
    assert retries == [
        "po attempt 1 failed: timeout; retrying in 0s (1/2 retries used)",
        "po attempt 2 failed: timeout; retrying in 0s (2/2 retries used)",
    ]


def test_malformed_backlog_from_po_fails_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = ScriptedProvider({RoleName.PO: {"summary": "x", "breakdown": {"epics": "no"}}})
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "po failed: malformed_output after 3 attempts"


# --- architect ------------------------------------------------------------------------


def _to_architecture_gate(
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider, repo: Path
) -> tuple[Engine, Job]:
    engine = _engine(store, worktrees_root, seed, provider, stop_after=JobState.DEVELOPING)
    job = engine.start(engine.create_job("add a /health endpoint", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    return engine, engine.approve(job.id)


def test_architect_designs_from_the_approved_backlog(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = canned(seed)
    engine, job = _to_architecture_gate(store, worktrees_root, seed, provider, repo)

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert job.profile == seed  # the canned architect echoes the seed
    request = provider.requests[-1]
    assert request.role is RoleName.ARCHITECT
    assert "backlog" in request.prompt and '"id": "t1"' in request.prompt
    assert "seed_profile" in request.prompt
    assert job.data.plan is not None
    assert [p["task_id"] for p in job.data.plan["phases"]] == ["t1"]
    # the task now knows which phase builds it
    task = job.data.plan["breakdown"]["epics"][0]["stories"][0]["tasks"][0]
    assert task["phase"] == 1
    assert job.history[-1].note is not None and job.history[-1].note.startswith("architect:")
    assert json.loads(job.history[-1].detail or "{}")["profile"]["language"] == "python"


def test_architect_roles_always_come_from_seed(seed: Profile) -> None:
    data = seed.model_dump(mode="json")
    data["language"] = "typescript"
    data["roles"]["developer"]["model"] = "model-the-architect-picked"
    result = ArchitectResult(
        summary="ts",
        profile=Profile.model_validate(data),
        phases=[PlanPhase(goal="g", files=[], task_id="t1")],
    )

    profile = accepted_profile(result, seed)

    assert profile.language == "typescript"
    assert profile.roles == seed.roles


def test_phase_task_map_requires_one_phase_per_task(seed: Profile) -> None:
    def result(*task_ids: str) -> ArchitectResult:
        return ArchitectResult(
            summary="x",
            profile=seed,
            phases=[PlanPhase(goal=t, files=[], task_id=t) for t in task_ids],
        )

    assert phase_task_map(result("t2", "t1").phases, ["t1", "t2"]) == {"t2": 1, "t1": 2}
    missing = phase_task_map(result("t1").phases, ["t1", "t2"])
    assert isinstance(missing, str) and "t2" in missing
    unknown = phase_task_map(result("t1", "t9").phases, ["t1"])
    assert isinstance(unknown, str) and "t9" in unknown


def test_architect_plan_that_ignores_the_backlog_fails_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = canned(seed)
    provider.replies[RoleName.ARCHITECT] = {
        "summary": "wrong task",
        "profile": seed.model_dump(mode="json"),
        "decisions": [],
        "phases": [{"goal": "g", "files": [], "task_id": "t42"}],
    }
    _, job = _to_architecture_gate(store, worktrees_root, seed, provider, repo)

    assert job.state is JobState.FAILED
    assert "does not match the backlog" in (job.history[-1].note or "")


def test_reject_architecture_reruns_architect_with_previous_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = canned(seed)
    engine, job = _to_architecture_gate(store, worktrees_root, seed, provider, repo)

    job = engine.reject(job.id, "use poetry, not pip")

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert [r.role for r in provider.requests] == [
        RoleName.PO,
        RoleName.ARCHITECT,
        RoleName.ARCHITECT,
    ]
    prompt = provider.requests[-1].prompt
    assert "use poetry, not pip" in prompt
    assert "previous_plan" in prompt and "previous_profile" in prompt
    assert _moves(job)[-3:] == [
        JobState.AWAITING_ARCHITECTURE_APPROVAL,
        JobState.ARCHITECTURE,
        JobState.AWAITING_ARCHITECTURE_APPROVAL,
    ]

    job = engine.approve(job.id)
    assert job.state is JobState.DEVELOPING
    assert len(provider.requests) == 3


# --- durability -----------------------------------------------------------------------

_CHILD = """
import sys, time
from pathlib import Path
from slipwright.engine import Engine
from slipwright.providers.scripted import canned
from slipwright.schemas.profile import load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

db, repo, wt, prof = sys.argv[1:5]
seed = load_profile(Path(prof))
engine = Engine(
    JobStore(db), Workspace(Path(wt), PortAllocator(start=8300, end=8399)),
    seed_profile=seed, provider=canned(seed), supervisor_mode="manual",
)
job = engine.start(engine.create_job("survive a restart", Path(repo)).id)
print(job.id, job.state.value, flush=True)
time.sleep(120)  # parent kills us here
"""


def test_job_survives_process_death(
    tmp_path: Path, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    db = tmp_path / "jobs.sqlite3"
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(db), str(repo), str(worktrees_root), str(EXAMPLE)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
    )
    try:
        assert child.stdout is not None
        line = child.stdout.readline().strip()
        assert line, child.stderr.read() if child.stderr else ""
        job_id, state = line.split()
        assert state == "awaiting_backlog_approval"
    finally:
        child.kill()
        child.wait(timeout=30)

    with JobStore(db) as store:
        provider = canned(seed)
        engine = _engine(store, worktrees_root, seed, provider)
        resumed = engine.resume_all()

        assert [j.id for j in resumed] == [job_id]
        job = resumed[0]
        assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
        assert job.data.backlog is not None
        assert job.worktree_path is not None and job.worktree_path.is_dir()
        assert provider.requests == []  # resuming an approval state invokes nobody
        assert job.port in engine.workspace.ports.reserved

        job = engine.approve(job.id)
        assert job.state is JobState.ARCHITECTURE
