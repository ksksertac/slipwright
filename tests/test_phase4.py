from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine, NotAwaitingApproval
from slipwright.githost import CiState, CiStatus
from slipwright.providers import ModelRequest
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.roles.devops import draft_description
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName, load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace
from tests.pipeline import set_plan

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"
PY = sys.executable
CHECK = f"\"{PY}\" -c \"import sys; sys.exit(0 if open('OK').read().strip() == 'yes' else 1)\""
TRUE = f'"{PY}" -c "print(\'built\')"'

CASES = [{"name": "smoke", "description": "OK says yes"}]


class FakeHost:
    def __init__(self, statuses: list[CiStatus] | None = None) -> None:
        self.statuses = list(statuses or [CiStatus(CiState.SUCCESS, summary="ci: success")])
        self.pushes: list[str] = []
        self.prs: list[tuple[str, str, str]] = []
        self.polls = 0

    def push(self, worktree: Path, branch: str) -> None:
        self.pushes.append(branch)

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        self.prs.append((branch, title, body))
        return f"https://example.test/pr/{len(self.prs)}"

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        self.polls += 1
        if len(self.statuses) > 1:
            return self.statuses.pop(0)
        return self.statuses[0]


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE).model_copy(update={"build_cmd": TRUE, "test_cmd": CHECK})


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


def _qa_reply(stage_two: Callable[[ModelRequest], list[dict[str, Any]]]) -> Any:
    def reply(req: ModelRequest) -> dict[str, Any]:
        if '"stage": 1' in req.prompt:
            return {"summary": "proposed", "test_cases": CASES}
        return {"summary": "written", "changes": stage_two(req)}

    return reply


def _write_tests(_: ModelRequest) -> list[dict[str, Any]]:
    return [{"path": "tests/test_ok.txt", "content": "check OK\n"}]


def _provider(seed: Profile, qa: Any = None) -> ScriptedProvider:
    p = canned(seed)
    set_plan(p, seed, [{"goal": "write OK", "files": ["OK"]}])
    p.replies[RoleName.DEVELOPER] = lambda req: {
        "summary": "fixed" if '"ci_failure":' in req.prompt else "wrote OK",
        "phase_complete": True,
        "changes": [{"path": "OK", "content": "yes\n"}],
    }
    p.replies[RoleName.QA] = qa or _qa_reply(_write_tests)
    return p


def _engine(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    provider: ScriptedProvider,
    host: FakeHost | None = None,
) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8600, end=8699))
    return Engine(
        store,
        ws,
        seed_profile=seed,
        provider=provider,
        git_host=host or FakeHost(),
        ci_poll_s=0.0,
        ci_timeout_s=1.0,
        review="off",  # the standards review has its own tests (T9.5)
        supervisor_mode="manual",
    )


def _to_test_gate(engine: Engine, repo: Path) -> Job:
    job = engine.start(engine.create_job("make OK say yes", repo).id)
    job = engine.approve(job.id)  # profile
    job = engine.approve(job.id)  # plan -> develop -> gate -> qa stage 1
    assert job.state is JobState.AWAITING_TEST_APPROVAL, job.history[-1]
    return job


def _requests(provider: ScriptedProvider, role: RoleName) -> list[ModelRequest]:
    return [r for r in provider.requests if r.role is role]


# --- T4.1 QA ------------------------------------------------------------------------------


def test_stage_one_proposes_cases_and_stops(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed)
    engine = _engine(store, worktrees_root, seed, provider)

    job = _to_test_gate(engine, repo)

    assert job.data.qa_stage == 1
    assert job.data.test_cases == CASES
    (req,) = _requests(provider, RoleName.QA)
    assert req.model == seed.roles[RoleName.QA].model
    assert '"stage": 1' in req.prompt
    assert "+yes" in req.prompt  # the branch diff is in context
    assert "1 test cases proposed" in (job.history[-1].note or "")


def test_human_edits_are_persisted_and_used_in_stage_two(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed)
    engine = _engine(store, worktrees_root, seed, provider)
    job = _to_test_gate(engine, repo)

    edited = [
        {"name": "smoke", "description": "OK says yes"},
        {"name": "negative", "description": "OK never says no"},
        {"name": "", "description": "dropped"},
    ]
    job = engine.set_test_cases(job.id, edited)
    assert [c["name"] for c in store.get(job.id).data.test_cases] == ["smoke", "negative"]

    job = engine.approve(job.id)  # approve the list -> stage two

    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert job.data.qa_stage == 2
    stage_two = _requests(provider, RoleName.QA)[1]
    assert '"stage": 2' in stage_two.prompt
    assert "OK never says no" in stage_two.prompt
    assert "tests written and green" in (job.history[-1].note or "")
    assert "tests/test_ok.txt" in (job.history[-1].detail or "")
    assert job.worktree_path is not None
    assert (job.worktree_path / "tests" / "test_ok.txt").read_text(encoding="utf-8") == "check OK\n"
    log = subprocess.run(
        ["git", "-C", str(job.worktree_path), "log", "--format=%s", "-1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert log == "slipwright: tests"

    with pytest.raises(NotAwaitingApproval):  # edits only while the list awaits approval
        engine.set_test_cases(job.id, edited)


def test_stage_two_tests_go_through_the_build_gate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    def breaks_then_fixes(req: ModelRequest) -> list[dict[str, Any]]:
        if '"build_failure":' in req.prompt:
            return [{"path": "OK", "content": "yes\n"}, *_write_tests(req)]
        return [{"path": "OK", "content": "no\n"}]  # a test change that breaks the build

    provider = _provider(seed, _qa_reply(breaks_then_fixes))
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.approve(_to_test_gate(engine, repo).id)

    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert job.data.qa_stage == 2
    qa_reqs = _requests(provider, RoleName.QA)
    assert len(qa_reqs) == 3  # propose, write (red), write again (green)
    assert "[test: exit 1]" in qa_reqs[2].prompt
    assert job.data.build_attempts == 0


def test_stage_two_exhausts_gate_attempts(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed, _qa_reply(lambda _: [{"path": "OK", "content": "no\n"}]))
    engine = _engine(store, worktrees_root, seed, provider)
    job = engine.approve(_to_test_gate(engine, repo).id)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "qa tests failed the build gate 3 times"


def test_reject_reruns_the_current_stage_with_feedback(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed)
    engine = _engine(store, worktrees_root, seed, provider)
    job = _to_test_gate(engine, repo)

    job = engine.reject(job.id, "cover the error path too")
    assert job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage == 1
    assert "cover the error path too" in _requests(provider, RoleName.QA)[1].prompt

    job = engine.approve(job.id)
    assert job.data.qa_stage == 2
    job = engine.reject(job.id, "tests are too shallow")
    assert job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage == 2
    last = _requests(provider, RoleName.QA)[-1]
    assert '"stage": 2' in last.prompt and "tests are too shallow" in last.prompt


def test_put_tests_endpoint(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed, _provider(seed))
    job = _to_test_gate(engine, repo)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        resp = client.put(
            f"/api/jobs/{job.id}/tests",
            json={"test_cases": [{"name": "only", "description": "one case"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["test_cases"] == [{"name": "only", "description": "one case"}]
        assert client.put("/api/jobs/nope/tests", json={"test_cases": []}).status_code == 404


# --- T4.2 DevOps --------------------------------------------------------------------------


def _to_devops(engine: Engine, repo: Path) -> Job:
    job = _to_test_gate(engine, repo)
    job = engine.approve(job.id)  # list approved -> tests written
    assert job.data.qa_stage == 2
    return engine.approve(job.id)  # ship it


def test_devops_opens_pr_and_finishes_on_green_ci(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed)
    host = FakeHost()
    engine = _engine(store, worktrees_root, seed, provider, host)

    job = _to_devops(engine, repo)

    assert job.state is JobState.DONE
    assert job.data.pr_url == "https://example.test/pr/1"
    assert host.pushes == [job.branch]
    (branch, title, body) = host.prs[0]
    assert branch == job.branch
    assert title == "Slipwright change" and body == "Automated change."
    assert job.history[-1].note == f"PR {job.data.pr_url} (success)"

    (req,) = _requests(provider, RoleName.DEVOPS)
    assert '"draft":' in req.prompt and "write OK" in req.prompt
    # the small model named in the example profile is what got called - no fallback
    assert req.model == seed.roles[RoleName.DEVOPS].model
    assert req.model != seed.roles[RoleName.DEVELOPER].model
    assert req.thinking_depth is seed.roles[RoleName.DEVOPS].thinking_depth


def test_draft_description_is_built_from_plan_and_history(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed, _provider(seed))
    job = _to_test_gate(engine, repo)
    draft = draft_description(job)
    assert "make OK say yes" in draft
    assert "1. write OK — `OK`" in draft
    assert "**smoke**: OK says yes" in draft
    assert "build gate passed for phase 1/1" in draft


def test_red_ci_is_fed_back_for_a_fix(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed)
    host = FakeHost(
        [
            CiStatus(CiState.PENDING, summary="running"),
            CiStatus(CiState.FAILURE, log="lint: trailing whitespace", summary="ci: failure"),
            CiStatus(CiState.SUCCESS, summary="ci: success"),
        ]
    )
    engine = _engine(store, worktrees_root, seed, provider, host)

    job = _to_devops(engine, repo)

    assert job.state is JobState.DONE
    assert job.data.ci_attempts == 1
    assert host.pushes == [job.branch, job.branch]
    assert len(host.prs) == 1
    fixes = [r for r in _requests(provider, RoleName.DEVELOPER) if '"ci_failure":' in r.prompt]
    assert len(fixes) == 1
    assert "lint: trailing whitespace" in fixes[0].prompt


def test_red_ci_bounded_to_three_fix_attempts(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider(seed)
    host = FakeHost([CiStatus(CiState.FAILURE, log="still red", summary="ci: failure")])
    engine = _engine(store, worktrees_root, seed, provider, host)

    job = _to_devops(engine, repo)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "CI red after 3 fix attempts"
    assert job.history[-1].detail == "still red"
    fixes = [r for r in _requests(provider, RoleName.DEVELOPER) if '"ci_failure":' in r.prompt]
    assert len(fixes) == 3
    assert host.pushes == [job.branch] * 4


def test_repo_without_checks_is_done(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    host = FakeHost([CiStatus(CiState.NONE, summary="no checks reported")])
    engine = _engine(store, worktrees_root, seed, _provider(seed), host)
    job = _to_devops(engine, repo)
    assert job.state is JobState.DONE


def test_ci_never_finishing_fails_the_job(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    host = FakeHost([CiStatus(CiState.PENDING, summary="running")])
    engine = _engine(store, worktrees_root, seed, _provider(seed), host)
    engine.ci_timeout_s = 0.2
    job = _to_devops(engine, repo)
    assert job.state is JobState.FAILED
    assert "CI still pending" in (job.history[-1].note or "")


def test_restart_during_devops_does_not_open_a_second_pr(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    class DiesOnFirstPoll(FakeHost):
        def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
            if self.polls == 0:  # the process dies right after the PR was opened
                self.polls += 1
                raise SystemExit  # not an Exception: bypasses the crash-to-failed path
            return super().ci_status(worktree, branch, pr_url)

    provider = _provider(seed)
    host = DiesOnFirstPoll()
    engine_a = _engine(store, worktrees_root, seed, provider, host)
    with pytest.raises(SystemExit):
        _to_devops(engine_a, repo)

    job_id = store.list()[0].id
    persisted = store.get(job_id)
    assert persisted.state is JobState.DEVOPS
    assert persisted.data.pr_url == "https://example.test/pr/1"

    engine_b = _engine(store, worktrees_root, seed, provider, host)
    job = engine_b.resume(job_id)

    assert job.state is JobState.DONE
    assert len(host.prs) == 1
    assert len(_requests(provider, RoleName.DEVOPS)) == 1


def test_devops_without_push_permission_fails(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    data = seed.model_dump(mode="json")
    data["roles"]["devops"]["permissions"] = ["read_files"]
    seed = Profile.model_validate(data)
    host = FakeHost()
    engine = _engine(store, worktrees_root, seed, _provider(seed), host)
    job = _to_devops(engine, repo)
    assert job.state is JobState.FAILED
    assert host.pushes == []
