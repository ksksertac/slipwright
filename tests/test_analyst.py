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
from slipwright.roles.analyst import accepted_profile
from slipwright.roles.results import AnalystResult
from slipwright.schemas.job import JobState
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
    store: JobStore, worktrees_root: Path, seed: Profile, provider: ScriptedProvider
) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8300, end=8399))
    engine = Engine(store, ws, seed_profile=seed, provider=provider)
    engine.handlers.pop(JobState.PLANNING, None)  # stop right after profile approval
    return engine


def test_analyst_sees_worktree_and_job_stops_at_approval(
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

    assert job.state is JobState.AWAITING_PROFILE_APPROVAL
    assert job.worktree_path is not None and job.worktree_path.is_dir()
    assert job.port is not None
    assert job.profile == seed
    (request,) = provider.requests
    assert request.role is RoleName.ANALYST
    assert request.model == seed.roles[RoleName.ANALYST].model
    assert "pyproject.toml" in request.prompt
    assert "[project]" in request.prompt
    assert "add a /health endpoint" in request.prompt
    assert [t.to_state for t in job.history] == [
        JobState.ANALYZING,
        JobState.AWAITING_PROFILE_APPROVAL,
    ]
    # the proposed profile is on the record
    assert job.history[-1].detail is not None
    assert json.loads(job.history[-1].detail)["language"] == "python"


def test_analyst_roles_always_come_from_seed(seed: Profile) -> None:
    data = seed.model_dump(mode="json")
    data["language"] = "typescript"
    data["roles"]["developer"]["model"] = "model-the-analyst-picked"
    result = AnalystResult(summary="ts", profile=Profile.model_validate(data))

    profile = accepted_profile(result, seed)

    assert profile.language == "typescript"
    assert profile.roles == seed.roles


def test_approve_leaves_gate_and_reject_reruns_with_feedback(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = canned(seed)
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)

    job = engine.reject(job.id, "wrong package manager, we use poetry")

    assert job.state is JobState.AWAITING_PROFILE_APPROVAL
    assert len(provider.requests) == 2
    assert "wrong package manager, we use poetry" in provider.requests[1].prompt
    assert "previous_profile" in provider.requests[1].prompt
    assert [t.to_state for t in job.history] == [
        JobState.ANALYZING,
        JobState.AWAITING_PROFILE_APPROVAL,
        JobState.ANALYZING,
        JobState.AWAITING_PROFILE_APPROVAL,
    ]
    assert "rejected: wrong package manager" in (job.history[2].note or "")

    job = engine.approve(job.id)
    assert job.state is JobState.PLANNING
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


def test_analyst_failure_moves_job_to_failed(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    def boom(_: object) -> str:
        raise ProviderTimeoutError("model went away")

    engine = _engine(store, worktrees_root, seed, ScriptedProvider({RoleName.ANALYST: boom}))
    job = engine.start(engine.create_job("x", repo).id)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "analyst failed: timeout"
    assert "model went away" in (job.history[-1].detail or "")


def test_malformed_profile_from_analyst_fails_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = ScriptedProvider(
        {RoleName.ANALYST: {"summary": "x", "profile": {"language": "python"}}}
    )
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("x", repo).id)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "analyst failed: malformed_output"


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
    seed_profile=seed, provider=canned(seed),
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
        assert state == "awaiting_profile_approval"
    finally:
        child.kill()
        child.wait(timeout=30)

    with JobStore(db) as store:
        provider = canned(seed)
        engine = _engine(store, worktrees_root, seed, provider)
        resumed = engine.resume_all()

        assert [j.id for j in resumed] == [job_id]
        job = resumed[0]
        assert job.state is JobState.AWAITING_PROFILE_APPROVAL
        assert job.profile == seed
        assert job.worktree_path is not None and job.worktree_path.is_dir()
        assert provider.requests == []  # resuming an approval state invokes nobody
        assert job.port in engine.workspace.ports.reserved

        job = engine.approve(job.id)
        assert job.state is JobState.PLANNING
