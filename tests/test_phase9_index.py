from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright import cli
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.standards import load_corpus
from slipwright.standards.index import (
    HashingEmbedder,
    NoEmbedder,
    OpenAIEmbedder,
    StandardsIndex,
    StandardsIndexError,
    corpus_fingerprint,
)
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

FM = "---\ndomain: {domain}\ntags: [x]\napplies_to: [all]\n---\n"


def _page(domain: str, title: str, sections: dict[str, str]) -> str:
    body = "".join(f"\n## {h}\n\n{t}\n" for h, t in sections.items())
    return FM.format(domain=domain) + f"# {title}\n" + body


# --- T9.3 standards index (RAG) -----------------------------------------------------------


def _index(tmp_path: Path, embedder: object | None = None) -> StandardsIndex:
    return StandardsIndex(tmp_path / "standards.sqlite3", embedder)  # type: ignore[arg-type]


def test_keyword_search_finds_the_retry_section(tmp_path: Path) -> None:
    index = _index(tmp_path)
    result = index.reindex(load_corpus())
    assert result["added"] > 40 and result["removed"] == 0
    hits = index.search("Kafka tüketicisi yaz, yeniden deneme ve dead letter", "backend", k=3)
    assert hits and "Kafka tüketicileri ve yeniden denemeler" in hits[0].chunk.heading
    assert hits[0].chunk.domain == "backend" and hits[0].semantic == 0.0
    # domain filter: a web query never returns backend chunks
    for hit in index.search("formların ve düğmelerin erişilebilirliği", "web"):
        assert hit.chunk.domain == "web"
    assert index.search("çevrimdışı senkron", "mobile", k=2)[0].chunk.domain == "mobile"
    assert index.search("   ", "backend") == []
    assert index.search("zzzz qqqq", "backend") == []  # nothing matches: no hits, no crash
    everything = index.search("yeniden deneme backoff", "*", k=6)
    assert {h.chunk.domain for h in everything} >= {"backend"}
    stats = index.stats()
    assert stats["embedder"] == "none" and stats["embedded"] == 0
    assert stats["per_domain"]["backend"] > 5


def test_hybrid_search_with_embeddings_and_incremental_reindex(tmp_path: Path) -> None:
    index = _index(tmp_path, HashingEmbedder(dim=128))
    pages = load_corpus()
    first = index.reindex(pages)
    assert first["added"] == first["total"]
    assert index.stats()["embedded"] == first["total"]
    hits = index.search("mesaj tüketicileri için yeniden deneme politikası", "backend", k=2)
    assert hits[0].semantic > 0 and hits[0].keyword > 0
    assert "Kafka" in hits[0].chunk.heading
    # nothing changed: nothing re-embedded
    again = index.reindex(pages)
    assert (again["added"], again["removed"]) == (0, 0)
    # switching the embedder re-embeds everything once
    index.embedder = NoEmbedder()
    switched = index.reindex(pages)
    assert switched["added"] == first["total"]
    assert index.stats()["embedded"] == 0


def test_editing_a_page_replaces_only_its_chunks(tmp_path: Path) -> None:
    corpus = tmp_path / "standards"
    (corpus / "backend").mkdir(parents=True)
    a = corpus / "backend" / "a.md"
    b = corpus / "backend" / "b.md"
    a.write_text(_page("backend", "A", {"Alpha": "alpha text", "Beta": "beta text"}), "utf-8")
    b.write_text(_page("backend", "B", {"Gamma": "gamma text"}), "utf-8")
    index = _index(tmp_path)
    assert index.reindex(load_corpus(corpus))["total"] == 3
    a.write_text(_page("backend", "A", {"Alpha": "alpha text changed"}), "utf-8")
    result = index.reindex(load_corpus(corpus))
    assert (result["added"], result["removed"], result["total"]) == (1, 2, 2)
    assert [h.chunk.heading for h in index.search("gamma", "backend")] == ["Gamma"]
    assert index.search("alpha", "backend")[0].chunk.text == "alpha text changed"
    assert index.search("beta", "backend") == []


def test_project_overrides_outrank_global_and_are_scoped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    override = repo / ".slipwright" / "standards" / "backend"
    override.mkdir(parents=True)
    (override / "team.md").write_text(
        "---\ndomain: backend\ntags: [kafka]\napplies_to: [python]\n---\n# Team\n\n"
        "## Our Kafka retry policy\n\nKafka consumers retry three times then dead-letter.\n",
        encoding="utf-8",
    )
    index = _index(tmp_path)
    index.reindex(load_corpus())
    project_pages = [p for p in load_corpus(project_repo=repo) if p.scope == "project"]
    index.reindex(project_pages, project_id="p1")
    hits = index.search("Kafka retry dead letter", "backend", k=3, project_id="p1")
    assert hits[0].chunk.scope == "project" and hits[0].chunk.page == "backend/team.md"
    other = index.search("Kafka retry dead letter", "backend", k=3, project_id="p2")
    assert all(h.chunk.scope == "global" for h in other)
    assert all(h.chunk.scope == "global" for h in index.search("Kafka retry", "backend"))


def test_openai_embedder_batches_and_reports_errors() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if body["model"] == "broken":
            return httpx.Response(400, json={"error": {"message": "no such model"}})
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [1.0, float(i)]} for i in range(len(body["input"]))
                ]
            },
        )

    embedder = OpenAIEmbedder(
        "sk", "https://api.example.test/v1", "emb-model", transport=httpx.MockTransport(handler)
    )
    vectors = embedder.embed([f"t{i}" for i in range(70)])
    assert len(vectors) == 70 and vectors[65] == [1.0, 1.0]
    assert [len(c["input"]) for c in calls] == [64, 6]  # type: ignore[arg-type]
    assert embedder.embed([]) == []
    with pytest.raises(StandardsIndexError, match="400"):
        OpenAIEmbedder(
            "sk", "https://api.example.test/v1", "broken", transport=httpx.MockTransport(handler)
        ).embed(["x"])


def test_fingerprint_changes_with_files(tmp_path: Path) -> None:
    f = tmp_path / "a.md"
    f.write_text("x", encoding="utf-8")
    before = corpus_fingerprint([f])
    f.write_text("xy", encoding="utf-8")
    assert corpus_fingerprint([f]) != before
    assert corpus_fingerprint([]) == corpus_fingerprint([])


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


def test_engine_indexes_on_demand_and_by_fingerprint(
    engine: Engine, repo: Path, tmp_path: Path
) -> None:
    first = engine.reindex_standards()
    assert first["skipped"] is False and first["total"] > 40
    assert engine.reindex_standards()["skipped"] is True  # unchanged corpus
    assert engine.reindex_standards(force=True)["skipped"] is False
    project = engine.create_project(Project(name="demo", repo_path=repo))
    assert engine.reindex_standards(project.id)["total"] == 0  # no overrides yet
    override = repo / ".slipwright" / "standards" / "web"
    override.mkdir(parents=True)
    (override / "house.md").write_text(
        _page("web", "House style", {"Buttons": "All buttons are rounded 8px."}), "utf-8"
    )
    hits = engine.search_standards("rounded buttons", "web", project_id=project.id, k=2)
    assert hits[0].chunk.scope == "project" and hits[0].chunk.heading == "Buttons"
    settings = engine.update_standards_settings(embedder="hashing", top_k=2)
    assert settings["embedder"] == "hashing"
    hits = engine.search_standards("rounded buttons", "web", project_id=project.id)
    assert len(hits) == 2 and hits[0].semantic > 0
    engine.update_standards_settings(embedder="openai")
    with pytest.raises(StandardsIndexError, match="OpenAI key"):
        engine.reindex_standards(force=True)
    engine.update_standards_settings(embedder="none")


def test_standards_settings_endpoints(engine: Engine, repo: Path) -> None:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        status = client.get("/api/settings/standards").json()
        assert status["settings"]["embedder"] == "none" and status["chunks"] > 40
        assert status["per_domain"]["backend"] > 5
        assert client.put("/api/settings/standards", json={"embedder": "bogus"}).status_code == 400
        assert (
            client.put("/api/settings/standards", json={"embedder": "hashing", "top_k": 3}).json()[
                "top_k"
            ]
            == 3
        )
        hits = client.get("/api/settings/standards/search?q=kafka%20retry&domain=backend").json()
        assert hits and "Kafka" in hits[0]["heading"] and hits[0]["semantic"] > 0
        assert client.post("/api/settings/standards/reindex").json()["embedded"] > 40


def test_cli_standards_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SLIPWRIGHT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SLIPWRIGHT_PROVIDER", "scripted")
    assert cli.main(["standards", "reindex"]) == 0
    assert "global:" in capsys.readouterr().out
    assert cli.main(["standards", "search", "kafka retry", "--domain", "backend", "-k", "2"]) == 0
    out = capsys.readouterr().out
    assert "Kafka" in out and "[backend]" in out
