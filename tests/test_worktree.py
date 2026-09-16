import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from slipwright.schemas.job import Job
from slipwright.workspace import Workspace, WorktreeError
from slipwright.workspace import git as g


def _job(repo: Path, request: str = "do a thing") -> Job:
    return Job(request=request, repo_path=repo)


def _branches(repo: Path) -> set[str]:
    out = g.run(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
    return set(out.split())


def test_create_makes_worktree_on_job_branch(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root)
    job = ws.create(_job(repo))

    assert job.worktree_path == worktrees_root / job.id
    assert job.worktree_path.is_dir()
    assert (job.worktree_path / "README.md").exists()
    assert g.run(job.worktree_path, "branch", "--show-current").stdout.strip() == job.branch
    assert job.branch in _branches(repo)
    assert job.worktree_path.resolve() in {p.resolve() for p in g.worktree_paths(repo)}
    # branch starts at the repo's HEAD
    assert g.head_commit(job.worktree_path) == g.head_commit(repo)


def test_destroy_removes_worktree_and_branch(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root)
    job = ws.create(_job(repo))
    path = job.worktree_path
    assert path is not None
    (path / "scratch.txt").write_text("uncommitted", encoding="utf-8")  # must not block removal

    ws.destroy(job)

    assert job.worktree_path is None
    assert not path.exists()
    assert job.branch not in _branches(repo)
    assert path.resolve() not in {p.resolve() for p in g.worktree_paths(repo)}
    # main checkout is untouched
    assert (repo / "README.md").exists()
    assert g.run(repo, "status", "--porcelain").stdout == ""


def test_destroy_is_idempotent(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root)
    job = ws.create(_job(repo))
    ws.destroy(job)
    ws.destroy(job)  # no error
    ws.destroy(_job(repo))  # never created: still no error


def test_two_jobs_are_isolated(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root)
    a = ws.create(_job(repo, "job a"))
    b = ws.create(_job(repo, "job b"))
    assert a.worktree_path is not None and b.worktree_path is not None
    assert a.worktree_path != b.worktree_path
    assert a.branch != b.branch

    (a.worktree_path / "only_a.txt").write_text("a", encoding="utf-8")
    (b.worktree_path / "only_b.txt").write_text("b", encoding="utf-8")
    g.run(a.worktree_path, "add", "only_a.txt")
    g.run(a.worktree_path, "-c", "user.email=a@x", "-c", "user.name=a", "commit", "-qm", "a")

    assert not (b.worktree_path / "only_a.txt").exists()
    assert not (a.worktree_path / "only_b.txt").exists()
    assert not (repo / "only_a.txt").exists()
    assert not (repo / "only_b.txt").exists()
    # a's commit is on a's branch only
    assert g.head_commit(a.worktree_path) != g.head_commit(repo)
    assert g.head_commit(b.worktree_path) == g.head_commit(repo)


def test_concurrent_creation_against_same_repo(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root)
    jobs = [_job(repo, f"job {i}") for i in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        created = list(pool.map(ws.create, jobs))

    paths = {j.worktree_path for j in created}
    assert len(paths) == len(jobs)
    assert all(p is not None and (p / "README.md").exists() for p in paths)
    assert {j.branch for j in created} <= _branches(repo)


def test_failure_leaves_no_partial_state_when_path_taken(repo: Path, worktrees_root: Path) -> None:
    ws = Workspace(worktrees_root)
    job = _job(repo)
    taken = worktrees_root / job.id
    taken.mkdir(parents=True)
    (taken / "keep.txt").write_text("mine", encoding="utf-8")
    branches_before = _branches(repo)

    with pytest.raises(WorktreeError, match="already exists"):
        ws.create(job)

    assert job.worktree_path is None
    assert (taken / "keep.txt").exists()  # we never delete what we did not create
    assert _branches(repo) == branches_before
    assert len(g.worktree_paths(repo)) == 1


def test_failure_leaves_no_partial_state_when_branch_taken(
    repo: Path, worktrees_root: Path
) -> None:
    ws = Workspace(worktrees_root)
    job = _job(repo)
    g.run(repo, "branch", job.branch)

    with pytest.raises(WorktreeError, match="branch already exists"):
        ws.create(job)

    assert job.branch in _branches(repo)  # pre-existing branch is preserved
    assert not (worktrees_root / job.id).exists()
    assert len(g.worktree_paths(repo)) == 1


def test_failure_from_git_itself_cleans_up(
    repo: Path, worktrees_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate git dying after the branch is created but before the checkout lands."""
    ws = Workspace(worktrees_root)
    job = _job(repo)
    real_run = g.run

    def flaky_run(r: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("worktree", "add"):
            # do the branch half of the work, then fail
            real_run(r, "branch", job.branch)
            (worktrees_root / job.id).mkdir(parents=True)
            raise g.GitError(list(args), 128, "fatal: simulated failure")
        return real_run(r, *args, check=check)

    monkeypatch.setattr(g, "run", flaky_run)
    with pytest.raises(WorktreeError, match="simulated failure"):
        ws.create(job)

    assert job.worktree_path is None
    assert job.branch not in _branches(repo)
    assert not (worktrees_root / job.id).exists()
    assert len(g.worktree_paths(repo)) == 1
