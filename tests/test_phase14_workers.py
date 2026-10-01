"""T14.3: a Mac pairs with one code, builds what the server cannot, and a Mac that goes
away is a wait -- never a failed build."""

from __future__ import annotations

import io
import tarfile
import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright import workers as pairing
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.gates import toolchains
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import PlatformCommands, Profile, RoleName
from slipwright.schemas.worker import TaskResult
from slipwright.store import JobStore
from tests.pipeline import TRUE, full_engine, full_provider

LAN = "http://192.168.1.20:8500"


@pytest.fixture(autouse=True)
def _no_xcode_here(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolchains, "can_build", lambda platform, *a, **k: False)


def _ios_engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    seed = seed.model_copy(
        update={"platforms": [PlatformCommands(platform="ios", build_cmd=TRUE, test_cmd=TRUE)]}
    )
    provider = full_provider(seed, phases=2, domains=["backend", "mobile"])
    provider.replies[RoleName.ARCHITECT]["phases"][1]["platform"] = "ios"
    engine = full_engine(store, worktrees_root, seed, provider)
    engine.worker_poll_s = 0.05
    return engine


@pytest.fixture
def client(store: JobStore, worktrees_root: Path, seed: Profile) -> Iterator[TestClient]:
    engine = _ios_engine(store, worktrees_root, seed)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _engine_of(client: TestClient) -> Engine:
    engine: Engine = client.app.state.engine  # type: ignore[attr-defined]
    return engine


def _pair(client: TestClient, name: str = "mac") -> str:
    code = client.post("/api/workers/code", json={"address": LAN}).json()["code"]
    paired = client.post(
        "/api/worker/pair", json={"code": code, "name": name, "capabilities": ["ios"]}
    )
    assert paired.status_code == 200, paired.text
    return str(paired.json()["token"])


def _drive(engine: Engine, job: Job) -> Job:
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            return job
        job = engine.approve(job.id)
    raise AssertionError(f"still at {job.state}")


class FakeMac:
    """A worker driven through the API, as `slipwright worker` will drive it."""

    def __init__(self, client: TestClient, token: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self.built: list[dict[str, Any]] = []
        self.files: list[list[str]] = []
        self.silent = False  # stops answering, as a Mac put to sleep does
        self.hold_next = False  # takes the next build and never reports it
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> FakeMac:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.silent:
                time.sleep(0.05)
                continue
            got = self.client.post(
                "/api/worker/poll",
                json={"capabilities": ["ios"], "wait_s": 0.1},
                headers=self.headers,
            )
            if got.status_code != 200:
                continue
            task = got.json()
            if self.hold_next:
                self.hold_next = False
                self.silent = True
                continue
            packed = self.client.get(
                f"/api/worker/tasks/{task['id']}/snapshot", headers=self.headers
            ).content
            with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as tar:
                self.files.append(tar.getnames())
            self.built.append(task)
            output = "\n\n".join(
                f"$ {cmd}\nios-built\n[{label}: exit 0]" for label, cmd in task["commands"]
            )
            self.client.post(
                f"/api/worker/tasks/{task['id']}/result",
                json={"exit_code": 0, "output": output, "seconds": 1.5},
                headers=self.headers,
            )


def _until(check: Any, seconds: float = 30) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


# -- the code ---------------------------------------------------------------------------


def test_a_code_carries_the_address_and_a_secret_and_catches_a_bad_copy() -> None:
    secret = pairing.new_secret()
    code = pairing.pack(LAN, secret)
    assert code.startswith("SW-") and len(code) < 45  # short enough to read off a screen
    assert pairing.unpack(code) == (LAN, secret)
    assert pairing.unpack(code.lower().replace("0", "o")) == (LAN, secret)  # look-alikes
    assert pairing.unpack(pairing.pack("https://sw.example.com", secret))[0] == (
        "https://sw.example.com"
    )
    broken = code[:-1] + ("2" if code[-1] != "2" else "3")
    with pytest.raises(pairing.CodeError, match="does not add up"):
        pairing.unpack(broken)
    with pytest.raises(pairing.CodeError, match="start with SW-"):
        pairing.unpack("hello")


def test_a_code_made_at_localhost_carries_only_the_port() -> None:
    assert pairing.choose_address(None, "http://localhost:8500", LAN) == LAN
    assert pairing.choose_address("https://sw.example.com/", LAN) == "https://sw.example.com"
    nearby = pairing.choose_address(None, "http://127.0.0.1:8500")
    assert nearby == "http://localhost:8500"
    secret = pairing.new_secret()
    code = pairing.pack(nearby, secret)
    assert len(code) < len(pairing.pack(LAN, secret))  # shorter still than a LAN one
    assert pairing.unpack(code) == ("http://localhost:8500", secret)


# -- pairing ------------------------------------------------------------------------------


def test_a_mac_pairs_once_with_a_code_and_is_listed(client: TestClient) -> None:
    made = client.post("/api/workers/code", json={"address": LAN}).json()
    assert (
        made["address"] == LAN and made["command"] == f"slipwright worker --connect {made['code']}"
    )
    first = client.post("/api/worker/pair", json={"code": made["code"], "name": "Ada's Mac"})
    assert first.status_code == 200 and first.json()["token"].startswith("swk_")
    again = client.post("/api/worker/pair", json={"code": made["code"], "name": "another"})
    assert again.status_code == 403  # spent

    listed = client.get("/api/workers").json()
    assert [(w["name"], w["online"]) for w in listed] == [("Ada's Mac", True)]


def test_a_mac_paired_under_its_ip_address_is_renamed_by_its_next_poll(
    client: TestClient,
) -> None:
    token = _pair(client, name="192.168.1.11")
    mac = {"Authorization": f"Bearer {token}"}
    polled = client.post(
        "/api/worker/poll", json={"wait_s": 0, "name": "Ada's MacBook Pro"}, headers=mac
    )
    assert polled.status_code == 204
    assert [w["name"] for w in client.get("/api/workers").json()] == ["Ada's MacBook Pro"]
    # a worker from before the name was sent keeps the one it has
    client.post("/api/worker/poll", json={"wait_s": 0}, headers=mac)
    assert [w["name"] for w in client.get("/api/workers").json()] == ["Ada's MacBook Pro"]


def test_a_page_open_at_localhost_gets_a_code_without_being_asked_anything(
    client: TestClient,
) -> None:
    made = client.post("/api/workers/code", json={"address": "http://localhost:8500"})
    assert made.status_code == 200 and made.json()["address"] == "http://localhost:8500"
    # a page once open at an address another machine can reach is remembered for the next
    client.post("/api/workers/code", json={"address": LAN})
    again = client.post("/api/workers/code", json={"address": "http://localhost:8500"})
    assert again.status_code == 200 and again.json()["address"] == LAN


def test_the_worker_door_wants_a_worker_token(client: TestClient) -> None:
    assert client.post("/api/worker/poll", json={}).status_code == 401
    wrong = {"Authorization": "Bearer swk_not-a-real-one"}
    assert client.post("/api/worker/poll", json={}, headers=wrong).status_code == 401
    token = _pair(client)
    ok = client.post(
        "/api/worker/poll", json={"wait_s": 0}, headers={"Authorization": f"Bearer {token}"}
    )
    assert ok.status_code == 204


def test_a_removed_mac_is_refused_at_its_next_poll(client: TestClient) -> None:
    token = _pair(client)
    worker_id = client.get("/api/workers").json()[0]["id"]
    assert client.delete(f"/api/workers/{worker_id}").status_code == 204
    polled = client.post(
        "/api/worker/poll", json={"wait_s": 0}, headers={"Authorization": f"Bearer {token}"}
    )
    assert polled.status_code == 401
    assert client.get("/api/workers").json() == []


def test_a_build_goes_only_to_its_own_accounts_mac(store: JobStore) -> None:
    store.enqueue_worker_task("ada", "job-1", "ios", [("ios build", "b")], 60, b"tar")
    assert store.claim_worker_task("grace", "w-grace", ["ios"]) is None
    assert store.claim_worker_task("ada", "w-ada", ["android"]) is None
    claimed = store.claim_worker_task("ada", "w-ada", ["ios"])
    assert claimed is not None and claimed.job_id == "job-1"
    assert store.worker_task_snapshot(claimed.id, "w-grace") is None
    assert not store.finish_worker_task(
        claimed.id, "w-grace", TaskResult(exit_code=0, output="", seconds=0)
    )


# -- building on the Mac ----------------------------------------------------------------


def test_the_ios_phase_is_built_on_the_mac(client: TestClient, repo: Path) -> None:
    engine = _engine_of(client)
    with FakeMac(client, _pair(client)) as mac:
        job = _drive(engine, engine.start(engine.create_job("an api and an app", repo).id))

    assert job.state is JobState.DONE
    assert [t["platform"] for t in mac.built] == ["ios", "ios"]  # the phase, then QA's gate
    assert mac.built[0]["commands"][0][0] == "ios build"
    assert "OK" in mac.files[0]  # the worktree as the gate would see it
    passed = next(
        t.detail or "" for t in job.history if t.note == "build gate passed for phase 2/2"
    )
    assert "ios-built" in passed
    assert job.data.build_attempts == 0


def test_a_mac_that_goes_away_is_a_wait_and_the_build_is_owed_not_the_phase(
    client: TestClient, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pairing, "LIVE", timedelta(seconds=0.4))
    engine = _engine_of(client)
    with FakeMac(client, _pair(client)) as mac:
        mac.hold_next = True  # takes the iOS build, then falls asleep
        job = _drive(engine, engine.start(engine.create_job("an api and an app", repo).id))

        assert job.state is JobState.AWAITING_BUILDER
        assert job.data.builder_resume == "build_gate"
        assert job.data.build_attempts == 0  # a Mac asleep is not a red build
        mobile_calls = len([r for r in engine.provider.requests if r.role is RoleName.MOBILE_UI])

        mac.silent = False  # it wakes, polls, and that carries the development on
        _until(lambda: engine.store.get(job.id).state is not JobState.AWAITING_BUILDER)
        _until(lambda: engine.store.get(job.id).state in APPROVAL_STATES | {JobState.DONE})
        job = _drive(engine, engine.store.get(job.id))

    assert job.state is JobState.DONE
    # the phase was not written again: only its build was owed
    assert (
        len([r for r in engine.provider.requests if r.role is RoleName.MOBILE_UI]) == mobile_calls
    )


def test_a_database_from_before_workers_upgrades_into_one(tmp_path: Path) -> None:
    """The shape taken apart, as the attachments' test does it: drop what 0012 adds, stamp
    the revision before it, and let the store upgrade itself the way a server does."""
    from alembic import command
    from sqlalchemy import inspect, text

    from slipwright.store.db import Database
    from slipwright.store.migrate import _config, migrate
    from slipwright.store.schema import metadata

    db = Database(str(tmp_path / "old.sqlite3"))
    try:
        metadata.create_all(db.engine)
        with db.begin() as conn:
            for table in ("workers", "worker_codes", "worker_tasks"):
                conn.execute(text(f"DROP TABLE {table}"))
        command.stamp(_config(db), "0011_job_title")

        migrate(db)

        tables = set(inspect(db.engine).get_table_names())
        assert {"workers", "worker_codes", "worker_tasks"} <= tables
        columns = {c["name"] for c in inspect(db.engine).get_columns("worker_tasks")}
        assert {"snapshot", "commands_json", "tries", "state"} <= columns
    finally:
        db.dispose()
