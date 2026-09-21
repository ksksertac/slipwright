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


def list_tree(root: Path, limit: int = MAX_TREE_ENTRIES) -> list[str]:
    """Relative paths under ``root`` (sorted, bounded), skipping vendored/tool dirs."""
    entries: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel = Path(dirpath).relative_to(root)
        for name in sorted(filenames):
            entries.append((rel / name).as_posix() if rel != Path(".") else name)
            if len(entries) >= limit:
                entries.append(f"... (truncated at {limit} entries)")
                return entries
    return entries


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


def scan_worktree(root: Path) -> dict[str, Any]:
    return {"tree": list_tree(root), "files": read_files(root, MANIFEST_FILES)}


def writing_rules(language: str) -> str:
    """How every role writes for people: in the project's language, briefly. Code stays
    in English — identifiers, paths, commit messages and JSON keys are not prose."""
    from slipwright.schemas.project import LANGUAGE_NAMES

    name = LANGUAGE_NAMES.get(language, language)
    return (
        f"Write every text a person will read in {name}: titles, descriptions, summaries, "
        "reasons, feedback, test-case names and descriptions, decisions. Keep code, "
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
    """Context every role receives: the request, any rejection feedback, pending inbox,
    and (only for roles allowed to act in Jira) the Jira section."""
    ctx: dict[str, Any] = {"instructions": instructions, "request": job.request}
    ctx["writing"] = writing_rules(job.data.language)
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


def plan_outline(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """The plan as a role that implements or tests it needs it: summary, decisions and
    the phase goals — never the breakdown tree or file lists of other phases."""
    if not plan:
        return None
    return {
        "summary": plan.get("summary"),
        "decisions": plan.get("decisions", []),
        "phases": [
            {"number": i + 1, "goal": p.get("goal"), "domain": p.get("domain", "general")}
            for i, p in enumerate(plan.get("phases", []))
        ],
    }


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
