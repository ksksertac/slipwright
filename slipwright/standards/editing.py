"""Editing the standards from the UI (T9.6).

Pages are Markdown files: the global corpus under ``standards/`` in this repository, a
project's overrides under ``<repo>/.slipwright/standards``. A save writes the file where
the agents read it, checks it with the corpus linter, and — when the directory is inside
a git repository — also commits it on a ``slipwright/standards`` branch through a
separate worktree, so what people change in the UI is reviewable like any other change
without touching the checkout the app runs from.

The UI works one level down from pages: a *rule* is one ``##`` section (the unit the
retrieval hands to an agent), listed flat per domain and added, edited or removed on its
own. Rules added that way go to ``<domain>/rules.md`` (``core.md`` for the core rules);
the pages the corpus ships with keep their own files. A rule's id is ``<path>:<n>`` —
the n-th ``##`` block of the page's source — so it stays put while the rule is edited.
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
    GLOBAL_DIR,
    PROJECT_SUBDIR,
    StandardsError,
    lint,
    load_page,
    parse_page,
    split_sections,
)
from slipwright.workspace import git as g
from slipwright.workspace.git import GitError

log = logging.getLogger(__name__)

BRANCH = "slipwright/standards"
_PATH = re.compile(r"^(?:core\.md|(?:[a-z][a-z0-9-]*)/[a-z0-9][a-z0-9._-]*\.md)$")
_SLUG = re.compile(r"[^a-z0-9]+")
_SECTION = re.compile(r"^(?=## )", re.MULTILINE)  # keeps the "## " with its section
RULES_PAGE = "rules.md"  # where the UI puts a domain's added rules


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


@dataclass(frozen=True)
class Rule:
    id: str  # "<path>:<n>": the n-th "##" block of the page source
    path: str
    domain: str
    scope: str
    heading: str
    text: str
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


def split_source(text: str) -> tuple[str, list[str]]:
    """A page's source as ``(head, blocks)``: everything before the first ``## `` (the
    front-matter and title) and one string per ``##`` section, so that
    ``head + "".join(blocks)`` is the text again. Indices into ``blocks`` are rule ids."""
    parts = _SECTION.split(text)
    return parts[0], parts[1:]


def parse_block(block: str) -> tuple[str, str]:
    """``(heading, text)`` of one ``## `` block; the text is stripped."""
    first, _, rest = block.partition("\n")
    return first[3:].strip(), rest.strip()


def render_block(heading: str, text: str) -> str:
    return f"## {heading.strip()}\n\n{text.strip()}\n\n"


def rule_id(path: str, n: int) -> str:
    return f"{path}:{n}"


def parse_rule_id(rule: str) -> tuple[str, int]:
    path, sep, n = rule.rpartition(":")
    if not sep or not n.isdigit():
        raise PageError(f"not a rule id: {rule!r} (expected <path>:<n>)")
    return check_path(path), int(n)


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

    def list_rules(self, project_repo: Path | None, domain: str) -> list[Rule]:
        """Every ``##`` section of the domain's pages, flat, in page order. ``core`` lists
        only ``core.md``; any other domain leaves the core rules out."""
        out: list[Rule] = []
        for info in self.list_pages(project_repo, domain):
            if info.domain == domain:
                out.extend(self._rules_of(info, project_repo))
        return out

    def _rules_of(self, info: PageInfo, project_repo: Path | None) -> list[Rule]:
        file = self.root(project_repo) / info.path
        _, blocks = split_source(file.read_text(encoding="utf-8"))
        rules: list[Rule] = []
        for n, block in enumerate(blocks):
            heading, text = parse_block(block)
            if not text:
                continue  # not a chunk either
            rules.append(
                Rule(
                    id=rule_id(info.path, n),
                    path=info.path,
                    domain=info.domain,
                    scope=info.scope,
                    heading=heading,
                    text=text,
                    words=len(text.split()),
                    modified_at=info.modified_at,
                )
            )
        return rules

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

    # -- rules -------------------------------------------------------------------------

    def add_rule(
        self, domain: str, heading: str, text: str, project_repo: Path | None, *, author: str
    ) -> Rule:
        """Append a section to the domain's ``rules.md`` (``core.md`` for core), creating
        the page when the domain has none yet."""
        if domain not in DOMAINS:
            raise PageError(f"unknown domain {domain!r} (expected one of {DOMAINS})")
        heading, text = _clean_rule(heading, text)
        path = "core.md" if domain == "core" else f"{domain}/{RULES_PAGE}"
        file = self.root(project_repo) / path
        if file.is_file():
            head, blocks = split_source(file.read_text(encoding="utf-8"))
        else:
            head, blocks = split_source(new_page_text(domain, f"{domain.capitalize()} rules"))
            blocks = []  # the template's placeholder section is not a rule
        self._check_unique(heading, [parse_block(b)[0] for b in blocks])
        blocks.append(render_block(heading, text))
        info = self.write(path, _join(head, blocks), project_repo, author=author)
        return self._rule(info, project_repo, len(blocks) - 1)

    def update_rule(
        self, rule: str, heading: str, text: str, project_repo: Path | None, *, author: str
    ) -> Rule:
        path, n = parse_rule_id(rule)
        heading, text = _clean_rule(heading, text)
        head, blocks = split_source(self.read(path, project_repo))
        if n >= len(blocks):
            raise FileNotFoundError(rule)
        self._check_unique(heading, [parse_block(b)[0] for i, b in enumerate(blocks) if i != n])
        blocks[n] = render_block(heading, text)
        info = self.write(path, _join(head, blocks), project_repo, author=author)
        return self._rule(info, project_repo, n)

    def delete_rule(self, rule: str, project_repo: Path | None, *, author: str) -> None:
        """Remove one section; a page left without sections goes with it (except
        ``core.md``, which keeps at least one rule)."""
        path, n = parse_rule_id(rule)
        head, blocks = split_source(self.read(path, project_repo))
        if n >= len(blocks):
            raise FileNotFoundError(rule)
        del blocks[n]
        if not any(parse_block(b)[1] for b in blocks):
            if path == "core.md":
                raise PageError("core.md keeps at least one rule")
            self.delete(path, project_repo, author=author)
            return
        self.write(path, _join(head, blocks), project_repo, author=author)

    def _rule(self, info: PageInfo, project_repo: Path | None, n: int) -> Rule:
        wanted = rule_id(info.path, n)
        return next(r for r in self._rules_of(info, project_repo) if r.id == wanted)

    @staticmethod
    def _check_unique(heading: str, others: list[str]) -> None:
        # the linter only sees duplicates across pages; within one page it is on us
        if heading.lower() in {h.lower() for h in others}:
            raise PageError(f"a rule titled {heading!r} already exists on this page")

    def check_text(self, text: str, *, domain: str) -> None:
        """Lint a page that is not going to be a file.

        An account's rewritten pages are rows, not files, so there is no directory to
        lint them against; the shipped pages of the same domain stand in as siblings,
        which is where duplicate headings would come from anyway.
        """
        siblings = GLOBAL_DIR / domain
        self._raise_if_bad(siblings / "candidate.md", text, None)

    def describe(self, path: str, text: str, *, scope: str = "user") -> PageInfo:
        """What a page is, from its text alone: for pages that have no file behind them."""
        rel = check_path(path)
        page = parse_page(text, GLOBAL_DIR / rel, scope=scope, domain=rel.split("/")[0])
        sections = split_sections(page.body)
        return PageInfo(
            path=rel,
            domain=page.domain,
            title=page.title,
            scope=scope,
            sections=len(sections),
            words=sum(len(t.split()) for _, t in sections),
            modified_at=datetime.now(tz=UTC),
        )

    def _raise_if_bad(self, file: Path, text: str, project_repo: Path | None) -> None:
        problems = self._problems(file, text, project_repo)
        if problems:
            raise PageError("; ".join(problems))

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


def _clean_rule(heading: str, text: str) -> tuple[str, str]:
    heading = " ".join(heading.split())
    text = text.strip()
    if not heading:
        raise PageError("a rule needs a title")
    if not text:
        raise PageError("a rule needs a text")
    if _SECTION.search(text):
        raise PageError("a rule's text cannot open a '## ' section; add another rule instead")
    return heading, text


def _join(head: str, blocks: list[str]) -> str:
    body = "".join(b.rstrip("\n") + "\n\n" for b in blocks)
    return head.rstrip("\n") + "\n\n" + body.rstrip("\n") + "\n"


__all__ = [
    "BRANCH",
    "RULES_PAGE",
    "PageError",
    "PageInfo",
    "Rule",
    "StandardsEditor",
    "check_path",
    "new_page_text",
    "parse_rule_id",
    "rule_id",
    "split_source",
]
