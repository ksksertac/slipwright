"""Per-job isolation: worktree, port and live environment."""

from __future__ import annotations

from pathlib import Path

from slipwright.schemas.job import Job
from slipwright.workspace import worktree
from slipwright.workspace.git import GitError
from slipwright.workspace.worktree import WorktreeError

__all__ = ["GitError", "Workspace", "WorktreeError"]


class Workspace:
    """Owns the on-disk resources of jobs under one ``worktrees_root``.

    Methods mutate the passed ``Job`` in place and return it; persisting the change is
    the caller's responsibility so that the store stays the single source of truth.
    """

    def __init__(self, worktrees_root: Path) -> None:
        self.worktrees_root = worktrees_root

    def create(self, job: Job) -> Job:
        job.worktree_path = worktree.create(job, self.worktrees_root)
        return job

    def destroy(self, job: Job) -> Job:
        worktree.destroy(job, self.worktrees_root)
        job.worktree_path = None
        return job
