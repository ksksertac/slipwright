"""A development's short name.

The request is the agents' brief and can run to a paragraph; it used to be the label too,
so every table, the dashboard and every chat message showed the paragraph. A development
has a name now: given on the form, stored with the job, shown wherever it is listed --
and derived from the first sentence for whatever arrives without one.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.notify.text import gate_message
from slipwright.providers.scripted import ScriptedProvider, canned
from slipwright.schemas.job import Job, JobState, headline
from slipwright.schemas.profile import Profile, load_profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"

LONG = (
    "android app yapacaz. 3. sınıftan 12. sınıfa, matematik sorular olacak. hepsi çoktan "
    "seçmeli ve geriye doğru 10 sn sayacak. her sorudan 10 puan kazanacak."
)


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE)


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    ws = Workspace(worktrees_root, PortAllocator(start=8400, end=8499))
    provider: ScriptedProvider = canned(seed)
    eng = Engine(store, ws, seed_profile=seed, provider=provider, supervisor_mode="manual")
    eng.handlers.pop(JobState.ARCHITECTURE, None)  # stop after backlog approval
    return eng


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _start(client: TestClient, repo: Path, **body: Any) -> dict[str, Any]:
    resp = client.post("/api/jobs", json={"request": LONG, "repo_path": str(repo), **body})
    assert resp.status_code == 201, resp.text
    job: dict[str, Any] = resp.json()
    return job


def test_a_development_is_listed_by_its_name_and_briefed_by_its_request(
    client: TestClient, repo: Path
) -> None:
    job = _start(client, repo, title="Matematik yarışması")
    project = job["project_id"]

    assert (job["title"], job["request"]) == ("Matematik yarışması", LONG)
    lane = client.get(f"/api/projects/{project}/pipeline").json()["lanes"][0]
    assert lane["title"] == "Matematik yarışması"
    assert lane["request"] == LONG  # still there, unfolded under "What was asked"
    waiting = client.get("/api/overview").json()["waiting"][0]
    assert waiting["title"] == "Matematik yarışması"
    assert {i["job_title"] for i in client.get("/api/activity").json()} == {"Matematik yarışması"}
    costs = client.get(f"/api/projects/{project}/costs").json()
    assert [j["title"] for j in costs["jobs"]] == ["Matematik yarışması"]


def test_a_development_started_without_a_name_is_named_after_its_first_sentence(
    client: TestClient, repo: Path
) -> None:
    """A chat message or the CLI has no name to give; the paragraph is still not a name."""
    assert _start(client, repo)["title"] == "android app yapacaz"


def test_a_first_sentence_too_long_for_a_name_is_cut_at_a_word() -> None:
    name = headline("a " * 30 + "very long opening sentence without any full stop in it at all")
    assert len(name) <= 80 and name.endswith("…") and not name.endswith(" …")


def test_the_branch_is_named_after_the_name_not_the_paragraph(
    client: TestClient, repo: Path
) -> None:
    job = _start(client, repo, title="Quiz app")
    assert "/quiz-app-" in job["data"]["branch_name"]


def test_renaming_changes_the_name_and_nothing_the_agents_or_git_hold(
    client: TestClient, repo: Path
) -> None:
    job = _start(client, repo, title="Quiz app")

    renamed = client.patch(f"/api/jobs/{job['id']}", json={"title": "  Bluetooth quiz  "})

    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Bluetooth quiz"
    assert renamed.json()["request"] == LONG
    assert renamed.json()["data"]["branch_name"] == job["data"]["branch_name"]
    assert client.get(f"/api/jobs/{job['id']}").json()["title"] == "Bluetooth quiz"


def test_a_development_cannot_be_left_without_a_name(client: TestClient, repo: Path) -> None:
    job = _start(client, repo, title="Quiz app")
    assert client.patch(f"/api/jobs/{job['id']}", json={"title": ""}).status_code == 422
    assert client.patch(f"/api/jobs/{job['id']}", json={"title": "   "}).status_code == 400


def test_the_chat_is_told_the_name_not_the_paragraph(tmp_path: Path) -> None:
    job = Job(request=LONG, title="Matematik yarışması", repo_path=tmp_path)
    message = gate_message(job, role=None, project="Süperzeka", link=None, lang="tr")
    assert "“Matematik yarışması”" in message.lines
    assert not any("geriye doğru" in line for line in message.lines)


def test_developments_from_before_names_are_given_one_when_the_database_upgrades(
    tmp_path: Path,
) -> None:
    from alembic import command
    from sqlalchemy import text

    from slipwright.store.db import Database
    from slipwright.store.migrate import _config, migrate
    from slipwright.store.schema import metadata

    db = Database(str(tmp_path / "old.sqlite3"))
    try:
        metadata.create_all(db.engine)
        with db.begin() as conn:
            conn.execute(text("ALTER TABLE jobs DROP COLUMN title"))
            # and what the revisions after it add, since those replay on top
            conn.execute(text("ALTER TABLE job_history DROP COLUMN detail_size"))  # (0014)
            conn.execute(text("DROP TABLE job_messages"))  # (0013)
            for table in ("workers", "worker_codes", "worker_tasks"):  # (0012)
                conn.execute(text(f"DROP TABLE {table}"))
            conn.execute(
                text(
                    "INSERT INTO jobs (id, request, repo_path, state, created_at, updated_at)"
                    " VALUES ('j1', :request, '/r', 'done', '2026-01-01', '2026-01-01')"
                ),
                {"request": LONG},
            )
        command.stamp(_config(db), "0010_attachments")

        migrate(db)

        with db.connect() as conn:
            title = conn.execute(text("SELECT title FROM jobs WHERE id = 'j1'")).scalar()
        assert title == "android app yapacaz"
    finally:
        db.dispose()
