"""Per-job git worktrees.

Invariant 4: jobs never share a checkout. Each job gets ``<worktrees_root>/<job-id>``
on its own branch ``slipwright/<job-id>``. ``create`` is all-or-nothing: if git fails
midway, anything this call created is removed and anything that already existed is
left alone.
"""

from __future__ import annotations

import shutil
import threading
from collections import defaultdict
from pathlib import Path

from slipwright.schemas.job import Job
from slipwright.workspace import git


class WorktreeError(RuntimeError):
    pass


# git's own worktree bookkeeping is not safe against concurrent ``worktree add`` on the
# same repository (it reads sibling entries while they are half-written), so those calls
# are serialised per repository. Jobs still run in parallel; only the checkout is queued.
_repo_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


def _repo_lock(repo: Path) -> threading.Lock:
    return _repo_locks[str(repo.resolve())]


def worktree_path(worktrees_root: Path, job: Job) -> Path:
    return worktrees_root / job.id


def create(job: Job, worktrees_root: Path) -> Path:
    """Create the job's worktree and branch. Returns the worktree path.

    Does not touch the store; the caller records ``worktree_path`` on the job.
    """
    repo = job.repo_path
    path = worktree_path(worktrees_root, job)
    branch = job.branch

    if path.exists():
        raise WorktreeError(f"worktree path already exists: {path}")
    if git.branch_exists(repo, branch):
        raise WorktreeError(f"branch already exists: {branch}")

    worktrees_root.mkdir(parents=True, exist_ok=True)
    with _repo_lock(repo):
        try:
            git.run(repo, "worktree", "add", "-b", branch, str(path))
        except git.GitError as exc:
            _cleanup_partial(repo, path, branch)
            raise WorktreeError(
                f"could not create worktree for job {job.id}: {exc.stderr}"
            ) from exc
    return path


def destroy(job: Job, worktrees_root: Path) -> None:
    """Remove the job's worktree and delete its branch. Safe to call twice."""
    repo = job.repo_path
    path = job.worktree_path or worktree_path(worktrees_root, job)
    with _repo_lock(repo):
        _cleanup_partial(repo, path, job.branch)


def _cleanup_partial(repo: Path, path: Path, branch: str) -> None:
    # Ask git first so its bookkeeping in .git/worktrees is updated; fall back to
    # deleting the directory ourselves and pruning the stale registration.
    if path.exists():
        git.run(repo, "worktree", "remove", "--force", str(path), check=False)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    git.run(repo, "worktree", "prune", check=False)
    if git.branch_exists(repo, branch):
        git.run(repo, "branch", "-D", branch, check=False)
