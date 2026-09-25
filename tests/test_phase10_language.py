"""T10 — the platform's language and the project's need not be the same.

The agents write in the project's language; the page is read in whichever language the
TR/EN switch is on. When the two differ, every string an agent wrote is also kept in the
other one, translated once and cached by the source text.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from slipwright.translate import prose_in_note, strings_of
from tests.pipeline import full_engine, full_provider


def _client(engine: object) -> TestClient:
    """The lifespan puts the engine on ``app.state``, so the client is a context manager."""
    return TestClient(create_app(engine, resume_on_startup=False, require_auth=False))  # type: ignore[arg-type]


def _run_to_backlog_gate(store: JobStore, repo: Path, worktrees_root: Path, seed: Profile):
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo, language="en"))
    job = engine.create_job("add a health endpoint", project_id=project.id)
    engine.start(job.id)
    return engine, project, store.get(job.id)


# --- what is worth translating ----------------------------------------------------------


def test_strings_of_takes_the_agents_prose_and_leaves_the_humans_words_alone(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _project, job = _run_to_backlog_gate(store, repo, worktrees_root, seed)
    texts = strings_of(job)
    assert "As a user I get the request" in texts  # a story the Product Owner wrote
    assert "Request" in texts  # its epic
    # the request is what the person typed: it is shown as they wrote it, never paraphrased
    assert job.request not in texts
    # and nothing that is not prose
    assert all(any(c.isalpha() for c in t) for t in texts)


def test_prose_in_note_lifts_only_what_an_agent_wrote() -> None:
    assert (
        prose_in_note("backend phase 1/7: Scaffolded the app. (3 files)")
        == "Scaffolded the app."
    )
    assert (
        prose_in_note("backend phase 1/7, fix attempt 2: Fixed it. (1 files)") == "Fixed it."
    )
    assert prose_in_note("qa: tests written and green (6 files) — Covered CRUD.") == "Covered CRUD."
    assert prose_in_note("supervisor: fix (a missing import)") == "a missing import"
    # the engine's own sentences carry no prose at all
    assert prose_in_note("build gate passed for phase 3/7") is None
    assert prose_in_note("jira (devops): 4 done") is None
    assert prose_in_note("review phase 2/7: clean") is None


# --- the bridge ---------------------------------------------------------------------------


def test_the_other_language_is_translated_once_and_then_cached(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, project, job = _run_to_backlog_gate(store, repo, worktrees_root, seed)
    calls = len(engine.provider.requests)  # type: ignore[attr-defined]

    texts = engine.translations("tr", project_id=project.id)
    assert texts, "an English project read in Turkish needs a bridge"
    assert all(v.startswith("[translated] ") for v in texts.values())
    assert texts["Request"] == "[translated] Request"
    asked = len(engine.provider.requests) - calls  # type: ignore[attr-defined]
    assert asked >= 1

    # asked again, nothing is sent: the cache is keyed by the source text
    again = engine.translations("tr", project_id=project.id)
    assert again == texts
    assert len(engine.provider.requests) - calls == asked  # type: ignore[attr-defined]


def test_a_project_read_in_its_own_language_needs_no_bridge(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, project, _job = _run_to_backlog_gate(store, repo, worktrees_root, seed)
    calls = len(engine.provider.requests)  # type: ignore[attr-defined]
    assert engine.translations("en", project_id=project.id) == {}
    assert len(engine.provider.requests) == calls  # type: ignore[attr-defined]


def test_a_provider_that_cannot_translate_is_not_an_error(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, project, _job = _run_to_backlog_gate(store, repo, worktrees_root, seed)

    class Broken:
        def complete(self, request: object) -> object:
            raise RuntimeError("no model today")

    engine._provider = Broken()  # type: ignore[assignment]
    assert engine.translations("tr", project_id=project.id) == {}


def test_the_endpoint_serves_the_bridge_for_a_project_and_for_everything(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, project, _job = _run_to_backlog_gate(store, repo, worktrees_root, seed)
    with _client(engine) as client:
        r = client.get(f"/api/projects/{project.id}/translations", params={"lang": "tr"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["lang"] == "tr"
        assert body["texts"]["Request"] == "[translated] Request"

        assert client.get("/api/translations", params={"lang": "tr"}).json()["texts"]
        assert client.get("/api/translations", params={"lang": "en"}).json()["texts"] == {}
        # a language the platform does not speak is refused, not guessed at
        assert client.get("/api/translations", params={"lang": "de"}).status_code == 422


def test_the_job_state_is_untouched_by_reading_it_in_another_language(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, project, job = _run_to_backlog_gate(store, repo, worktrees_root, seed)
    before = store.get(job.id).model_dump(mode="json")
    engine.translations("tr", project_id=project.id)
    assert store.get(job.id).model_dump(mode="json") == before
    assert store.get(job.id).state is JobState.AWAITING_BACKLOG_APPROVAL


# --- the web ------------------------------------------------------------------------------


def test_the_web_reads_the_bridge() -> None:
    web = Path(__file__).resolve().parent.parent / "web" / "src"
    said = (web / "i18n" / "said.tsx").read_text(encoding="utf-8")
    assert "useTranslations" in said and "useSay" in said
    hooks = (web / "api" / "hooks.ts").read_text(encoding="utf-8")
    assert "/translations" in hooks
    notes = (web / "i18n" / "notes.ts").read_text(encoding="utf-8")
    assert "prose" in notes  # the agent's own words inside an engine note
    # the pages that show agent prose reach for it
    for page in ("pages/ProjectPage.tsx", "pages/JobPage.tsx", "components/Breakdown.tsx"):
        assert "useSay" in (web / page).read_text(encoding="utf-8"), page


def test_the_language_is_chosen_before_there_is_an_account_to_remember_it_against() -> None:
    web = Path(__file__).resolve().parent.parent / "web" / "src"
    # nobody has chosen on a first visit, so the browser answers for them
    i18n = (web / "i18n.tsx").read_text(encoding="utf-8")
    assert "navigator.languages" in i18n
    # and every page carries the switch that corrects the guess -- including the ones
    # before sign-in, which is where the guess is all there is
    for page in ("pages/LoginPage.tsx", "pages/AccountPages.tsx", "components/Layout.tsx"):
        assert "LangPicker" in (web / page).read_text(encoding="utf-8"), page
