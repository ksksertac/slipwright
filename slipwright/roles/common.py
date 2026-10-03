"""Shared plumbing for roles: worktree scanning, context assembly and file changes.

Roles are thin: they assemble a context dict, call ``invoke_role`` and post-process the
typed result. Everything that touches the filesystem on their behalf lives here so the
permission checks are in one place.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import Any

from slipwright.gates import toolchains
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


def where_it_runs() -> dict[str, Any]:
    """Where the project's build and test commands run, for every role that writes code or
    tests that run there.

    Only the Architect used to be told. QA, never told, wrote a mobile app's tests to launch
    the APK on an API 23 and an API 35 emulator and read it with TalkBack -- on a server with
    no device, no emulator and nothing it may install -- and the build gate failed the same
    way three times running, each round paid for, because nothing in what QA read said the
    test could never pass there.
    """
    return {
        "rules": (
            "The project's build and test commands run on a server, as an ordinary user, on "
            "a bare checkout: nothing can be installed (no system package manager, no SDK or "
            "emulator download), and no device, emulator or simulator is attached or can be "
            "started. A test that needs one can never pass there. Beyond git, curl, Python "
            "with uv and Node with npm, only what `installed` lists is there."
        ),
        "installed": toolchains.installed(),
    }


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
    job: Job,
    profile: Profile,
    role: RoleName,
    changes: list[FileChange],
    cut: Collection[str] = (),
) -> list[str]:
    """Write a role's file changes into the worktree. Returns the touched paths.

    Enforces the role's ``write_files`` permission and confines every path to the worktree.
    ``cut`` names the files the role was shown only part of: those take edits, never whole
    contents. Raises ``EditMismatch`` -- and writes nothing -- when an answer cannot be
    applied as written.
    """
    if not changes:
        return []
    if Permission.WRITE_FILES not in profile.roles[role].permissions:
        raise PermissionError(f"role {role.value} lacks the write_files permission")
    root = require_worktree(job).resolve()
    # every change is worked out before any is written: an edit that does not fit refuses
    # the whole answer, and a refused answer must not leave half of itself on disk
    planned: list[tuple[Path, str | None]] = []
    for change in changes:
        target = (root / change.path).resolve()
        if root not in target.parents and target != root:
            raise PermissionError(f"path escapes the worktree: {change.path}")
        if change.edits:
            planned.append((target, _edited(change, target)))
        elif change.content is not None and change.path in cut:
            raise EditMismatch(
                f"{change.path} was shown cut, so whole contents would lose the rest of "
                "it: change it with `edits`"
            )
        else:
            planned.append((target, change.content))
    touched: list[str] = []
    for (target, text), change in zip(planned, changes, strict=True):
        if text is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        touched.append(change.path)
    return touched


class EditMismatch(ValueError):
    """An answer that cannot be applied as written: an edit whose text is not in the file
    (or is in it more than once), or whole contents for a file the role was shown cut.
    Says what to do, with the file's real lines, for the role's next attempt."""


def _edited(change: FileChange, target: Path) -> str:
    """The file at ``target`` with ``change.edits`` applied in order."""
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise EditMismatch(f"{change.path} cannot be edited: it does not exist") from exc
    for n, edit in enumerate(change.edits or [], start=1):
        found = text.count(edit.find)
        if found == 1:
            text = text.replace(edit.find, edit.replace, 1)
            continue
        why = "is not in it" if found == 0 else f"is in it {found} times; make it longer"
        raise EditMismatch(
            f"edit {n} of {change.path}: its `find` text {why}. The file's lines nearest "
            f"to it, as they are now:\n{_nearest(text, edit.find)}"
        )
    return text


def _nearest(text: str, find: str, around: int = 6) -> str:
    """The lines of ``text`` around the one that shares the most with ``find``'s first
    line, numbered: what the role should copy from instead."""
    lines = text.splitlines()
    first = next((ln.strip() for ln in find.splitlines() if ln.strip()), find.strip())
    words = set(first.split())

    def score(line: str) -> int:
        return len(words & set(line.split())) + (100 if first and first in line else 0)

    best = max(range(len(lines)), key=lambda i: score(lines[i]), default=0)
    start, end = max(0, best - around), min(len(lines), best + around + 1)
    return "\n".join(f"{i + 1:>5}| {lines[i]}" for i in range(start, end))


__all__ = [
    "MANIFEST_FILES",
    "EditMismatch",
    "SKIP_DIRS",
    "apply_changes",
    "base_context",
    "list_tree",
    "project_facts",
    "read_files",
    "require_worktree",
    "scan_worktree",
]
