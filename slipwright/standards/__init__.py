"""The standards corpus: Markdown pages under ``standards/<domain>/`` with front-matter.

``load_corpus`` reads the global corpus (this repository's ``standards/``) and, when
given, a project's override folder (``<repo>/.slipwright/standards/``), and splits every
page into chunks — one per ``##`` section — that carry the page title and domain so a
chunk is meaningful on its own. ``lint`` enforces the layout the retrieval quality
depends on (front-matter, short single-topic sections, unique headings per domain).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent
GLOBAL_DIR = PACKAGE_ROOT / "standards"
PROJECT_SUBDIR = Path(".slipwright") / "standards"
DOMAINS = (
    "core",
    "product",
    "architecture",
    "design",
    "backend",
    "web",
    "mobile",
    "testing",
    "devops",
)
MAX_SECTION_WORDS = 400

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_H1 = re.compile(r"^# (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Page:
    path: Path
    domain: str
    title: str
    tags: tuple[str, ...]
    applies_to: tuple[str, ...]
    body: str  # markdown after the front-matter
    scope: str = "global"  # or "project"

    @property
    def relpath(self) -> str:
        base = GLOBAL_DIR if self.scope == "global" else self.path.parents[1]
        try:
            return self.path.relative_to(base).as_posix()
        except ValueError:
            return self.path.name


@dataclass(frozen=True)
class Chunk:
    id: str  # sha256 of scope+path+heading+text: stable across reindexes
    scope: str
    domain: str
    page: str  # page relpath
    title: str
    heading: str
    text: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def document(self) -> str:
        """What gets embedded and shown: title and heading give the section context."""
        return f"{self.title} — {self.heading}\n\n{self.text}"


class StandardsError(ValueError):
    pass


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONT.match(text)
    if not match:
        return {}, text
    meta: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            meta[key.strip()] = [v.strip().strip("'\"") for v in raw[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = raw.strip("'\"")
    return meta, text[match.end() :]


def load_page(path: Path, *, scope: str = "global", domain: str | None = None) -> Page:
    return parse_page(path.read_text(encoding="utf-8"), path, scope=scope, domain=domain)


def parse_page(
    text: str, path: Path, *, scope: str = "global", domain: str | None = None
) -> Page:
    """A page from its text. ``path`` names it -- chunk ids, headings and retrieval all
    read it -- and need not exist: an account's rewritten pages live in the database."""
    meta, body = parse_front_matter(text)
    dom = str(meta.get("domain") or domain or path.parent.name)
    h1 = _H1.search(body)
    title = h1.group(1).strip() if h1 else path.stem.replace("-", " ").title()
    tags = meta.get("tags") or []
    applies = meta.get("applies_to") or []
    return Page(
        path=path,
        domain=dom,
        title=title,
        tags=tuple(tags) if isinstance(tags, list) else (str(tags),),
        applies_to=tuple(applies) if isinstance(applies, list) else (str(applies),),
        body=body,
        scope=scope,
    )


def page_from_text(domain: str, name: str, text: str, *, scope: str = "user") -> Page:
    """A page an account rewrote, indexed exactly as the shipped one would be.

    It is given the path the shipped page has, so a rewritten ``backend/services-and-apis``
    shadows the original rather than sitting beside it.
    """
    stem = name[:-3] if name.endswith(".md") else name
    return parse_page(text, GLOBAL_DIR / domain / f"{stem}.md", scope=scope, domain=domain)


def load_corpus(global_dir: Path | None = None, project_repo: Path | None = None) -> list[Page]:
    """Global pages plus the project's overrides (``<repo>/.slipwright/standards``)."""
    pages: list[Page] = []
    root = GLOBAL_DIR if global_dir is None else global_dir
    if root.is_dir():
        for path in sorted(root.rglob("*.md")):
            pages.append(load_page(path, scope="global"))
    if project_repo is not None:
        override = project_repo / PROJECT_SUBDIR
        if override.is_dir():
            for path in sorted(override.rglob("*.md")):
                pages.append(load_page(path, scope="project"))
    return pages


def split_sections(body: str) -> list[tuple[str, str]]:
    """``(heading, text)`` per ``##`` section; text before the first ``##`` is dropped
    unless it is the only content (then the page title is the heading)."""
    parts = re.split(r"^## +", body, flags=re.MULTILINE)
    sections: list[tuple[str, str]] = []
    for part in parts[1:]:
        heading, _, text = part.partition("\n")
        text = text.strip()
        if text:
            sections.append((heading.strip(), text))
    if not sections:
        intro = _H1.sub("", body).strip()
        if intro:
            sections.append(("", intro))
    return sections


def chunk_page(page: Page) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, text in split_sections(page.body):
        head = heading or page.title
        digest = hashlib.sha256(
            f"{page.scope}\n{page.relpath}\n{head}\n{text}".encode()
        ).hexdigest()[:24]
        chunks.append(
            Chunk(
                id=digest,
                scope=page.scope,
                domain=page.domain,
                page=page.relpath,
                title=page.title,
                heading=head,
                text=text,
                tags=page.tags,
            )
        )
    return chunks


def chunk_corpus(pages: list[Page]) -> list[Chunk]:
    return [c for page in pages for c in chunk_page(page)]


def lint(pages: list[Page]) -> list[str]:
    """Problems that would hurt retrieval; empty means the corpus is well-formed."""
    problems: list[str] = []
    seen: dict[tuple[str, str], str] = {}
    for page in pages:
        meta, _ = parse_front_matter(page.path.read_text(encoding="utf-8"))
        where = f"{page.scope}:{page.relpath}"
        if not meta:
            problems.append(f"{where}: missing front-matter (domain, tags, applies_to)")
        elif "domain" not in meta:
            problems.append(f"{where}: front-matter has no domain")
        if page.domain not in DOMAINS:
            problems.append(f"{where}: unknown domain {page.domain!r} (expected one of {DOMAINS})")
        if not _H1.search(page.body):
            problems.append(f"{where}: no '# Title' heading")
        sections = split_sections(page.body)
        if not sections:
            problems.append(f"{where}: no '## ' sections")
        for heading, text in sections:
            words = len(text.split())
            if words > MAX_SECTION_WORDS:
                problems.append(
                    f"{where}: section {heading!r} has {words} words (max {MAX_SECTION_WORDS})"
                )
            key = (page.domain, heading.lower())
            if key in seen and seen[key] != where:
                problems.append(
                    f"{where}: heading {heading!r} duplicates one in {seen[key]} (same domain)"
                )
            seen.setdefault(key, where)
    return problems


__all__ = [
    "DOMAINS",
    "GLOBAL_DIR",
    "MAX_SECTION_WORDS",
    "PROJECT_SUBDIR",
    "Chunk",
    "Page",
    "StandardsError",
    "chunk_corpus",
    "chunk_page",
    "lint",
    "load_corpus",
    "load_page",
    "page_from_text",
    "parse_front_matter",
    "parse_page",
    "split_sections",
]
