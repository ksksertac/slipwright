"""What one account may consume of a shared server.

On a machine of your own there is nothing to ration: the only person who can start
twenty developments at once is you, and you will stop. On a server people sign up to,
twenty is what one enthusiastic afternoon looks like, and nothing in the code stopped it
-- every job took a thread, a worktree and a container, and the machine simply went
down.

Model tokens are deliberately *not* rationed here. Everybody brings their own key, so
what they spend is between them and their vendor. What is rationed is what belongs to
the server: how many jobs run at once, how much disk their checkouts take, and how many
projects one account can accumulate.

Limits are read from settings, so an installation can raise them without a deploy, and a
single-team installation can turn them off entirely by setting them to zero.
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from slipwright.schemas.job import TERMINAL_STATES, Job
from slipwright.store import JobStore

log = logging.getLogger(__name__)

#: Off, unless an installation says otherwise.
#:
#: Tempting to ship real numbers here, and wrong: the same code runs on one person's
#: laptop, where the only one who can start twenty developments is them, and upgrading
#: must not quietly start refusing work that used to be allowed. A hosted installation
#: sets them on purpose -- ``SUGGESTED`` is what it probably wants -- and
#: ``warn_if_unprotected`` says so at startup if it has not.
DEFAULTS = {
    "max_running_jobs": 0,
    "max_projects": 0,
    "max_disk_mb": 0,
}

#: Generous enough that nobody doing ordinary work meets them, small enough that one
#: account cannot take the machine. What ``compose.yaml`` sets for the hosted profile.
SUGGESTED = {
    "max_running_jobs": 3,
    "max_projects": 20,
    "max_disk_mb": 5_000,
}

#: The one setting name they all live under, so an installation changes them in one place.
SETTING = "quota"


class QuotaExceeded(RuntimeError):
    """Refused for want of room, not for want of permission. Always says which limit."""

    def __init__(self, what: str, limit: int, used: int) -> None:
        super().__init__(f"{what}: {used} of {limit} already in use")
        self.what = what
        self.limit = limit
        self.used = used


@dataclass(frozen=True)
class Quota:
    """The limits in force. ``0`` means no limit, which is what a local install wants."""

    max_running_jobs: int = DEFAULTS["max_running_jobs"]
    max_projects: int = DEFAULTS["max_projects"]
    max_disk_mb: int = DEFAULTS["max_disk_mb"]

    @classmethod
    def unlimited(cls) -> Quota:
        return cls(max_running_jobs=0, max_projects=0, max_disk_mb=0)

    @classmethod
    def suggested(cls) -> Quota:
        return cls(**SUGGESTED)

    @property
    def unprotected(self) -> bool:
        return not (self.max_running_jobs or self.max_projects or self.max_disk_mb)


@dataclass(frozen=True)
class Usage:
    """What one account is using right now."""

    running_jobs: int
    projects: int
    disk_mb: int


def running(jobs: list[Job]) -> int:
    return sum(1 for j in jobs if j.state not in TERMINAL_STATES)


def disk_mb(paths: list[Path]) -> int:
    """How much the account's checkouts take, in whole megabytes.

    Walks the tree rather than asking the filesystem, because there is no portable way to
    ask; it is called when a job starts, not in a loop.
    """
    total = 0
    for root in paths:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except OSError:  # a file that went away mid-walk is not an error
                continue
    return total // (1024 * 1024)


def from_environment(env: Mapping[str, str] | None = None) -> dict[str, int]:
    """``SLIPWRIGHT_QUOTA_MAX_PROJECTS`` and friends, for a server that sets its limits
    in the file it is deployed from rather than by hand afterwards."""
    source = os.environ if env is None else env
    found: dict[str, int] = {}
    for name in DEFAULTS:
        raw = source.get(f"SLIPWRIGHT_QUOTA_{name.upper()}")
        if raw and raw.strip().isdigit():
            found[name] = int(raw)
    return found


class Quotas:
    """Reads the limits, measures the use, and refuses what will not fit."""

    def __init__(self, store: JobStore, worktrees_root: Path, repos_root: Path) -> None:
        self.store = store
        self.worktrees_root = worktrees_root
        self.repos_root = repos_root

    def limits(self) -> Quota:
        """What is in force: the stored settings, else the environment, else off.

        The environment comes second so that a server can declare its limits in its
        compose file -- deployed configuration, versioned with everything else -- while
        an administrator can still raise one from the page without a redeploy.
        """
        data: dict[str, int] = self.store.get_setting(SETTING, {}) or {}
        fallback = from_environment()
        return Quota(
            **{
                name: int(data.get(name, fallback.get(name, default)))
                for name, default in DEFAULTS.items()
            }
        )

    def update(self, **changes: int) -> Quota:
        data: dict[str, int] = self.store.get_setting(SETTING, {}) or {}
        for key, value in changes.items():
            if key in DEFAULTS and value is not None:
                data[key] = max(0, int(value))
        self.store.set_setting(SETTING, data)
        return self.limits()

    def usage(self, owner_id: str | None) -> Usage:
        jobs = self.store.list(owner_id=owner_id)
        projects = self.store.list_projects(owner_id)
        paths = [self.worktrees_root / j.id for j in jobs]
        paths += [self.repos_root / p.id for p in projects]
        return Usage(
            running_jobs=running(jobs),
            projects=len([p for p in projects if not p.is_demo]),
            disk_mb=disk_mb(paths),
        )

    # -- the two places something is refused ------------------------------------------------

    def check_new_project(self, owner_id: str | None) -> None:
        limits = self.limits()
        if not limits.max_projects:
            return
        used = self.usage(owner_id).projects
        if used >= limits.max_projects:
            raise QuotaExceeded("projects", limits.max_projects, used)

    def check_new_job(self, owner_id: str | None) -> None:
        """Called where a development is about to start running, not where it is created.

        Queuing would be kinder than refusing, and is the obvious next step; refusing is
        what makes the machine survive until then, and it says exactly what is in the way.
        """
        limits = self.limits()
        use = self.usage(owner_id)
        if limits.max_running_jobs and use.running_jobs >= limits.max_running_jobs:
            raise QuotaExceeded("running developments", limits.max_running_jobs, use.running_jobs)
        if limits.max_disk_mb and use.disk_mb >= limits.max_disk_mb:
            raise QuotaExceeded("disk (MB)", limits.max_disk_mb, use.disk_mb)


def warn_if_unprotected(quota: Quota, *, open_to_strangers: bool) -> str | None:
    """Say so, loudly, when a server anybody can sign up to has no limits.

    Returned rather than raised: refusing to start would be worse than the risk, and an
    installation that means it can ignore the line in its log.
    """
    if not open_to_strangers or not quota.unprotected:
        return None
    return (
        "this installation accepts signups but has no quotas: one account can start any "
        "number of developments and fill the disk. Set them under Settings, or with "
        "SLIPWRIGHT_QUOTA_* -- suggested: "
        + ", ".join(f"{k}={v}" for k, v in SUGGESTED.items())
    )


def forget_everything(store: JobStore, owner_id: str, *, worktrees: Path, repos: Path) -> None:
    """Delete an account's work: its jobs, projects, checkouts, settings and pages.

    Closing an account has to actually remove what it left behind -- somebody asking to
    be forgotten is owed that, and a server that only marks accounts inactive fills up
    with the work of people who have gone.
    """
    for project in store.list_projects(owner_id):
        for job in store.list(project_id=project.id):
            shutil.rmtree(worktrees / job.id, ignore_errors=True)
            with _quiet():
                store.delete_job(job.id, owner_id)
        shutil.rmtree(repos / project.id, ignore_errors=True)
        with _quiet():
            store.delete_project(project.id, owner_id)
    store.forget_settings(owner_id)
    store.forget_pages(owner_id)


class _quiet:
    """A job still running, or already gone, must not stop the rest being removed."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: object, value: object, tb: object) -> bool:
        if value is not None:
            log.warning("could not delete during account removal: %s", value)
        return True


__all__ = [
    "DEFAULTS",
    "SUGGESTED",
    "SETTING",
    "Quota",
    "QuotaExceeded",
    "Quotas",
    "Usage",
    "disk_mb",
    "from_environment",
    "forget_everything",
    "running",
    "warn_if_unprotected",
]
