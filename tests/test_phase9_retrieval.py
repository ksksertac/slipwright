"""T9.4 — standards retrieved into every role's prompt."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from slipwright.activity import ActivityKind, job_activity
from slipwright.providers import ModelRequest
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.standards import GLOBAL_DIR
from slipwright.standards.retrieval import (
    BINDING,
    build_query,
    core_text,
    domains_for,
    estimate_tokens,
    retrieve,
)
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, full_seed, past_design, set_plan

KAFKA = "Add a Kafka consumer that retries failed messages with backoff"
FORM = "Add a signup form with labelled inputs and keyboard focus"


@pytest.fixture
def seed() -> Profile:
    return full_seed()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[JobStore]:
    with JobStore(tmp_path / "jobs.sqlite3") as s:
        yield s


def _context(req: ModelRequest) -> dict[str, Any]:
    text = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    ctx: dict[str, Any] = json.loads(text)
    return ctx


def _standards(req: ModelRequest) -> dict[str, Any]:
    section: dict[str, Any] = _context(req)["standards"]
    return section


def _headings(req: ModelRequest) -> list[str]:
    return [s["heading"] for s in _standards(req)["retrieved"]]


def _two_phase_job(store: JobStore, worktrees_root: Path, seed: Profile, repo: Path) -> Any:
    provider = full_provider(seed, phases=2)
    set_plan(
        provider,
        seed,
        [
            {"goal": KAFKA, "files": ["app/consumer.py"], "domain": "backend"},
            {"goal": FORM, "files": ["web/src/Signup.tsx"], "domain": "web"},
        ],
    )
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("messaging and signup", repo).id)
    job = engine.approve(job.id)  # backlog
    job = engine.approve(job.id)  # architecture -> the backend phase, then the screens
    job = past_design(engine, job)  # the web phase waits for them; this test is not about that
    assert job.state is JobState.AWAITING_TEST_APPROVAL, job.history[-1]
    return engine, provider, job


def test_every_role_gets_core_and_its_domain(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    _, provider, _ = _two_phase_job(store, worktrees_root, seed, repo)
    by_role = {r.role: r for r in provider.requests}
    core = core_text(GLOBAL_DIR)
    assert core.startswith("# Ortak kurallar")
    for role, req in by_role.items():
        section = _standards(req)
        assert section["core"] == core
        assert section["note"] == BINDING
        assert section["domain"] == {
            RoleName.PO: "product",
            RoleName.ARCHITECT: "architecture",
            RoleName.BACKEND: "backend",
            RoleName.WEB_UI: "web",
            RoleName.QA: "testing",
            RoleName.DEVOPS: "devops",
        }.get(role, section["domain"])
        assert section["retrieved"], role  # every domain has something to say
        assert all(s["id"] and s["page"] and s["text"] for s in section["retrieved"])


def test_kafka_phase_gets_retry_rules_and_form_phase_gets_accessibility(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    _, provider, _ = _two_phase_job(store, worktrees_root, seed, repo)
    backend = next(r for r in provider.requests if r.role is RoleName.BACKEND)
    web = next(r for r in provider.requests if r.role is RoleName.WEB_UI)

    backend_headings = _headings(backend)
    assert any("Kafka tüketicileri ve yeniden denemeler" in h for h in backend_headings), (
        backend_headings
    )
    assert not any("Erişilebilirlik" in h for h in backend_headings)
    assert all(s["page"].startswith("backend/") for s in _standards(backend)["retrieved"])

    web_headings = _headings(web)
    assert any("Erişilebilirlik" in h for h in web_headings), web_headings
    assert not any("Kafka" in h for h in web_headings)
    assert all(s["page"].startswith("web/") for s in _standards(web)["retrieved"])

    # the developer's query leads with the phase, not the request
    assert _context(backend)["standards"]["retrieved"][0]["page"].startswith("backend/")


def test_retrievals_are_recorded_per_phase_in_the_history(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    _, _, job = _two_phase_job(store, worktrees_root, seed, repo)
    notes = [t.note or "" for t in job.history if (t.note or "").startswith("standards")]
    assert notes[0].startswith("standards (po): ")
    assert notes[1].startswith("standards (architect): ")
    assert any(n.startswith("standards (backend phase 1): ") for n in notes)
    assert any(n.startswith("standards (web_ui phase 2): ") for n in notes)
    assert any(n.startswith("standards (qa): ") for n in notes)
    entry = next(t for t in job.history if (t.note or "").startswith("standards (backend"))
    assert entry.detail is not None
    assert "domain: backend" in entry.detail
    assert "Kafka tüketicileri ve yeniden denemeler" in entry.detail
    items = job_activity(job)
    kinds = {(i.kind, i.role) for i in items if i.kind is ActivityKind.STANDARDS}
    assert (ActivityKind.STANDARDS, RoleName.BACKEND) in kinds
    assert (ActivityKind.STANDARDS, RoleName.WEB_UI) in kinds


def test_architect_reads_across_domains(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    _, provider, _ = _two_phase_job(store, worktrees_root, seed, repo)
    architect = next(r for r in provider.requests if r.role is RoleName.ARCHITECT)
    pages = {s["page"].split("/")[0] for s in _standards(architect)["retrieved"]}
    assert "architecture" in pages
    assert len(pages) >= 3  # a little of the specialists' domains too
    assert [d for d, _ in domains_for(RoleName.ARCHITECT)][0] == "architecture"
    assert domains_for(RoleName.BACKEND) == [("backend", None)]


# --- the budget --------------------------------------------------------------------------


class _Hit:
    def __init__(self, ident: str, text: str) -> None:
        from slipwright.standards import Chunk
        from slipwright.standards.index import Hit

        chunk = Chunk(
            id=ident,
            scope="global",
            domain="backend",
            page="backend/x.md",
            title="X",
            heading=ident,
            text=text,
        )
        self.hit = Hit(chunk=chunk, score=1.0, keyword=1.0, semantic=0.0)


def _job(request: str = "r") -> Job:
    return Job(id="j", request=request, repo_path=Path("."))


def test_budget_truncates_deterministically() -> None:
    hits = [_Hit(f"s{i}", "word " * (100 * (i + 1))).hit for i in range(4)]  # 125..500 tokens

    def search(query: str, domain: str | None, k: int) -> list[Any]:
        return hits[:k]

    def ids(budget: int) -> list[str]:
        r = retrieve(search, _job(), RoleName.BACKEND, core="core", budget=budget, top_k=4)
        assert r.tokens <= budget
        return r.chunk_ids

    assert estimate_tokens("word " * 100) == 125
    assert ids(10_000) == ["s0", "s1", "s2", "s3"]
    assert ids(400) == ["s0", "s1"]  # s2 (375) does not fit after 375 used
    assert ids(130) == ["s0"]
    assert ids(0) == []
    # a long section is skipped, shorter ones after it still fit
    hits[:] = [hits[3], hits[0], hits[1], hits[2]]
    assert ids(400) == ["s0", "s1"]
    r = retrieve(search, _job(), RoleName.BACKEND, core="core", budget=400, top_k=4)
    assert r.dropped == 2 and "2 more section(s)" in r.detail()
    assert ids(400) == ids(400)  # same inputs, same answer


def test_profile_budget_overrides_the_setting(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    data = seed.model_dump(mode="json")
    data["roles"]["po"]["standards_budget"] = 0  # the PO gets core only
    seed = Profile.model_validate(data)
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    engine.update_standards_settings(token_budget=150)
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    po = next(r for r in provider.requests if r.role is RoleName.PO)
    architect = next(r for r in provider.requests if r.role is RoleName.ARCHITECT)
    assert _standards(po)["retrieved"] == [] and _standards(po)["core"]
    retrieved = _standards(architect)["retrieved"]
    assert sum(estimate_tokens(s["text"]) for s in retrieved) <= 150
    entry = next(t for t in job.history if (t.note or "").startswith("standards (architect)"))
    assert "budget: 150 tokens" in (entry.detail or "") and "exceeded the budget" in (
        entry.detail or ""
    )


def test_query_leads_with_the_phase_and_names_the_task() -> None:
    job = _job("the request")
    job.data.plan = {
        "phases": [{"goal": "first", "files": ["a.py"], "task_id": "t1"}, {"goal": "second"}],
        "breakdown": {
            "epics": [
                {
                    "id": "e1",
                    "title": "E",
                    "stories": [
                        {
                            "id": "s1",
                            "title": "Story one",
                            "tasks": [{"id": "t1", "title": "Task A"}],
                        }
                    ],
                }
            ]
        },
    }
    job.data.phase_index = 0
    assert build_query(job, RoleName.BACKEND) == "first a.py Story one Task A the request"
    job.data.phase_index = 1
    assert build_query(job, RoleName.BACKEND) == "second the request"
    assert build_query(job, RoleName.PO) == "the request"
    assert build_query(job, RoleName.ARCHITECT).startswith("E Story one Task A")
    job.data.test_cases = [{"name": "logs in", "description": "d"}]
    assert build_query(job, RoleName.QA).startswith("logs in first second")


def test_project_core_page_is_appended(tmp_path: Path) -> None:
    override = tmp_path / ".slipwright" / "standards"
    override.mkdir(parents=True)
    (override / "core.md").write_text(
        "---\ndomain: core\n---\n\n# Our rules\n\n## Licences\n\nMIT only.\n", encoding="utf-8"
    )
    text = core_text(GLOBAL_DIR, tmp_path)
    assert text.startswith("# Ortak kurallar") and text.rstrip().endswith("MIT only.")
    assert core_text(tmp_path / "nowhere") == ""


def test_unmatched_query_falls_back_to_the_domain_opening_sections(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.start(engine.create_job("zzqx", repo).id)  # matches nothing anywhere
    po = next(r for r in provider.requests if r.role is RoleName.PO)
    retrieved = _standards(po)["retrieved"]
    assert retrieved and all(s["page"].startswith("product/") for s in retrieved)
    entry = next(t for t in job.history if (t.note or "").startswith("standards (po)"))
    assert "no section matched the query" in (entry.detail or "")
    # page order, so the backlog page opens with its first section
    first = engine.standards_index.browse("product", k=1)[0]
    assert retrieved[0]["id"] == first.chunk.id
