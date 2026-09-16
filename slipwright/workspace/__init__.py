"""Per-job isolation: worktree, port and live environment."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from slipwright.schemas.job import Job
from slipwright.workspace import live, worktree
from slipwright.workspace.git import GitError
from slipwright.workspace.live import LiveEnvError
from slipwright.workspace.ports import NoFreePort, PortAllocator
from slipwright.workspace.worktree import WorktreeError

__all__ = [
    "GitError",
    "LiveEnvError",
    "NoFreePort",
    "PortAllocator",
    "Workspace",
    "WorktreeError",
]


class Workspace:
    """Owns the on-disk and network resources of jobs under one ``worktrees_root``.

    Methods mutate the passed ``Job`` in place and return it; persisting the change is
    the caller's responsibility so that the store stays the single source of truth.
    """

    def __init__(
        self,
        worktrees_root: Path,
        ports: PortAllocator | None = None,
        logs_root: Path | None = None,
    ) -> None:
        self.worktrees_root = worktrees_root
        self.ports = ports or PortAllocator()
        # job ids are hex, so a dotted directory can never collide with a worktree
        self.logs_root = logs_root or worktrees_root / ".logs"

    def reserve_ports(self, jobs: Iterable[Job]) -> None:
        """Seed the allocator with ports already held by persisted jobs (after a restart)."""
        self.ports.reserve(j.port for j in jobs if j.port is not None)

    def create(self, job: Job) -> Job:
        port = self.ports.allocate()
        try:
            job.worktree_path = worktree.create(job, self.worktrees_root)
        except WorktreeError:
            self.ports.release(port)
            raise
        job.port = port
        return job

    def destroy(self, job: Job) -> Job:
        self.down(job)
        worktree.destroy(job, self.worktrees_root)
        job.worktree_path = None
        self.ports.release(job.port)
        job.port = None
        return job

    # -- live environment ----------------------------------------------------------------

    def up(self, job: Job, health_timeout: float = 30.0) -> int:
        """Run the profile's run_cmd in the worktree on the job's port; return its PID."""
        return live.up(job, self.logs_root, health_timeout=health_timeout)

    def down(self, job: Job) -> None:
        live.down(job, self.logs_root)

    def is_running(self, job: Job) -> bool:
        return live.is_running(job, self.logs_root)

    def log_path(self, job: Job) -> Path:
        return live.log_path(self.logs_root, job)
