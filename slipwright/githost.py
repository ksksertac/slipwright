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


class NoRemote(GitHostError):
    """The checkout has no remote to push to: a local folder the engine turned into a
    repository. The engine finishes the development on the branch instead."""


class GitHost(Protocol):
    def push(self, worktree: Path, branch: str) -> None: ...

    def remote_head(self, worktree: Path, branch: str) -> str | None:
        """The commit ``branch`` points at on the host, or None when it is not there.
        Asks; brings nothing into the checkout."""
        ...

    def fetch(self, worktree: Path, branch: str) -> str | None:
        """Bring ``branch`` from the host into ``refs/remotes/origin/<branch>`` and return
        the commit it points at, or None when the host has no such branch."""
        ...

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

    def _credentials(self) -> list[str]:
        """Answer GitHub's HTTPS prompt from ``GH_TOKEN`` for this one call. The helper
        lives in the command line, so a checkout the user also works in never has the
        token written into its remote URL or its config."""
        if not self.token():
            return []
        return [
            "-c",
            "credential.helper=",  # ignore whatever the machine has configured
            "-c",
            "credential.helper=!f() { echo username=x-access-token; "
            'echo "password=$GH_TOKEN"; }; f',
        ]

    def push(self, worktree: Path, branch: str) -> None:
        if not g.has_remote(worktree, self.remote):
            raise NoRemote(f"the checkout has no remote named {self.remote!r}")
        try:
            g.run(
                worktree,
                *self._credentials(),
                "push",
                "--force-with-lease",
                "-u",
                self.remote,
                branch,
                env=self._env(),
            )
        except g.GitError as exc:
            raise GitHostError(f"push failed: {exc.stderr}") from exc

    def remote_head(self, worktree: Path, branch: str) -> str | None:
        if not g.has_remote(worktree, self.remote):
            raise NoRemote(f"the checkout has no remote named {self.remote!r}")
        try:
            out = g.run(
                worktree,
                *self._credentials(),
                "ls-remote",
                "--heads",
                self.remote,
                f"refs/heads/{branch}",
                env=self._env(),
            ).stdout
        except g.GitError as exc:
            raise GitHostError(f"could not read the branch: {exc.stderr}") from exc
        return out.split()[0] if out.strip() else None

    def fetch(self, worktree: Path, branch: str) -> str | None:
        if self.remote_head(worktree, branch) is None:
            return None
        tracking = f"refs/remotes/{self.remote}/{branch}"
        try:
            g.run(
                worktree,
                *self._credentials(),
                "fetch",
                "-q",
                self.remote,
                f"+refs/heads/{branch}:{tracking}",
                env=self._env(),
            )
        except g.GitError as exc:
            raise GitHostError(f"pull failed: {exc.stderr}") from exc
        return g.run(worktree, "rev-parse", tracking).stdout.strip()

    def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        existing = self._gh(worktree, "pr", "view", branch, "--json", "url", check=False)
        if existing.returncode == 0:
            url: str = json.loads(existing.stdout)["url"]
            return url
        created = self._gh(
            worktree, "pr", "create", "--head", branch, "--title", title, "--body", body
        )
        return created.stdout.strip().splitlines()[-1]

    def open_draft(self, worktree: Path, branch: str, title: str, body: str) -> str:
        """The branch's pull request as a draft: opened at the first push so the work can
        be followed while it is built. One that is already open is returned as it is."""
        existing = self._gh(worktree, "pr", "view", branch, "--json", "url", check=False)
        if existing.returncode == 0:
            url: str = json.loads(existing.stdout)["url"]
            return url
        created = self._gh(
            worktree, "pr", "create", "--draft", "--head", branch, "--title", title, "--body", body
        )
        return created.stdout.strip().splitlines()[-1]

    def finish_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
        """DevOps' title and description on the draft, and it marked ready for review."""
        self._gh(worktree, "pr", "edit", branch, "--title", title, "--body", body)
        # already ready (a person pressed it on the host) is not a failure
        self._gh(worktree, "pr", "ready", branch, check=False)
        view = self._gh(worktree, "pr", "view", branch, "--json", "url")
        url: str = json.loads(view.stdout)["url"]
        return url

    # -- taking a deleted development back off the host ---------------------------------

    def push_onto(self, worktree: Path, branch: str) -> None:
        """Put HEAD on ``branch`` as what comes next on it -- never forced. The base
        branch is everybody's: a force there would take whatever was merged since with it,
        so a branch that moved meanwhile is refused and the caller says so."""
        if not g.has_remote(worktree, self.remote):
            raise NoRemote(f"the checkout has no remote named {self.remote!r}")
        try:
            g.run(
                worktree,
                *self._credentials(),
                "push",
                self.remote,
                f"HEAD:refs/heads/{branch}",
                env=self._env(),
            )
        except g.GitError as exc:
            raise GitHostError(f"push to {branch} refused: {exc.stderr}") from exc

    def delete_branch(self, worktree: Path, branch: str) -> bool:
        """Remove ``branch`` from the host. False when it was not there to remove."""
        if self.remote_head(worktree, branch) is None:
            return False
        try:
            g.run(
                worktree,
                *self._credentials(),
                "push",
                self.remote,
                "--delete",
                branch,
                env=self._env(),
            )
        except g.GitError as exc:
            raise GitHostError(f"could not delete {branch}: {exc.stderr}") from exc
        return True

    def close_pr(self, worktree: Path, pr_url: str) -> bool:
        """Close a pull request that is still open. False when it already was not."""
        view = self._gh(worktree, "pr", "view", pr_url, "--json", "state")
        if json.loads(view.stdout).get("state") != "OPEN":
            return False
        self._gh(worktree, "pr", "close", pr_url)
        return True

    def merged_commit(self, worktree: Path, pr_url: str) -> str | None:
        """The commit a merged pull request put on its base branch, or None when it was
        not merged. A squash merge leaves none of the branch's own commits on the base;
        this is the one commit that holds them."""
        view = self._gh(worktree, "pr", "view", pr_url, "--json", "state,mergeCommit")
        data: dict[str, Any] = json.loads(view.stdout)
        if data.get("state") != "MERGED":
            return None
        oid = (data.get("mergeCommit") or {}).get("oid")
        return str(oid) if oid else None

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


__all__ = ["CiState", "CiStatus", "GhHost", "GitHost", "GitHostError", "NoRemote"]
