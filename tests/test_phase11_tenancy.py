"""T11 — one installation, many accounts, and nothing leaks between them.

Two people sign up on the same server. Everything one of them creates must be invisible
to the other: the project, its jobs, their history and diffs, the live event stream, and
every cross-project total on the dashboard.

The assertions are deliberately about *absence*. A leak is not a wrong number on a page;
it is somebody else's request text, backlog and code showing up where it should not be.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import PortAllocator, Workspace
from tests.pipeline import full_provider


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return Engine(
        store,
        Workspace(worktrees_root, PortAllocator(start=8800, end=8899)),
        seed_profile=seed,
        provider=full_provider(seed, phases=1),
        supervisor_mode="manual",
    )


@pytest.fixture
def app(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=True)) as c:
        yield c


def _client(app: TestClient, email: str) -> TestClient:
    """A signed-up, verified account with its own cookie jar."""
    person = TestClient(app.app, base_url=str(app.base_url))
    person.post("/api/auth/signup", json={"email": email, "password": "correct horse"})
    store: JobStore = app.app.state.engine.store  # type: ignore[attr-defined]
    user = store.find_by_email(email)
    assert user is not None
    store.mark_email_verified(user.id)
    return person


@pytest.fixture
def ada(app: TestClient) -> TestClient:
    return _client(app, "ada@example.com")


@pytest.fixture
def bob(app: TestClient) -> TestClient:
    return _client(app, "bob@example.com")


def _project(person: TestClient, repo: Path, name: str) -> dict[str, object]:
    made = person.post("/api/projects", json={"name": name, "repo_path": str(repo)})
    assert made.status_code == 201, made.text
    return dict(made.json())


# --- projects and jobs ----------------------------------------------------------------------


def test_a_project_belongs_to_whoever_made_it(ada: TestClient, bob: TestClient, repo: Path) -> None:
    project = _project(ada, repo, "ada's")
    assert project["owner_id"]

    assert [p["id"] for p in ada.get("/api/projects").json()] == [project["id"]]
    assert bob.get("/api/projects").json() == []

    # not forbidden — not found. A 403 would confirm that the id exists.
    assert bob.get(f"/api/projects/{project['id']}").status_code == 404
    assert bob.get(f"/api/projects/{project['id']}/pipeline").status_code == 404
    assert bob.get(f"/api/projects/{project['id']}/board").status_code == 404
    assert bob.delete(f"/api/projects/{project['id']}").status_code == 404
    assert bob.patch(f"/api/projects/{project['id']}", json={"name": "mine now"}).status_code == 404


def test_a_job_and_its_history_are_invisible_to_everybody_else(
    ada: TestClient, bob: TestClient, repo: Path
) -> None:
    project = _project(ada, repo, "ada's")
    made = ada.post(f"/api/projects/{project['id']}/jobs", json={"request": "a secret plan"})
    assert made.status_code == 201, made.text
    job = made.json()

    assert bob.get(f"/api/jobs/{job['id']}").status_code == 404
    assert bob.get(f"/api/jobs/{job['id']}/history/0").status_code == 404
    assert bob.get(f"/api/jobs/{job['id']}/result").status_code == 404
    assert bob.delete(f"/api/jobs/{job['id']}").status_code == 404
    assert bob.post(f"/api/jobs/{job['id']}/message", json={"text": "hello"}).status_code == 404
    assert bob.get("/api/jobs").json() == []

    # nor through the batch endpoints, which take a list of ids from the caller
    refused = bob.post("/api/jobs/approve", json={"job_ids": [job["id"]]})
    assert refused.status_code in (200, 207)
    assert all(not r["ok"] for r in refused.json()["results"])


def test_two_people_may_register_the_same_checkout(
    ada: TestClient, bob: TestClient, repo: Path
) -> None:
    """`find_project_by_repo` used to hand back whichever project had that path."""
    mine = _project(ada, repo, "ada's")
    theirs = _project(bob, repo, "bob's")
    assert mine["id"] != theirs["id"]
    assert mine["owner_id"] != theirs["owner_id"]


# --- the totals on the dashboard ---------------------------------------------------------------


def test_the_cross_project_views_count_only_your_own(
    ada: TestClient, bob: TestClient, repo: Path
) -> None:
    project = _project(ada, repo, "ada's")
    ada.post(f"/api/projects/{project['id']}/jobs", json={"request": "a secret plan"})

    mine = ada.get("/api/overview").json()
    assert mine["jobs_total"] >= 1
    assert mine["projects"] == 1

    theirs = bob.get("/api/overview").json()
    assert theirs["jobs_total"] == 0
    assert theirs["projects"] == 0
    assert theirs["recent"] == []
    assert theirs["waiting"] == []

    assert bob.get("/api/activity").json() == []
    assert [i["job_request"] for i in ada.get("/api/activity").json()]

    # the agent cards count model calls; they are per account too
    assert all(a["invocations"] == 0 for a in bob.get("/api/agents").json())


def test_the_translation_bridge_does_not_carry_another_tenants_prose(
    ada: TestClient, bob: TestClient, repo: Path
) -> None:
    project = _project(ada, repo, "ada's")
    ada.post(f"/api/projects/{project['id']}/jobs", json={"request": "a secret plan"})
    assert bob.get("/api/translations", params={"lang": "en"}).json()["texts"] == {}


# --- the live stream ---------------------------------------------------------------------------


def test_the_bus_delivers_an_event_only_to_its_owner(
    ada: TestClient, bob: TestClient, repo: Path, engine: Engine
) -> None:
    """The filter lives in ``EventBus``, not in the endpoint.

    It is asserted here rather than over the HTTP stream because the stream is endless by
    design -- it waits for the next event forever -- and a test that reads one has to
    guess when to stop. The endpoint does nothing but hand this owner id to ``subscribe``
    and ``since``.
    """
    project = _project(ada, repo, "ada's")
    ada.post(f"/api/projects/{project['id']}/jobs", json={"request": "a secret plan"})
    owners = {
        e.owner_id for _, e in engine.events.since(0) if "a secret plan" in json.dumps(e.payload)
    }
    assert len(owners) == 1, "the request text was published under more than one owner"
    (ada_id,) = owners
    assert ada_id

    # replay: what each reader is allowed to catch up on
    mine = json.dumps([e.model_dump(mode="json") for _, e in engine.events.since(0, ada_id)])
    assert "a secret plan" in mine

    theirs = json.dumps([e.model_dump(mode="json") for _, e in engine.events.since(0, "somebody")])
    assert "a secret plan" not in theirs
    assert str(project["id"]) not in theirs

    # live: an event is never even put on another reader's queue
    with engine.events.subscribe("somebody") as stranger, engine.events.subscribe(ada_id) as owner:
        engine.events.emit(
            "activity", job_id="j", owner_id=ada_id, payload={"title": "another secret"}
        )
        assert owner.get_nowait().payload["title"] == "another secret"
        assert stranger.empty()


def test_an_event_never_says_who_it_belongs_to(engine: Engine) -> None:
    """The owner decides delivery; putting it on the wire would hand out account ids."""
    engine.events.emit("job.state", job_id="j", owner_id="ada", payload={"state": "created"})
    (_, event), = engine.events.since(0)
    assert event.owner_id == "ada"
    assert "ada" not in event.sse(1)
    assert "owner_id" not in json.loads(event.sse(1).split("data: ", 1)[1])
