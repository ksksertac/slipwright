"""T11 — what a new account arrives to.

Somebody who has just confirmed their address has no model key yet, so nothing can run.
An empty dashboard would say nothing about what Slipwright does, so they get one finished
development to read: a backlog, a plan with its decisions, phases, test cases, a review
and the whole activity feed.

It is data, not a run. Nothing executes, nothing is cloned, no tokens are spent -- and
nothing in it can be approved or re-run, because there is no checkout behind it.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.demo import DEMO_NAME, seed_demo_project
from slipwright.engine import Engine
from slipwright.mail import read_outbox
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace

BASE = "https://slipwright.example"


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    eng = Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8500, end=8599)),
        seed_profile=seed,
    )
    eng.update_mail_settings(base_url=BASE)
    return eng


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=True)) as c:
        yield c


def _sign_up_and_confirm(client: TestClient, store: JobStore, email: str) -> None:
    client.post("/api/auth/signup", json={"email": email, "password": "correct horse"})
    letters = read_outbox(store, to=email)
    assert letters
    link = next(w for w in letters[0]["body"].split() if w.startswith(BASE))
    token = parse_qs(urlparse(link).query)["token"][0]
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 200


# --- seeding -------------------------------------------------------------------------------


def test_the_example_is_there_the_moment_the_address_is_confirmed(
    client: TestClient, store: JobStore
) -> None:
    # nothing before: an unconfirmed account has no project yet
    client.post("/api/auth/signup", json={"email": "ada@example.com", "password": "correct horse"})
    assert client.get("/api/projects").json() == []

    _sign_up_and_confirm(client, store, "bob@example.com")
    projects = client.get("/api/projects").json()
    assert [p["name"] for p in projects] == [DEMO_NAME]
    assert projects[0]["is_demo"] is True


def test_the_example_is_a_finished_development_with_something_to_read(
    client: TestClient, store: JobStore
) -> None:
    _sign_up_and_confirm(client, store, "ada@example.com")
    project = client.get("/api/projects").json()[0]

    jobs = client.get(f"/api/projects/{project['id']}/jobs").json()
    assert len(jobs) == 1
    job = client.get(f"/api/jobs/{jobs[0]['id']}").json()
    assert job["state"] == JobState.DONE.value

    assert job["data"]["backlog"]["epics"], "a backlog to read"
    assert job["data"]["plan"]["decisions"], "decisions, with the reasons"
    assert len(job["data"]["plan"]["phases"]) == 4
    assert len(job["data"]["test_cases"]) == 4
    assert job["data"]["reviews"], "a standards review"

    # the pipeline and the board are drawn from it, so both pages have content
    lanes = client.get(f"/api/projects/{project['id']}/pipeline").json()["lanes"]
    assert lanes and lanes[0]["steps"]
    board = client.get(f"/api/projects/{project['id']}/board").json()
    assert board["tasks_total"] == 4
    assert len(client.get(f"/api/projects/{project['id']}/activity").json()) > 10


def test_it_is_one_account_s_own(client: TestClient, store: JobStore, engine: Engine) -> None:
    _sign_up_and_confirm(client, store, "ada@example.com")
    ada = store.find_by_email("ada@example.com")
    assert ada is not None
    assert [p.owner_id for p in store.list_projects(ada.id)] == [ada.id]
    assert store.list_projects("somebody-else") == []


def test_seeding_twice_does_not_give_two(store: JobStore) -> None:
    assert seed_demo_project(store, "ada") is not None
    assert seed_demo_project(store, "ada") is None
    assert len(store.list_projects("ada")) == 1


def test_an_installation_can_turn_it_off(
    store: JobStore, worktrees_root: Path, seed: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SLIPWRIGHT_DEMO_PROJECT", "0")
    eng = Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8500, end=8599)),
        seed_profile=seed,
    )
    eng.update_mail_settings(base_url=BASE)
    with TestClient(create_app(eng, resume_on_startup=False, require_auth=True)) as c:
        _sign_up_and_confirm(c, store, "ada@example.com")
        assert c.get("/api/projects").json() == []


# --- read-only ------------------------------------------------------------------------------


def test_nothing_in_the_example_can_be_run(client: TestClient, store: JobStore) -> None:
    """There is no checkout behind it, so anything that would run only fails further in."""
    _sign_up_and_confirm(client, store, "ada@example.com")
    project = client.get("/api/projects").json()[0]
    job_id = client.get(f"/api/projects/{project['id']}/jobs").json()[0]["id"]

    for call in (
        lambda: client.post(f"/api/jobs/{job_id}/approve"),
        lambda: client.post(f"/api/jobs/{job_id}/reject", json={"feedback": "no"}),
        lambda: client.post(f"/api/jobs/{job_id}/rerun", json={"step": "tests"}),
        lambda: client.put(f"/api/jobs/{job_id}/backlog", json={"breakdown": {"epics": []}}),
        lambda: client.post(f"/api/jobs/{job_id}/message", json={"text": "hello"}),
    ):
        answer = call()
        assert answer.status_code == 409, answer.text
        assert "example" in answer.json()["detail"]


def test_it_can_be_deleted_which_is_the_point(client: TestClient, store: JobStore) -> None:
    _sign_up_and_confirm(client, store, "ada@example.com")
    project = client.get("/api/projects").json()[0]
    job_id = client.get(f"/api/projects/{project['id']}/jobs").json()[0]["id"]

    # the job is finished, so the project is not in use and goes cleanly
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert client.get("/api/projects").json() == []
