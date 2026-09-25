from __future__ import annotations

from pathlib import Path

from slipwright.standards import (
    DOMAINS,
    GLOBAL_DIR,
    chunk_corpus,
    chunk_page,
    lint,
    load_corpus,
    load_page,
    parse_front_matter,
    split_sections,
)

# --- T9.2 standards corpus ----------------------------------------------------------------


def test_global_corpus_covers_every_domain_and_lints_clean() -> None:
    pages = load_corpus()
    domains = {p.domain for p in pages}
    assert set(DOMAINS) <= domains, set(DOMAINS) - domains
    assert lint(pages) == []
    chunks = chunk_corpus(pages)
    assert len(chunks) >= 40
    core = [p for p in pages if p.domain == "core"]
    assert len(core) == 1 and core[0].path == GLOBAL_DIR / "core.md"
    # every chunk is self-describing: title and heading travel with the text
    backend = [c for c in chunks if c.domain == "backend"]
    kafka = next(c for c in backend if "Kafka" in c.heading)
    assert kafka.document.startswith("Veri, mesajlaşma ve gözlemlenebilirlik — Kafka tüketicileri")
    assert "dlq" in kafka.text and "backoff" in kafka.text
    assert kafka.page == "backend/data-and-messaging.md" and kafka.scope == "global"
    assert len(kafka.id) == 24


def test_front_matter_and_sections() -> None:
    raw = "---\ndomain: web\ntags: [a, b]\napplies_to: [react]\n---\n"
    raw += "# T\n\nintro\n\n## One\n\nx\n\n## Two\n\ny\n"
    meta, body = parse_front_matter(raw)
    assert meta == {"domain": "web", "tags": ["a", "b"], "applies_to": ["react"]}
    assert split_sections(body) == [("One", "x"), ("Two", "y")]
    assert split_sections("# Only\n\njust intro") == [("", "just intro")]
    assert parse_front_matter("no front matter")[0] == {}


def test_project_overrides_and_lint_problems(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    override = repo / ".slipwright" / "standards" / "backend"
    override.mkdir(parents=True)
    (override / "team.md").write_text(
        "---\ndomain: backend\ntags: [team]\napplies_to: [python]\n---\n# Team rules\n\n"
        "## Kafka tüketicileri ve yeniden denemeler\n\nÜç kez deneriz, sonra DLQ.\n",
        encoding="utf-8",
    )
    pages = load_corpus(project_repo=repo)
    project = [p for p in pages if p.scope == "project"]
    assert len(project) == 1 and project[0].relpath == "backend/team.md"
    chunks = chunk_page(project[0])
    assert chunks[0].scope == "project"
    assert chunks[0].heading == "Kafka tüketicileri ve yeniden denemeler"
    # the same heading in the same domain as a global page is flagged
    problems = lint(pages)
    assert any("duplicates" in p and "team.md" in p for p in problems)

    bad = tmp_path / "bad.md"
    bad.write_text("# No meta\n\n## A\n\n" + "word " * 401, encoding="utf-8")
    page = load_page(bad, scope="global", domain="nope")
    problems = lint([page])
    assert any("missing front-matter" in p for p in problems)
    assert any("unknown domain" in p for p in problems)
    assert any("401 words" in p for p in problems)
    empty = tmp_path / "empty.md"
    empty.write_text("---\ndomain: web\n---\n\nnothing\n", encoding="utf-8")
    problems = lint([load_page(empty)])
    assert any("no '# Title'" in p for p in problems)
