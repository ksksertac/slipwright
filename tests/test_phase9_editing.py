"""T9.6 — editing the standards from the UI: pages, linting, reindex, the review branch."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.activity import project_progress
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.standards import GLOBAL_DIR, PROJECT_SUBDIR
from slipwright.standards.editing import BRANCH, PageError, StandardsEditor, check_path
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

WEB = Path(__file__).resolve().parent.parent / "web"

PAGE = """---
domain: backend
tags: [queues]
applies_to: [backend]
---

# Queues

## Dead letters

Every consumer has a dead-letter topic named `<topic>.dlq`; poison messages go there
with the original headers and the error, never dropped.
"""


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """A private copy of the global corpus inside its own git repository."""
    root = tmp_path / "corpus-repo"
    (root / "standards").mkdir(parents=True)
    shutil.copytree(GLOBAL_DIR, root / "standards", dirs_exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    return root / "standards"


def _engine(store: JobStore, worktrees_root: Path, seed: Profile, corpus: Path) -> Engine:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    engine.standards_dir = corpus
    return engine


def test_paths_are_checked() -> None:
    assert check_path("backend/services-and-apis.md") == "backend/services-and-apis.md"
    assert check_path("core.md") == "core.md"
    for bad in ("../x.md", "backend/../core.md", "nope/x.md", "backend/x.txt", "/etc/passwd"):
        with pytest.raises(PageError):
            check_path(bad)


def test_editor_lists_reads_writes_and_commits_on_the_review_branch(
    corpus: Path, tmp_path: Path
) -> None:
    editor = StandardsEditor(corpus, tmp_path / "branches")
    pages = editor.list_pages(None, "backend")
    assert {p.domain for p in pages} == {"backend", "core"}  # core rides along
    assert all(p.sections > 0 and p.words > 0 for p in pages)
    assert "# Core rules" in editor.read("core.md", None)

    info = editor.create("backend", "Queues", PAGE, None, author="ada")
    assert info.path == "backend/queues.md" and info.title == "Queues" and info.sections == 1
    assert (corpus / "backend" / "queues.md").read_text(encoding="utf-8") == PAGE
    repo = corpus.parent
    assert BRANCH in _git(repo, "branch", "--list", BRANCH)
    assert "standards: update backend/queues.md (by ada)" in _git(repo, "log", "-1", BRANCH)
    assert _git(repo, "show", f"{BRANCH}:standards/backend/queues.md") == PAGE
    assert "main" in _git(repo, "branch", "--show-current")  # the checkout stayed on main
    assert "queues.md" in _git(repo, "status", "--short")  # visible where the agents read

    # a second save is another commit; a duplicate title is refused
    editor.write(
        "backend/queues.md",
        PAGE.replace("Dead letters", "Dead letters and DLQ"),
        None,
        author="ada",
    )
    assert _git(repo, "rev-list", "--count", BRANCH).strip() == "3"  # base + 2
    with pytest.raises(PageError, match="already exists"):
        editor.create("backend", "Queues", "", None, author="ada")

    editor.delete("backend/queues.md", None, author="ada")
    assert not (corpus / "backend" / "queues.md").exists()
    assert "remove backend/queues.md" in _git(repo, "log", "-1", BRANCH)
    with pytest.raises(PageError):
        editor.delete("core.md", None, author="ada")


def test_linter_refuses_bad_pages(corpus: Path, tmp_path: Path) -> None:
    editor = StandardsEditor(corpus, tmp_path / "branches")
    with pytest.raises(PageError, match="front-matter"):
        editor.write("backend/x.md", "# No front matter\n\n## A\n\ntext\n", None, author="a")
    with pytest.raises(PageError, match="unknown domain"):
        editor.write(
            "backend/x.md",
            "---\ndomain: nope\n---\n\n# Title\n\n## A\n\ntext\n",
            None,
            author="a",
        )
    with pytest.raises(PageError, match="words"):
        editor.write(
            "backend/x.md",
            "---\ndomain: backend\n---\n\n# Long\n\n## A\n\n" + "word " * 401 + "\n",
            None,
            author="a",
        )
    with pytest.raises(PageError, match="duplicates"):
        editor.write(
            "backend/x.md",
            "---\ndomain: backend\n---\n\n# Dup\n\n## Idempotency and retries\n\ncopy\n",
            None,
            author="a",
        )
    assert not (corpus / "backend" / "x.md").exists()
    # a page without git around it still saves, just without a review branch
    loose = tmp_path / "loose"
    loose.mkdir()
    StandardsEditor(loose, tmp_path / "b2").create("web", "Forms", "", None, author="a")
    assert (loose / "web" / "forms.md").is_file()


def test_edited_page_changes_what_the_next_invocation_retrieves(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path, corpus: Path
) -> None:
    engine = _engine(store, worktrees_root, seed, corpus)
    provider = engine.provider
    before = engine.search_standards("dead letter topic poison messages", "backend")
    assert not any("Dead letters" in h.chunk.heading for h in before)

    engine.standards_editor.create("backend", "Queues", PAGE, None, author="ada")
    engine.ensure_standards_indexed()
    after = engine.search_standards("dead letter topic poison messages", "backend")
    assert after and "Dead letters" in after[0].chunk.heading

    # and the agent sees it: a backend phase about dead letters pulls the new section
    from tests.pipeline import set_plan

    set_plan(
        provider,  # type: ignore[arg-type]
        seed,
        [
            {
                "goal": "route poison messages to the dead letter topic",
                "files": ["OK"],
                "domain": "backend",
            }
        ],
    )
    job = engine.start(engine.create_job("dlq", repo).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    backend = next(r for r in provider.requests if r.role.value == "backend")  # type: ignore[attr-defined]
    assert "Dead letters" in backend.prompt


def test_project_overrides_live_in_the_project_repo(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path, corpus: Path
) -> None:
    engine = _engine(store, worktrees_root, seed, corpus)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        assert client.get(f"/api/standards/pages?project_id={project.id}").json() == []
        resp = client.post(
            "/api/standards/pages",
            json={"domain": "backend", "title": "Queues", "text": PAGE, "project_id": project.id},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["scope"] == "project" and resp.json()["path"] == "backend/queues.md"
        assert (repo / PROJECT_SUBDIR / "backend" / "queues.md").is_file()
        assert BRANCH in _git(repo, "branch", "--list", BRANCH)
        listed = client.get(f"/api/standards/pages?project_id={project.id}&domain=backend").json()
        assert [p["path"] for p in listed] == ["backend/queues.md"]
        hits = client.get(
            f"/api/settings/standards/search?q=poison+dead+letter&domain=backend&project_id={project.id}"
        ).json()
        assert hits and hits[0]["scope"] == "project"
        assert client.get("/api/standards/pages?project_id=nope").status_code == 404


def test_pages_api(store: JobStore, worktrees_root: Path, seed: Profile, corpus: Path) -> None:
    engine = _engine(store, worktrees_root, seed, corpus)
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        pages = client.get("/api/standards/pages?domain=web").json()
        assert {p["domain"] for p in pages} == {"web", "core"}
        page = client.get("/api/standards/pages/web/frontend.md").json()
        assert page["text"].startswith("---") and page["title"] and page["sections"] > 0
        assert client.get("/api/standards/pages/web/nope.md").status_code == 404
        assert client.get("/api/standards/pages/etc/passwd").status_code == 400

        text = (
            page["text"]
            + "\n## Empty states\n\nEvery list has an empty state that says what to do next.\n"
        )
        resp = client.put("/api/standards/pages/web/frontend.md", json={"text": text})
        assert resp.status_code == 200 and resp.json()["sections"] == page["sections"] + 1
        bad = client.put(
            "/api/standards/pages/web/frontend.md", json={"text": "# no front matter\n"}
        )
        assert bad.status_code == 422 and "front-matter" in bad.json()["detail"]
        hits = client.get("/api/settings/standards/search?q=empty+state+list&domain=web").json()
        assert "Empty states" in hits[0]["heading"]

        created = client.post("/api/standards/pages", json={"domain": "web", "title": "Charts"})
        assert created.status_code == 201 and created.json()["path"] == "web/charts.md"
        assert client.delete("/api/standards/pages/web/charts.md").status_code == 204
        assert client.delete("/api/standards/pages/web/charts.md").status_code == 404
        assert client.delete("/api/standards/pages/core.md").status_code == 400


def test_review_health_on_the_project_progress(seed: Profile, repo: Path) -> None:
    from slipwright.schemas.job import Job

    job = Job(id="j", request="x", repo_path=repo, project_id="p")
    job.data.reviews = [
        {"phase": 1, "round": 0, "blocking": 1, "advisory": 2, "violations": [], "verdict": ""},
        {"phase": 2, "round": 0, "blocking": 0, "advisory": 1, "violations": [], "verdict": ""},
    ]
    progress = project_progress("p", [job])
    assert (progress.reviews, progress.review_blocking, progress.review_advisory) == (2, 1, 3)


def test_standards_ui_sources() -> None:
    text = {p.name: p.read_text(encoding="utf-8") for p in (WEB / "src").rglob("*.tsx")}
    tab = text["AgentStandardsTab.tsx"]
    for expected in (
        "useStandardsPages",
        "New page",
        "Markdown",
        "preview",
        "core.md",
        "Try a search",
        "Reindex now",
        "embedder",
        "Scope",
        "ConfirmModal",
    ):
        assert expected in tab, expected
    assert "review_blocking" in text["ProjectPage.tsx"]
    hooks = (WEB / "src" / "api" / "hooks.ts").read_text(encoding="utf-8")
    assert "/api/standards/pages" in hooks and "/api/settings/standards" in hooks
