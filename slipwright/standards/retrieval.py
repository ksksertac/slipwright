"""What a role gets to read before it works: the ``core`` page in full, then the
best-matching sections of its domain, cut to a token budget (T9.4).

The query is built from what the role is about to do — the current phase's goal, files
and backlog task first, the request last — so a Kafka phase pulls the retry rules and a
form phase pulls the accessibility rules, not the other way round.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slipwright.roles.specialists import DEVELOPER_ROLES, STANDARDS_DOMAIN
from slipwright.schemas.job import Job
from slipwright.schemas.profile import RoleName
from slipwright.standards import DOMAINS, PROJECT_SUBDIR, load_page
from slipwright.standards.index import Hit

DEFAULT_BUDGET = 2000
SIDE_DOMAIN_K = 2  # sections per neighbouring domain for the roles that read across

BINDING = (
    "The sections under `retrieved` are this project's engineering standards and are "
    "binding unless they contradict `core`, which always wins. When you cannot follow a "
    "retrieved standard, say which one and why in `summary`."
)

Search = Callable[[str, str | None, int], list[Hit]]
Browse = Callable[[str | None, int], list[Hit]]


def estimate_tokens(text: str) -> int:
    """Deterministic and provider-independent: about four characters per token."""
    return (len(text) + 3) // 4


@dataclass
class Retrieval:
    role: RoleName
    domain: str
    query: str
    core: str
    budget: int
    sections: list[dict[str, Any]] = field(default_factory=list)
    dropped: int = 0  # sections that matched but did not fit the budget
    browsed: bool = False  # nothing matched: the domain's opening sections were used

    @property
    def tokens(self) -> int:
        return sum(estimate_tokens(s["text"]) for s in self.sections)

    @property
    def chunk_ids(self) -> list[str]:
        return [str(s["id"]) for s in self.sections]

    def as_context(self) -> dict[str, Any]:
        return {
            "note": BINDING,
            "domain": self.domain,
            "core": self.core,
            "retrieved": [
                {k: s[k] for k in ("id", "page", "heading", "text", "scope")} for s in self.sections
            ],
        }

    def note(self, phase: int | None = None) -> str:
        who = f"{self.role.value} phase {phase}" if phase else self.role.value
        return f"standards ({who}): {len(self.sections)} section(s)"

    def detail(self) -> str:
        lines = [f"domain: {self.domain}", f"query: {self.query}", f"budget: {self.budget} tokens"]
        if self.browsed:
            lines.append("(no section matched the query: the domain's opening sections were used)")
        lines += [f"{s['id'][:12]}  {s['page']} — {s['heading']}" for s in self.sections]
        if self.dropped:
            lines.append(f"({self.dropped} more section(s) matched but exceeded the budget)")
        return "\n".join(lines)


def core_text(global_dir: Path, project_repo: Path | None = None) -> str:
    """``core.md`` from the global corpus, followed by the project's own core page if it
    has one. Never empty when the global page exists."""
    parts: list[str] = []
    for root in (global_dir, project_repo / PROJECT_SUBDIR if project_repo else None):
        if root is None:
            continue
        page = root / "core.md"
        if page.is_file():
            parts.append(load_page(page, scope="global" if root is global_dir else "project").body)
    return "\n\n".join(parts).strip()


def _task_title(job: Job, task_id: str | None) -> str | None:
    if not task_id:
        return None
    tree = (job.data.plan or {}).get("breakdown") or job.data.backlog or {}
    for epic in tree.get("epics", []):
        for story in epic.get("stories", []):
            for task in story.get("tasks", []):
                if task.get("id") == task_id:
                    return f"{story.get('title', '')} {task.get('title', '')}".strip()
    return None


def _backlog_titles(job: Job) -> list[str]:
    tree = job.data.backlog or (job.data.plan or {}).get("breakdown") or {}
    titles: list[str] = []
    for epic in tree.get("epics", []):
        titles.append(str(epic.get("title", "")))
        for story in epic.get("stories", []):
            titles.append(str(story.get("title", "")))
            titles.extend(str(t.get("title", "")) for t in story.get("tasks", []))
    return titles


def build_query(job: Job, role: RoleName) -> str:
    """The most specific words first: the FTS layer keeps only the first few dozen."""
    plan = job.data.plan or {}
    phases: list[dict[str, Any]] = plan.get("phases", [])
    parts: list[str] = []
    if role in DEVELOPER_ROLES and phases:
        phase = phases[min(job.data.phase_index, len(phases) - 1)]
        parts.append(str(phase.get("goal", "")))
        parts.extend(str(f) for f in phase.get("files", []))
        title = _task_title(job, phase.get("task_id"))
        if title:
            parts.append(title)
    elif role is RoleName.QA:
        parts.extend(str(c.get("name", "")) for c in job.data.test_cases)
        parts.extend(str(p.get("goal", "")) for p in phases)
    elif role is RoleName.DEVOPS:
        parts.append(str(plan.get("summary", "")))
        parts.extend(str(p.get("goal", "")) for p in phases)
    elif role is RoleName.ARCHITECT:
        parts.extend(_backlog_titles(job))
    parts.append(job.request)
    return " ".join(p for p in parts if p)[:2000]


def domains_for(role: RoleName) -> list[tuple[str, int | None]]:
    """(domain, k) pairs to search, in order; ``None`` means the configured top_k.
    The Architect reads its own domain first and then a little of every other one, so it
    can tag phases and respect the specialists' rules in its decisions."""
    own = STANDARDS_DOMAIN.get(role, "*")
    if role is RoleName.ARCHITECT:
        others = [d for d in DOMAINS if d not in ("core", own)]
        return [(own, None)] + [(d, SIDE_DOMAIN_K) for d in others]
    return [(own, None)]


def retrieve(
    search: Search,
    job: Job,
    role: RoleName,
    *,
    core: str,
    budget: int = DEFAULT_BUDGET,
    top_k: int = 4,
    browse: Browse | None = None,
) -> Retrieval:
    """Rank-ordered sections that fit the budget. Deterministic: same corpus, same job,
    same budget gives the same list. A section that does not fit is dropped and smaller
    ones after it may still be taken, so a budget is never wasted on one long page.

    When nothing in the role's own domain matches the query, ``browse`` supplies that
    domain's opening sections instead: a Product Owner writing a backlog for "add
    /health" still reads how this project writes stories."""
    query = build_query(job, role)
    domain = STANDARDS_DOMAIN.get(role, "*")
    result = Retrieval(role=role, domain=domain, query=query, core=core, budget=budget)
    seen: set[str] = set()
    used = 0
    for dom, k in domains_for(role):
        hits = search(query, None if dom == "*" else dom, k or top_k)
        if not hits and dom == domain and browse is not None:
            hits = browse(None if dom == "*" else dom, k or top_k)
            result.browsed = True
        for hit in hits:
            if hit.chunk.id in seen:
                continue
            seen.add(hit.chunk.id)
            cost = estimate_tokens(hit.chunk.text)
            if used + cost > budget:
                result.dropped += 1
                continue
            used += cost
            result.sections.append(hit.as_context())
    return result


__all__ = [
    "BINDING",
    "DEFAULT_BUDGET",
    "Retrieval",
    "build_query",
    "core_text",
    "domains_for",
    "estimate_tokens",
    "retrieve",
]
