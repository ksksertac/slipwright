"""T16.1: every step that changes the code is on the project's repository as it is made.

Everything was committed step by step and pushed only when DevOps opened the pull request
at the very end: ten phases, fourteen hours, and the repository had none of it."""

from __future__ import annotations

import subprocess
from pathlib import Path

from slipwright.githost import CiState, CiStatus, GitHostError
from slipwright.roles.specialists import DEVELOPER_ROLES
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import git as g
from tests.pipeline import full_engine, full_provider


class Host:
    """A host that keeps what it was asked, and can refuse a push."""

    def __init__(self, *, refuse: int = 0, drafts: bool = True) -> None:
        self.pushed: list[str] = []  # the branch head at every push
        self.calls: list[str] = []
        self.refuse = refuse
        if not drafts:
            self.open_draft = None  # type: ignore[assignment]
            self.finish_pr = None  # type: ignore[assignment]

    def push(self, worktree: Path, branch: str) -> None:
        if self.refuse:
            self.refuse -= 1
            raise GitHostError("the host said no")
        self.pushed.append(g.head_commit(worktree))
        self.calls.append("push")

    def open_draft(self, worktree: Path, branch: str, title: str, body: str) -> str:
        self.calls.append(f"draft:{title}")
        return "https://example.test/pr/7"

    def finish_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        self.calls.append(f"finish:{title}")
        return "https://example.test/pr/7"

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        self.calls.append(f"open:{title}")
        return "https://example.test/pr/8"

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        return CiStatus(CiState.SUCCESS, summary="ci: success")


def _with_remote(repo: Path, tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    g.run(repo, "remote", "add", "origin", str(remote))
    return repo


def _drive(engine, job: Job) -> Job:  # type: ignore[no-untyped-def]
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            return job
        job = engine.approve(job.id)
    return job


def test_every_phase_is_pushed_and_the_pull_request_is_a_draft_from_the_first(
    store: JobStore, repo: Path, tmp_path: Path, worktrees_root: Path, seed: Profile
) -> None:
    host = Host()
    provider = full_provider(seed, phases=3)
    written = iter(range(100))
    for role in DEVELOPER_ROLES:  # each phase writes something of its own
        provider.replies[role] = lambda _req: {
            "summary": "wrote OK",
            "changes": [{"path": "OK", "content": f"yes {next(written)}\n"}],
        }
    engine = full_engine(store, worktrees_root, seed, provider, git_host=host)
    job = engine.start(engine.create_job("add a health page", _with_remote(repo, tmp_path)).id)
    job = _drive(engine, engine.approve(engine.approve(job.id).id))

    assert job.state is JobState.DONE
    # a push per phase, one for the tests, then DevOps' own before it finishes the PR
    assert host.calls[:2] == ["push", "draft:add a health page"]
    assert len(set(host.pushed)) == 4  # three phases and the tests, each a commit of its own
    finished = [c for c in host.calls if c.startswith(("finish:", "open:"))]
    assert len(finished) == 1 and finished[0].startswith("finish:")  # the draft, not a 2nd PR
    assert job.data.pr_url == job.data.draft_pr_url == "https://example.test/pr/7"


def test_a_refused_push_is_noted_and_the_next_one_carries_it(
    store: JobStore, repo: Path, tmp_path: Path, worktrees_root: Path, seed: Profile
) -> None:
    host = Host(refuse=1)
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=2), git_host=host)
    job = engine.start(engine.create_job("x", _with_remote(repo, tmp_path)).id)
    job = _drive(engine, engine.approve(engine.approve(job.id).id))

    assert job.state is JobState.DONE  # a push that failed stopped nothing
    notes = [t.note or "" for t in job.history]
    assert any(n == "phase 1/2: committed, not pushed" for n in notes)
    assert host.pushed  # and a later push carried phase 1 with it


def test_a_checkout_with_nowhere_to_push_says_nothing(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    host = Host()
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=2), git_host=host)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(engine.approve(job.id).id)

    assert host.calls == []
    assert not any("not pushed" in (t.note or "") for t in job.history)


def test_a_host_without_drafts_gets_its_pull_request_at_the_end_as_before(
    store: JobStore, repo: Path, tmp_path: Path, worktrees_root: Path, seed: Profile
) -> None:
    host = Host(drafts=False)
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=2), git_host=host)
    job = engine.start(engine.create_job("x", _with_remote(repo, tmp_path)).id)
    job = _drive(engine, engine.approve(engine.approve(job.id).id))

    assert job.state is JobState.DONE
    assert job.data.draft_pr_url is None
    assert [c for c in host.calls if not c.startswith("push")] == [
        "open:" + c[5:] for c in host.calls if c.startswith("open:")
    ]
    assert job.data.pr_url == "https://example.test/pr/8"


def test_a_phase_commit_names_its_task_and_its_jira_key(
    store: JobStore, repo: Path, tmp_path: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(
        store, worktrees_root, seed, full_provider(seed, phases=1), git_host=Host()
    )
    job = engine.start(engine.create_job("x", _with_remote(repo, tmp_path)).id)
    job = engine.approve(job.id, run=False)
    job = store.get(job.id)
    job.data.jira_keys = {"t1": "SCRUM-7"}
    store.save(job)
    job = engine.approve(engine._run(job).id)  # noqa: SLF001
    worktree = store.get(job.id).worktree_path
    assert worktree is not None
    subjects = g.run(worktree, "log", "--format=%s").stdout.splitlines()
    assert any(
        s.startswith("slipwright: phase 1/1: ") and s.endswith("[SCRUM-7]") for s in subjects
    )
