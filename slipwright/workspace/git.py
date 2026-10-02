"""Thin subprocess wrapper around git. Everything the workspace does to a repo goes here."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: What a package manager or a build fills a checkout with, which is never the work. A
#: project the agents start has no ``.gitignore`` until somebody writes one, and ``add -A``
#: once committed all of ``node_modules`` -- sixteen thousand files -- into a phase, whose
#: diff then went to QA at 150 million characters and was refused by the model. These are
#: kept out of every commit (through ``info/exclude``, so the project's own files are not
#: touched) and out of every diff a role is shown.
NEVER_COMMITTED = (
    "node_modules/",
    ".gradle/",
    "build/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".dart_tool/",
    ".next/",
    ".nuxt/",
    ".expo/",
    "DerivedData/",
    "coverage/",
)
#: Committed, but never worth a reviewer's reading: lock files a package manager writes
#: (a fresh ``package-lock.json`` is nine thousand lines) and compiled output, which says
#: again what its source already said. Left out of every diff a role is shown.
NEVER_SHOWN = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lockb",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "Podfile.lock",
    "pubspec.lock",
    "go.sum",
    "dist/",
)
#: The most of a diff a role is given. Past it the role reads which files changed and as
#: much of the change as fits; a model has a limit on what it is sent, and a diff that
#: size is not one anybody reviews line by line anyway.
MAX_DIFF_CHARS = 400_000
_EXCLUDE_MARK = "# slipwright: never committed"


class GitError(RuntimeError):
    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args_ = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"git {' '.join(args)} failed ({returncode}): {self.stderr}")


def run(
    repo: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
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
    # Without a token in the URL git asks for a username. There is nobody at the other
    # end of a server's stdin, so it either hangs until the request times out or fails
    # with an error about the terminal rather than about the credentials. Refusing the
    # prompt turns that into an immediate, honest failure the caller can explain.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(
        ["git", "clone", "--quiet", url, str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        raise GitError(["clone", url, str(target)], proc.returncode, proc.stderr)


def _not_ours() -> list[str]:
    """Pathspecs that leave ``NEVER_COMMITTED`` and ``NEVER_SHOWN`` out of a diff, at any
    depth: a directory with everything under it, a file by its name."""
    return [
        "--",
        ".",
        *(
            f":(exclude,glob)**/{p}**" if p.endswith("/") else f":(exclude,glob)**/{p}"
            for p in (*NEVER_COMMITTED, *NEVER_SHOWN)
        ),
    ]


def _capped(repo: Path, text: str, stat: list[str]) -> str:
    """``text``, or when it is too big to send, which files changed and as much as fits."""
    if len(text) <= MAX_DIFF_CHARS:
        return text
    files = run(repo, "diff", "--stat=200", "--no-color", *stat, *_not_ours()).stdout
    room = max(MAX_DIFF_CHARS - len(files), MAX_DIFF_CHARS // 2)
    return (
        f"(this diff is {len(text):,} characters; the first {room:,} follow the list of "
        f"changed files)\n\n{files}\n{text[:room]}\n(... cut here)"
    )


def diff(repo: Path, base: str, head: str = "HEAD") -> str:
    """What changed between two commits, as a role is shown it: dependencies and build
    output left out, and no bigger than ``MAX_DIFF_CHARS``."""
    text = run(repo, "diff", "--no-color", base, head, *_not_ours()).stdout
    return _capped(repo, text, [base, head])


def work_in_progress(repo: Path, base: str, limit: int = 12_000) -> str:
    """What the checkout holds against ``base`` right now, read for somebody asking about
    it while the run is still writing there.

    Read without touching the index. A plain ``git diff`` refreshes the index's stat
    information and takes ``index.lock`` to do it; the run's own ``git add`` a moment
    later would then fail on a lock it never took, and a question would have broken the
    phase it was asked about."""
    quiet = ("--no-optional-locks", "diff", "--no-color")
    stat = run(repo, *quiet, "--stat=200", base, *_not_ours(), check=False).stdout
    text = run(repo, *quiet, base, *_not_ours(), check=False).stdout
    if len(stat) + len(text) <= limit:
        return f"{stat}\n{text}".strip()
    room = max(limit - len(stat), limit // 2)
    return f"{stat}\n{text[:room]}\n(... cut here)".strip()


def changed_files(repo: Path, base: str, head: str = "HEAD") -> str:
    """Which files changed between two commits and by how many lines, every path whole:
    what a role that describes a change needs, without the change itself."""
    return run(
        repo, "diff", "--stat=240,200", "--no-color", base, head, *_not_ours()
    ).stdout.rstrip()


def numstat(repo: Path, base: str, head: str = "HEAD") -> list[tuple[str, int, int]]:
    """(path, added, removed) per file between two commits; a binary file counts as 0/0."""
    out = run(repo, "diff", "--numstat", "--no-color", base, head, *_not_ours()).stdout
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


def known(repo: Path, commit: str) -> bool:
    """Whether this checkout has ``commit`` at all -- one pushed from elsewhere and never
    fetched is not."""
    proc = run(repo, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
    return proc.returncode == 0


def reset_soft(repo: Path, commit: str) -> None:
    """Move the branch back to ``commit`` and keep what came after it staged."""
    run(repo, "reset", "-q", "--soft", commit)


def merge(repo: Path, ref: str) -> list[str]:
    """Bring ``ref`` into the branch: a fast-forward when it can be, a merge commit when
    both sides moved. Returns the files that conflicted -- and then the merge is undone
    and the checkout is as it was, because nobody is there to resolve it."""
    if run(repo, "merge", "-q", "--ff-only", ref, check=False).returncode == 0:
        return []
    proc = run(
        repo,
        "-c",
        "user.name=slipwright",
        "-c",
        "user.email=slipwright@localhost",
        "merge",
        "-q",
        "--no-edit",
        ref,
        check=False,
    )
    if proc.returncode == 0:
        return []
    conflicted = run(repo, "diff", "--name-only", "--diff-filter=U", check=False).stdout
    run(repo, "merge", "--abort", check=False)
    return conflicted.split() or [proc.stderr.strip() or "the merge failed"]


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
    """Stage everything but ``NEVER_COMMITTED``. What an earlier commit let in by mistake
    is taken back out of the index, so the next commit removes it from the branch."""
    _exclude_ours(repo)
    run(repo, "add", "-A")
    patterns = [f"--exclude={d}" for d in NEVER_COMMITTED]
    tracked = run(repo, "ls-files", "-z", "--cached", "--ignored", *patterns).stdout
    if tracked:
        run(
            repo,
            "rm",
            "-r",
            "-q",
            "--cached",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            stdin=tracked,
        )


def _exclude_ours(repo: Path) -> None:
    """``NEVER_COMMITTED`` in the repository's ``info/exclude``: shared by every worktree,
    never committed, and the project's own ``.gitignore`` is left alone."""
    common = Path(run(repo, "rev-parse", "--git-common-dir").stdout.strip())
    exclude = (common if common.is_absolute() else repo / common) / "info" / "exclude"
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if _EXCLUDE_MARK in current:
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    block = "\n".join([_EXCLUDE_MARK, *NEVER_COMMITTED])
    exclude.write_text(f"{current.rstrip()}\n{block}\n".lstrip(), encoding="utf-8")


def staged_diff(repo: Path) -> str:
    """Diff of the index against HEAD (call ``stage_all`` first to include new files),
    as a role is shown it -- see ``diff``."""
    text = run(repo, "diff", "--cached", "--no-color", *_not_ours()).stdout
    return _capped(repo, text, ["--cached"])


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
