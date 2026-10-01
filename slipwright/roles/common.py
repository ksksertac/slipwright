"""Shared plumbing for roles: worktree scanning, context assembly and file changes.

Roles are thin: they assemble a context dict, call ``invoke_role`` and post-process the
typed result. Everything that touches the filesystem on their behalf lives here so the
permission checks are in one place.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from slipwright.roles.results import FileChange
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Permission, Profile, RoleName

SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
)
MANIFEST_FILES = (
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Pipfile",
    "package.json",
    "tsconfig.json",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "Gemfile",
    "composer.json",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "README.md",
    "README.rst",
    "README",
)
MAX_TREE_ENTRIES = 400
MAX_FILE_BYTES = 12_000
#: What is not code. A folder with more than a few of these is counted, not listed: a
#: model writing code needs to know the images are there, not each one's name.
NOT_CODE_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".ico", ".svg",
        ".heic", ".tif", ".tiff", ".psd",
        ".ttf", ".otf", ".woff", ".woff2", ".eot",
        ".mp3", ".mp4", ".wav", ".ogg", ".webm", ".mov", ".m4a",
        ".pdf", ".zip",
    }
)  # fmt: skip
_DOC_SUFFIXES = frozenset({".md", ".rst", ".txt"})
#: Up to this many of them in one folder are still listed one by one.
_LISTED_NOT_CODE = 3
#: A walk stops here: a monorepo is not read to its last file to choose 400 of them.
_MAX_WALK = 20_000


def list_tree(root: Path, limit: int = MAX_TREE_ENTRIES, first: Iterable[str] = ()) -> list[str]:
    """Relative paths under ``root``, bounded, skipping vendored and tool directories.

    The cap used to fall wherever an alphabetical walk reached it, so in a big repository
    ``assets/`` or ``public/`` filled it and ``src/`` never appeared (T15.3). What the
    reader needs most comes first: the folders of ``first`` (the files a phase touches),
    then the files at the top, then code, then documents. Images, fonts and media are
    counted per folder. What does not fit is said, with where it was.
    """
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = Path(dirpath).relative_to(root)
        files.extend((rel / n).as_posix() if rel != Path(".") else n for n in sorted(filenames))
        if len(files) >= _MAX_WALK:
            break

    def folder(path: str) -> str:
        return path.rpartition("/")[0]

    def not_code(path: str) -> bool:
        return Path(path).suffix.lower() in NOT_CODE_SUFFIXES

    counted: dict[str, list[str]] = {}
    for path in files:
        if not_code(path):
            counted.setdefault(folder(path), []).append(path)
    counted = {d: paths for d, paths in counted.items() if len(paths) > _LISTED_NOT_CODE}
    focus = {folder(p.strip("/")) for p in first}

    def rank(path: str) -> int:
        where = folder(path)
        if any(where == f or (f and where.startswith(f + "/")) for f in focus):
            return 0
        if not where:
            return 1
        return 3 if Path(path).suffix.lower() in _DOC_SUFFIXES else 2

    ranked = [(rank(p), p, p) for p in files if not (not_code(p) and folder(p) in counted)]
    # a counted folder is one line, so it sits among the code where its folder would
    for where, paths in counted.items():
        kinds = ", ".join(sorted({Path(p).suffix.lower() for p in paths}))
        line = f"{where or '.'}/ ({len(paths)} files: {kinds})"
        ranked.append((min(rank(paths[0]), 2), f"{where}/", line))
    listed = [line for _, _, line in sorted(ranked)]
    if len(listed) <= limit:
        return listed
    left = listed[limit:]
    tops: dict[str, int] = {}
    for entry in left:
        top = entry.split("/", 1)[0] if "/" in entry else "."
        tops[top] = tops.get(top, 0) + 1
    where = ", ".join(f"{t}/ {n}" for t, n in sorted(tops.items(), key=lambda kv: -kv[1])[:5])
    return [*listed[:limit], f"... ({len(left)} more left out: {where})"]


def read_files(root: Path, names: Iterable[str], max_bytes: int = MAX_FILE_BYTES) -> dict[str, str]:
    """Contents of the named files (relative to root) that exist, truncated per file."""
    out: dict[str, str] = {}
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        text = data[:max_bytes].decode("utf-8", errors="replace")
        if len(data) > max_bytes:
            text += f"\n... (truncated, {len(data)} bytes total)"
        out[name] = text
    return out


def scan_worktree(root: Path, limit: int = MAX_TREE_ENTRIES) -> dict[str, Any]:
    return {"tree": list_tree(root, limit), "files": read_files(root, MANIFEST_FILES)}


def writing_rules(language: str) -> str:
    """How every role writes for people: in the project's language, briefly. Code stays
    in English — identifiers, paths, commit messages and JSON keys are not prose."""
    from slipwright.schemas.project import LANGUAGE_NAMES

    name = LANGUAGE_NAMES.get(language, language)
    return (
        f"Write every text a person will read in {name}: titles, descriptions, summaries, "
        "reasons, feedback, test-case names and descriptions, decisions, and the plan — "
        "its summary, its decisions and every phase title and goal, which are read on the "
        f"project's board. All of it in {name}, including the phase titles. Keep code, "
        "identifiers, file paths, commands, commit messages and JSON keys in English. "
        "`summary` is for the person who approves the next step: two to four plain "
        "sentences saying what was done and what they should look at — no file lists, "
        "no internal jargon, no restating the rules you followed."
    )


def base_context(
    job: Job,
    *,
    instructions: str,
    feedback: str | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Context every role receives: the request, the project brief, any rejection
    feedback, pending inbox, and (only for roles allowed to act in Jira) the Jira
    section."""
    ctx: dict[str, Any] = {"instructions": instructions, "request": job.request}
    ctx["writing"] = writing_rules(job.data.language)
    if job.data.brief:
        # what this project is, approved by a person before any agent read it
        ctx["project"] = job.data.brief
    if feedback:
        ctx["feedback"] = feedback
    if jira:
        ctx["jira"] = jira
    if standards:
        ctx["standards"] = standards
    pending = [m.text for m in job.pending_messages]
    if pending:
        ctx["messages_from_human"] = pending
    return ctx


def plan_outline(plan: dict[str, Any] | None, current: int | None = None) -> dict[str, Any] | None:
    """The plan as a role that implements or tests it needs it: summary, stack,
    decisions and the phase goals — never the breakdown tree or file lists of other
    phases.

    With ``current`` (a phase index), the phases are named by their heading only and that
    one is marked (T15.6): a developer building phase 7 needs to know phase 8 exists, not
    what it will verify, and its own phase it has whole in ``current_phase``. It was sent
    every phase in full on every call. The decisions stay whole: they are free text no
    one tagged by domain, and they bind every phase."""
    if not plan:
        return None
    phases: list[dict[str, Any]] = []
    for i, p in enumerate(plan.get("phases", [])):
        entry = {
            "number": i + 1,
            "goal": p.get("goal") if current is None else _heading(p.get("goal")),
            "domain": p.get("domain", "general"),
        }
        if current == i:
            entry["this_phase"] = True
        phases.append(entry)
    return {
        "summary": plan.get("summary"),
        "stack": plan.get("stack", []),
        "decisions": plan.get("decisions", []),
        "phases": phases,
    }


def _heading(goal: Any) -> Any:
    """A phase goal's heading: the part before its colon ("Show the result and the cup:
    from the host's final view..."), or its first 100 characters."""
    if not isinstance(goal, str):
        return goal
    head, colon, _ = goal.partition(":")
    if colon and len(head) <= 120:
        return head.strip()
    return goal if len(goal) <= 100 else goal[:100].rstrip() + "…"


def project_facts(profile: Profile) -> dict[str, str | int]:
    """The profile's build/test/run facts, as every implementing role sees them."""
    return {
        "language": profile.language,
        "package_manager": profile.package_manager,
        "build_cmd": profile.build_cmd,
        "test_cmd": profile.test_cmd,
        "run_cmd": profile.run_cmd,
        "port": profile.port,
    }


def require_worktree(job: Job) -> Path:
    if job.worktree_path is None:
        raise RuntimeError(f"job {job.id} has no worktree")
    return job.worktree_path


def apply_changes(
    job: Job, profile: Profile, role: RoleName, changes: list[FileChange]
) -> list[str]:
    """Write a role's file changes into the worktree. Returns the touched paths.

    Enforces the role's ``write_files`` permission and confines every path to the worktree.
    """
    if not changes:
        return []
    if Permission.WRITE_FILES not in profile.roles[role].permissions:
        raise PermissionError(f"role {role.value} lacks the write_files permission")
    root = require_worktree(job).resolve()
    touched: list[str] = []
    for change in changes:
        target = (root / change.path).resolve()
        if root not in target.parents and target != root:
            raise PermissionError(f"path escapes the worktree: {change.path}")
        if change.content is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.content, encoding="utf-8", newline="\n")
        touched.append(change.path)
    return touched


__all__ = [
    "MANIFEST_FILES",
    "SKIP_DIRS",
    "apply_changes",
    "base_context",
    "list_tree",
    "project_facts",
    "read_files",
    "require_worktree",
    "scan_worktree",
]
