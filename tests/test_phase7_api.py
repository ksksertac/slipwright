from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app, openapi_schema
from slipwright.engine import Engine
from slipwright.events import Event, EventBus
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

ROOT = Path(__file__).resolve().parent.parent
OPENAPI_FILE = ROOT / "schemas" / "openapi.json"

# --- T7.3 API namespace and live events ---------------------------------------------------


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_json_routes_live_under_api_only(client: TestClient, repo: Path) -> None:
    assert client.get("/api/projects").status_code == 200
    assert client.get("/projects").status_code == 404
    assert client.get("/jobs").status_code == 404
    assert client.post("/jobs", json={"request": "x", "repo_path": str(repo)}).status_code == 404
    assert client.get("/api/auth/me").status_code == 200
    paths = openapi_schema()["paths"]
    assert all(p.startswith("/api/") for p in paths), [
        p for p in paths if not p.startswith("/api/")
    ]
    assert "/api/events" in paths


def test_committed_openapi_is_current() -> None:
    committed = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    assert committed == openapi_schema(), (
        "schemas/openapi.json is stale; run `uv run python scripts/export_schema.py`"
    )


def test_event_bus_fan_out_and_isolation() -> None:
    bus = EventBus()
    bus.emit("job.state", job_id="j1", payload={"state": "done"})  # nobody listening: dropped
    with bus.subscribe() as a, bus.subscribe() as b:
        assert bus.subscriber_count == 2
        bus.emit("activity", project_id="p", job_id="j1", payload={"title": "hi"})
        ea, eb = a.get(timeout=1), b.get(timeout=1)
        assert ea == eb and ea.type == "activity" and ea.payload["title"] == "hi"
        assert ea.sse(3).startswith("id: 3\nevent: activity\ndata: {")
        assert json.loads(ea.sse(3).split("data: ", 1)[1].strip())["job_id"] == "j1"
    assert bus.subscriber_count == 0
    assert Event(type="x").payload == {}


def test_store_publishes_on_every_persisted_change(engine: Engine, repo: Path) -> None:
    seen: list[Event] = []
    with engine.events.subscribe() as q:
        job = engine.start(engine.create_job("x", repo).id)
        job = engine.approve(job.id)
        engine.execute_test_run(engine.start_test_run(job.project_id or "").id)
        while not q.empty():
            seen.append(q.get_nowait())
    types = [e.type for e in seen]
    assert types[0] == "project"  # the default project was created
    assert types[1] == "job.state" and seen[1].payload["state"] == "created"
    assert "activity" in types and "job.data" in types
    states = [e.payload["state"] for e in seen if e.type == "job.state"]
    assert states[-1] == "awaiting_plan_approval"
    runs = [e for e in seen if e.type == "test_run.state"]
    assert [r.payload["status"] for r in runs] == ["running", "passed"]
    assert all(e.project_id == job.project_id for e in seen[1:])
    titles = [e.payload["title"] for e in seen if e.type == "activity"]
    assert titles[0] == "job started" and any(t.startswith("planner:") for t in titles)


def _read_events(client: TestClient, url: str, n: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with client.stream("GET", url) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if len(events) >= n:
                    break
    return events


def test_sse_endpoint_streams_store_events(client: TestClient, engine: Engine, repo: Path) -> None:
    project = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
    other = client.post("/api/projects", json={"name": "other", "repo_path": str(repo)}).json()

    def later() -> None:
        time.sleep(0.3)
        engine.store.update_project(engine.store.get_project(other["id"]))  # filtered out
        engine.start(engine.create_job("live", project_id=project["id"]).id, run=False)

    thread = threading.Thread(target=later, daemon=True)
    thread.start()
    events = _read_events(client, f"/api/events?project_id={project['id']}&limit=3", 3)
    thread.join(timeout=5)
    assert [e["type"] for e in events] == ["job.state", "job.state", "activity"]
    assert all(e["project_id"] == project["id"] for e in events)
    assert events[0]["payload"]["state"] == "created"
    assert events[1]["payload"]["state"] == "analyzing"
    assert events[2]["payload"]["title"] == "job started"


def test_sse_keepalive_and_unfiltered(client: TestClient, engine: Engine, repo: Path) -> None:
    def later() -> None:
        time.sleep(0.3)
        engine.create_project(Project(name="late", repo_path=repo))

    thread = threading.Thread(target=later, daemon=True)
    thread.start()
    with client.stream("GET", "/api/events?limit=1&keepalive_s=0.05") as resp:
        lines = []
        for line in resp.iter_lines():
            lines.append(line)
            if line.startswith("data: "):
                break
    thread.join(timeout=5)
    assert ": connected" in lines
    assert ": ping" in lines  # at least one keepalive went out while nothing happened
    assert json.loads(lines[-1][6:])["type"] == "project"


def test_cors_only_in_dev_mode(engine: Engine) -> None:
    headers = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        resp = c.options("/api/projects", headers=headers)
        assert "access-control-allow-origin" not in resp.headers
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False, dev=True)) as c:
        resp = c.options("/api/projects", headers=headers)
        assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
        assert resp.headers["access-control-allow-credentials"] == "true"
        resp = c.options(
            "/api/projects",
            headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in resp.headers


def test_settings_dev_flag() -> None:
    from slipwright.config import Settings

    assert Settings.from_env({}).dev is False
    assert Settings.from_env({"SLIPWRIGHT_DEV": "1"}).dev is True
    assert Settings.from_env({"SLIPWRIGHT_DEV": "off"}).dev is False
