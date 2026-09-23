"""T11 — what an editor (or any long-lived reader) needs from the stream.

A VS Code window keeps one connection open for hours: it drops, it comes back, and what
happened in between must not be lost. The bus keeps a short history and the endpoint
replays it; every response also names the build that answered, so a client can tell when
the server moved under it.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.events import Event, EventBus
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


def _engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))


def test_the_bus_remembers_the_last_events_with_their_ids() -> None:
    bus = EventBus(history=3)
    for i in range(5):
        bus.emit("activity", project_id="p1", payload={"n": i})

    assert bus.last_id == 5
    # older than the history is gone; what is left keeps its own ids
    assert [i for i, _ in bus.since(0)] == [3, 4, 5]
    assert [e.payload["n"] for _, e in bus.since(3)] == [3, 4]
    assert bus.since(5) == []


def test_a_reader_that_reconnects_is_given_what_it_missed(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        for i in range(3):
            engine.events.emit("activity", project_id="p1", payload={"n": i})

        with client.stream("GET", "/api/events?since=0&limit=3&keepalive_s=0.1") as resp:
            assert resp.status_code == 200
            assert resp.headers["x-accel-buffering"] == "no"  # no proxy may hold this back
            body = "".join(resp.iter_text())
        ids = [line[4:] for line in body.splitlines() if line.startswith("id: ")]
        payloads = [
            json.loads(line[6:])["payload"]["n"]
            for line in body.splitlines()
            if line.startswith("data: ")
        ]
        assert ids == ["1", "2", "3"] and payloads == [0, 1, 2]

        # the header a reader sends when it reconnects says the same thing
        with client.stream(
            "GET", "/api/events?limit=2&keepalive_s=0.1", headers={"Last-Event-ID": "1"}
        ) as resp:
            body = "".join(resp.iter_text())
        assert [
            json.loads(line[6:])["payload"]["n"]
            for line in body.splitlines()
            if line.startswith("data: ")
        ] == [1, 2]


def test_the_replay_respects_the_project_filter(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        engine.events.publish(Event(type="activity", project_id="other", payload={"n": 0}))
        engine.events.publish(Event(type="activity", project_id="mine", payload={"n": 1}))
        with client.stream(
            "GET", "/api/events?since=0&project_id=mine&limit=1&keepalive_s=0.1"
        ) as resp:
            body = "".join(resp.iter_text())
        assert [
            json.loads(line[6:])["payload"]["n"]
            for line in body.splitlines()
            if line.startswith("data: ")
        ] == [1]


def test_every_response_names_the_build(
    store: JobStore, worktrees_root: Path, seed: Profile, tmp_path: Path
) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    engine = _engine(store, worktrees_root, seed)
    app = create_app(engine, resume_on_startup=False, require_auth=False, static_dir=static)
    with TestClient(app) as client:
        version = client.get("/api/version")
        build = version.json()["build"]
        assert version.headers["x-slipwright-version"] == build
        assert client.get("/api/projects").headers["x-slipwright-version"] == build
        assert client.get("/").headers["x-slipwright-version"] == build
