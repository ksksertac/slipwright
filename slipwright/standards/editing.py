"""Editing the standards from the UI (T9.6).

Pages are Markdown files: the global corpus under ``standards/`` in this repository, a
project's overrides under ``<repo>/.slipwright/standards``. A save writes the file where
the agents read it, checks it with the corpus linter, and — when the directory is inside
a git repository — also commits it on a ``slipwright/standards`` branch through a
separate worktree, so what people change in the UI is reviewable like any other change
without touching the checkout the app runs from.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from slipwright.standards import (
    DOMAINS,
    PROJECT_SUBDIR,
    StandardsError,
    lint,
    load_page,
    split_sections,
)
from slipwright.workspace import git as g
from slipwright.workspace.git import GitError

log = logging.getLogger(__name__)

BRANCH = "slipwright/standards"
_PATH = re.compile(r"^(?:core\.md|(?:[a-z][a-z0-9-]*)/[a-z0-9][a-z0-9._-]*\.md)$")
_SLUG = re.compile(r"[^a-z0-9]+")


class PageError(ValueError):
    """A bad path or a page the linter refuses."""


@dataclass(frozen=True)
class PageInfo:
    path: str  # relative: "backend/services-and-apis.md" or "core.md"
    domain: str
    title: str
    scope: str
    sections: int
    words: int
    modified_at: datetime


def check_path(path: str) -> str:
    """A safe relative page path: ``<domain>/<name>.md`` or ``core.md``."""
    if not _PATH.match(path) or ".." in path:
        raise PageError(f"not a page path: {path!r} (expected <domain>/<name>.md)")
    domain = path.split("/", 1)[0] if "/" in path else "core"
    if domain not in DOMAINS:
        raise PageError(f"unknown domain {domain!r} (expected one of {DOMAINS})")
    return path


def slug(title: str) -> str:
    return _SLUG.sub("-", title.lower()).strip("-") or "page"


def new_page_text(domain: str, title: str, body: str = "") -> str:
    """Front-matter plus a title; ``body`` may already carry ``##`` sections."""
    text = body.strip() or "## Rule\n\nState the rule, why it exists and how to apply it."
    return f"---\ndomain: {domain}\ntags: []\napplies_to: [{domain}]\n---\n\n# {title}\n\n{text}\n"


class StandardsEditor:
    def __init__(self, global_dir: Path, worktrees_dir: Path) -> None:
        self.global_dir = global_dir
        self.worktrees_dir = worktrees_dir  # where the review-branch worktrees live

    # -- where ---------------------------------------------------------------------------

    def root(self, project_repo: Path | None) -> Path:
        return self.global_dir if project_repo is None else project_repo / PROJECT_SUBDIR

    def scope(self, project_repo: Path | None) -> str:
        return "global" if project_repo is None else "project"

    # -- read ----------------------------------------------------------------------------

    def list_pages(self, project_repo: Path | None, domain: str | None = None) -> list[PageInfo]:
        root = self.root(project_repo)
        if not root.is_dir():
            return []
        out: list[PageInfo] = []
        for path in sorted(root.rglob("*.md")):
            rel = path.relative_to(root).as_posix()
            try:
                check_path(rel)
                page = load_page(path, scope=self.scope(project_repo))
            except (PageError, StandardsError, UnicodeDecodeError):
                continue
            if domain and page.domain != domain and page.domain != "core":
                continue
            sections = split_sections(page.body)
            out.append(
                PageInfo(
                    path=rel,
                    domain=page.domain,
                    title=page.title,
                    scope=page.scope,
                    sections=len(sections),
                    words=sum(len(t.split()) for _, t in sections),
                    modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                )
            )
        return out

    def read(self, path: str, project_repo: Path | None) -> str:
        file = self.root(project_repo) / check_path(path)
        if not file.is_file():
            raise FileNotFoundError(path)
        return file.read_text(encoding="utf-8")

    # -- write ---------------------------------------------------------------------------

    def write(self, path: str, text: str, project_repo: Path | None, *, author: str) -> PageInfo:
        """Save a page after the linter accepted it, then commit it on the review branch."""
        rel = check_path(path)
        root = self.root(project_repo)
        file = root / rel
        file.parent.mkdir(parents=True, exist_ok=True)
        problems = self._problems(file, text, project_repo)
        if problems:
            raise PageError("; ".join(problems))
        file.write_text(text, encoding="utf-8")
        self._commit(root, rel, f"standards: update {rel} (by {author})", delete=False)
        page = load_page(file, scope=self.scope(project_repo))
        sections = split_sections(page.body)
        return PageInfo(
            path=rel,
            domain=page.domain,
            title=page.title,
            scope=page.scope,
            sections=len(sections),
            words=sum(len(t.split()) for _, t in sections),
            modified_at=datetime.fromtimestamp(file.stat().st_mtime, tz=UTC),
        )

    def create(
        self, domain: str, title: str, text: str, project_repo: Path | None, *, author: str
    ) -> PageInfo:
        if domain not in DOMAINS or domain == "core":
            raise PageError(f"unknown domain {domain!r}")
        rel = f"{domain}/{slug(title)}.md"
        if (self.root(project_repo) / rel).exists():
            raise PageError(f"{rel} already exists")
        body = text if text.lstrip().startswith("---") else new_page_text(domain, title, text)
        return self.write(rel, body, project_repo, author=author)

    def delete(self, path: str, project_repo: Path | None, *, author: str) -> None:
        rel = check_path(path)
        if rel == "core.md":
            raise PageError("core.md cannot be deleted")
        root = self.root(project_repo)
        file = root / rel
        if not file.is_file():
            raise FileNotFoundError(path)
        file.unlink()
        self._commit(root, rel, f"standards: remove {rel} (by {author})", delete=True)

    def _problems(self, file: Path, text: str, project_repo: Path | None) -> list[str]:
        """Lint the candidate page together with its siblings (duplicate headings)."""
        with tempfile.TemporaryDirectory(prefix="slipwright-lint-") as tmp_dir:
            tmp = Path(tmp_dir) / file.name
            tmp.write_text(text, encoding="utf-8")
            try:
                candidate = load_page(tmp, scope=self.scope(project_repo), domain=file.parent.name)
            except StandardsError as exc:
                return [str(exc)]
            siblings = [
                load_page(p, scope=self.scope(project_repo))
                for p in sorted(file.parent.glob("*.md"))
                if p != file
            ]
            problems = lint([candidate, *siblings])
            return [p for p in problems if tmp.name in p]

    # -- git -----------------------------------------------------------------------------

    def _repo_of(self, root: Path) -> Path | None:
        try:
            top = g.run(root, "rev-parse", "--show-toplevel").stdout.strip()
        except (GitError, OSError):
            return None
        return Path(top) if top else None

    def _commit(self, root: Path, rel: str, message: str, *, delete: bool) -> None:
        """Mirror the change onto the ``slipwright/standards`` branch through a worktree of
        the same repository. Never raises: a missing repository just means no review
        branch, which the log records."""
        repo = self._repo_of(root)
        if repo is None:
            log.info("standards: %s is not under git, no review branch", root)
            return
        try:
            wt = self.worktrees_dir / f"standards-{abs(hash(str(repo))) % 10**8}"
            if not (wt / ".git").exists():
                wt.parent.mkdir(parents=True, exist_ok=True)
                g.run(repo, "worktree", "prune")
                if g.branch_exists(repo, BRANCH):
                    g.run(repo, "worktree", "add", "-q", str(wt), BRANCH)
                else:
                    g.run(repo, "worktree", "add", "-q", "-b", BRANCH, str(wt), "HEAD")
            inside = (root / rel).resolve().relative_to(repo.resolve()).as_posix()
            target = wt / inside
            if delete:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / rel, target)
            g.run(wt, "add", "-A", "--", inside)
            g.commit(wt, message)
        except (GitError, OSError, ValueError) as exc:
            log.warning("standards: could not commit %s on %s: %s", rel, BRANCH, exc)


__all__ = ["BRANCH", "PageError", "PageInfo", "StandardsEditor", "check_path", "new_page_text"]
