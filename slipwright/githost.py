"""Git hosting: push a branch, open a pull request, read CI status.

The engine only talks to the ``GitHost`` protocol. ``GhHost`` implements it with the
``gh`` CLI (GitHub); tests use an in-memory fake.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from slipwright.workspace import git as g


class CiState(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    NONE = "none"  # the repository runs no checks


@dataclass(frozen=True)
class CiStatus:
    state: CiState
    log: str | None = None
    summary: str = ""

    @property
    def terminal(self) -> bool:
        return self.state in (CiState.SUCCESS, CiState.FAILURE, CiState.NONE)


class GitHostError(RuntimeError):
    pass


class GitHost(Protocol):
    def push(self, worktree: Path, branch: str) -> None: ...

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str: ...

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus: ...


class GhHost:
    """GitHub through ``gh``; every call runs inside the job's worktree.

    ``token`` (a value or a callable returning the current one) is passed to ``gh`` and
    ``git`` as ``GH_TOKEN``; without it the user's own ``gh auth`` login applies.
    """

    def __init__(
        self,
        remote: str = "origin",
        gh: str = "gh",
        token: str | Callable[[], str | None] | None = None,
    ) -> None:
        self.remote = remote
        self.gh = gh
        self._token = token

    def token(self) -> str | None:
        return self._token() if callable(self._token) else self._token

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        token = self.token()
        if token:
            env["GH_TOKEN"] = token
            env["GITHUB_TOKEN"] = token
        return env

    def push(self, worktree: Path, branch: str) -> None:
        try:
            g.run(
                worktree, "push", "--force-with-lease", "-u", self.remote, branch, env=self._env()
            )
        except g.GitError as exc:
            raise GitHostError(f"push failed: {exc.stderr}") from exc

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        existing = self._gh(worktree, "pr", "view", branch, "--json", "url", check=False)
        if existing.returncode == 0:
            url: str = json.loads(existing.stdout)["url"]
            return url
        created = self._gh(
            worktree, "pr", "create", "--head", branch, "--title", title, "--body", body
        )
        return created.stdout.strip().splitlines()[-1]

    def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
        view = self._gh(worktree, "pr", "view", pr_url, "--json", "statusCheckRollup")
        checks: list[dict[str, Any]] = json.loads(view.stdout).get("statusCheckRollup") or []
        if not checks:
            return CiStatus(CiState.NONE, summary="no checks reported")
        states = [_check_state(c) for c in checks]
        summary = ", ".join(
            f"{c.get('name') or c.get('context')}: {s}" for c, s in zip(checks, states, strict=True)
        )
        if any(s is CiState.FAILURE for s in states):
            return CiStatus(
                CiState.FAILURE, log=self._failed_log(worktree, branch), summary=summary
            )
        if any(s is CiState.PENDING for s in states):
            return CiStatus(CiState.PENDING, summary=summary)
        return CiStatus(CiState.SUCCESS, summary=summary)

    def _failed_log(self, worktree: Path, branch: str) -> str:
        runs = self._gh(
            worktree,
            "run",
            "list",
            "--branch",
            branch,
            "--limit",
            "5",
            "--json",
            "databaseId,conclusion,name",
            check=False,
        )
        if runs.returncode != 0:
            return runs.stderr.strip() or "could not list workflow runs"
        for run in json.loads(runs.stdout or "[]"):
            if run.get("conclusion") == "failure":
                log = self._gh(
                    worktree, "run", "view", str(run["databaseId"]), "--log-failed", check=False
                )
                if log.stdout.strip():
                    return log.stdout[-20_000:]
        return "CI reported failure but no failed-step log was available"

    def _gh(self, cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [self.gh, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._env(),
        )
        if check and proc.returncode != 0:
            raise GitHostError(
                f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        return proc


def _check_state(check: dict[str, Any]) -> CiState:
    # CheckRun: status (COMPLETED/...) + conclusion; StatusContext: state
    conclusion = (check.get("conclusion") or check.get("state") or "").upper()
    status = (check.get("status") or "").upper()
    if status and status != "COMPLETED":
        return CiState.PENDING
    if conclusion in ("SUCCESS", "NEUTRAL", "SKIPPED"):
        return CiState.SUCCESS
    if conclusion in ("", "PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS"):
        return CiState.PENDING
    return CiState.FAILURE


__all__ = ["CiState", "CiStatus", "GhHost", "GitHost", "GitHostError"]
