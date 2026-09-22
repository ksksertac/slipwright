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


def run(
    repo: Path, *args: str, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if check and proc.returncode != 0:
        raise GitError(list(args), proc.returncode, proc.stderr)
    return proc


def clone(url: str, target: Path) -> None:
    """Clone ``url`` into ``target`` (which must not exist yet)."""
    proc = subprocess.run(
        ["git", "clone", "--quiet", url, str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise GitError(["clone", url, str(target)], proc.returncode, proc.stderr)


def numstat(repo: Path, base: str, head: str = "HEAD") -> list[tuple[str, int, int]]:
    """(path, added, removed) per file between two commits; a binary file counts as 0/0."""
    out = run(repo, "diff", "--numstat", "--no-color", base, head).stdout
    rows: list[tuple[str, int, int]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        rows.append(
            (path, int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0)
        )
    return rows


def commits(repo: Path, base: str, head: str = "HEAD") -> list[tuple[str, str]]:
    """(short sha, subject) of the commits head has and base does not, oldest last."""
    out = run(repo, "log", "--format=%h%x09%s", f"{base}..{head}").stdout
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        sha, _, subject = line.partition("\t")
        if sha:
            rows.append((sha, subject))
    return rows


def contains(repo: Path, commit: str, branch: str) -> bool:
    """Whether ``branch`` already contains ``commit`` (the work is merged)."""
    proc = run(repo, "merge-base", "--is-ancestor", commit, branch, check=False)
    return proc.returncode == 0


def has_remote(repo: Path, name: str = "origin") -> bool:
    proc = run(repo, "remote", "get-url", name, check=False)
    return proc.returncode == 0


def set_remote(repo: Path, name: str, url: str) -> None:
    """Point ``name`` at ``url``, adding the remote when the repo has none by that name."""
    run(repo, "remote", "set-url" if has_remote(repo, name) else "add", name, url)


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
