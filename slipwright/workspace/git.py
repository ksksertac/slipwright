"""Thin subprocess wrapper around git. Everything the workspace does to a repo goes here."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args_ = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {self.stderr}")


def run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise GitError(list(args), proc.returncode, proc.stderr)
    return proc


def branch_exists(repo: Path, branch: str) -> bool:
    proc = run(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
    return proc.returncode == 0


def worktree_paths(repo: Path) -> list[Path]:
    out = run(repo, "worktree", "list", "--porcelain").stdout
    return [
        Path(line.removeprefix("worktree ").strip())
        for line in out.splitlines()
        if line.startswith("worktree ")
    ]


def head_commit(repo: Path) -> str:
    return run(repo, "rev-parse", "HEAD").stdout.strip()


def stage_all(repo: Path) -> None:
    run(repo, "add", "-A")


def staged_diff(repo: Path) -> str:
    """Diff of the index against HEAD (call ``stage_all`` first to include new files)."""
    return run(repo, "diff", "--cached", "--no-color").stdout


def has_staged_changes(repo: Path) -> bool:
    return run(repo, "diff", "--cached", "--quiet", check=False).returncode != 0


def commit(repo: Path, message: str) -> bool:
    """Commit the index; returns False when there was nothing to commit."""
    if not has_staged_changes(repo):
        return False
    run(
        repo,
        "-c",
        "user.name=slipwright",
        "-c",
        "user.email=slipwright@localhost",
        "commit",
        "-q",
        "-m",
        message,
    )
    return True
