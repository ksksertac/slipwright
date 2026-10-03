"""The build room: a development's phases drawn as they are written and built, the machines
writing them on one side and the branch filling up on the other -- and a machine saying
what it is, so its card can tell the EC2 box from the laptop."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.building import build_room
from slipwright.engine import Engine
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.test_phase17_machines import Machine, _client, _engine, _pair, _run

PLAN = {
    "phases": [
        {"goal": "the booking API", "domain": "backend", "depends_on": []},
        {"goal": "the sign-in screens", "domain": "web", "depends_on": [1]},
        {"goal": "the notification service", "domain": "backend", "depends_on": [1]},
    ]
}


@pytest.fixture
def lent(store: JobStore, worktrees_root: Path, seed: Profile) -> Iterator[TestClient]:
    yield from _client(_engine(store, worktrees_root, seed, server=False))


def _job(engine: Engine, repo: Path, **data: Any) -> Job:
    job = engine.create_job("a booking app", repo_path=repo)
    job.data.plan = PLAN
    for key, value in data.items():
        setattr(job.data, key, value)
    return job


# -- a machine says what it is ------------------------------------------------------------


def test_a_machine_that_says_what_it_is_is_shown_so(lent: TestClient) -> None:
    token = _pair(lent, ["write:backend"], name="ec2-backend")
    said = lent.post(
        "/api/worker/about",
        json={
            "os": "Ubuntu 24.04",
            "host": "aws-ec2",
            "size": "c7i.xlarge",
            "writers": ["Claude Code sonnet"],
            "gpu": "none",  # a newer app saying more is heard, not refused
        },
        headers={"Authorization": f"Bearer {token}", "x-slipwright-protocol": "2"},
    )
    assert said.status_code == 204, said.text

    (machine,) = lent.get("/api/workers").json()
    assert machine["about"] == {
        "os": "Ubuntu 24.04",
        "host": "aws-ec2",
        "size": "c7i.xlarge",
        "writers": ["Claude Code sonnet"],
    }


def test_a_cloud_nobody_knows_is_shown_as_none(lent: TestClient) -> None:
    token = _pair(lent, ["write:backend"])
    lent.post(
        "/api/worker/about",
        json={"os": "Debian 12", "host": "my-own-rack"},
        headers={"Authorization": f"Bearer {token}"},
    )
    (machine,) = lent.get("/api/workers").json()
    assert machine["about"]["host"] is None and machine["about"]["os"] == "Debian 12"


def test_a_machine_that_never_says_is_drawn_by_what_it_can_do(lent: TestClient) -> None:
    _pair(lent, ["write:backend", "ios"])
    (machine,) = lent.get("/api/workers").json()
    assert machine["about"] is None


def test_only_a_paired_machine_may_say_what_it_is(lent: TestClient) -> None:
    said = lent.post("/api/worker/about", json={"os": "Ubuntu"})
    assert said.status_code == 401


# -- the room -------------------------------------------------------------------------------


def test_the_room_shows_the_machine_writing_each_phase(lent: TestClient, repo: Path) -> None:
    hold = threading.Event()

    def slow(machine: Machine, call: dict[str, Any]) -> None:
        machine.post(call, "progress", {"text": "3/7 files"})
        hold.wait(timeout=20)
        Machine.answer(machine, call)

    engine: Engine = lent.app.state.engine  # type: ignore[attr-defined]
    token = _pair(lent, ["write:backend"], name="ec2-backend")
    with Machine(lent, token, behave=slow):
        runner = threading.Thread(target=_run, args=(lent, repo), daemon=True)
        runner.start()
        deadline = time.monotonic() + 20
        room: dict[str, Any] = {}
        while time.monotonic() < deadline:
            jobs = engine.store.list(details=False)
            if jobs:
                room = lent.get(f"/api/jobs/{jobs[0].id}/building").json()
                if any(p.get("doing") for p in room.get("phases", [])):
                    break
            time.sleep(0.05)
        hold.set()
        runner.join(timeout=30)
        after = lent.get(f"/api/jobs/{jobs[0].id}/building").json()

    assert room["live"] is True and room["in_turn"] == 1 and room["step"] == "writing"
    first = room["phases"][0]
    assert first["writing"] and first["writer"] == "ec2-backend" and first["doing"] == "3/7 files"
    (machine,) = room["machines"]
    assert machine["name"] == "ec2-backend" and machine["phase"] == 1
    assert machine["writes"] == ["backend"]
    assert room["server"]["writing"] == []  # the machine has it, not the server
    # once it is past the phases the room closes, every phase built
    assert after["live"] is False
    assert [p["status"] for p in after["phases"]] == ["done", "done"]
    assert not any(p["writing"] for p in after["phases"])


def test_the_server_is_shown_writing_what_no_machine_took(
    lent: TestClient, store: JobStore, repo: Path
) -> None:
    engine: Engine = lent.app.state.engine  # type: ignore[attr-defined]
    job = _job(engine, repo, phase_index=0, ahead={"3": {"role": "backend", "started_at": "now"}})
    job = job.model_copy(update={"state": JobState.DEVELOPING})

    room = build_room(job, machines=[], calls=[], slots=3, models=["anthropic · sonnet"])

    assert room.live and room.in_turn == 1 and room.slots == 3
    assert room.server.writing == [1, 3]  # the phase in its turn, and one written ahead
    assert [p.writing for p in room.phases] == [True, False, True]
    assert room.server.models == ["anthropic · sonnet"]


def test_the_room_is_closed_while_a_person_is_asked(lent: TestClient, repo: Path) -> None:
    engine: Engine = lent.app.state.engine  # type: ignore[attr-defined]
    job = _job(engine, repo, phase_index=1)
    for state in (
        JobState.AWAITING_REVIEW_APPROVAL,
        JobState.AWAITING_DECISION,
        JobState.PAUSED,
        JobState.QA,
    ):
        room = build_room(
            job.model_copy(update={"state": state}), machines=[], calls=[], slots=3, models=[]
        )
        assert not room.live, state
        assert room.in_turn is None


def test_another_accounts_development_is_not_found(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    from slipwright.workspace import PortAllocator, Workspace
    from tests.test_phase12_teams import BASE, _sign_up_owner

    engine = Engine(
        store, Workspace(worktrees_root, PortAllocator(start=8900, end=8999)), seed_profile=seed
    )
    engine.update_mail_settings(base_url=BASE)
    theirs = engine.create_job("somebody else's", repo_path=repo)
    theirs.owner_id = "another-account"
    store.save(theirs)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=True)) as owner:
        _sign_up_owner(owner, store)
        assert owner.get(f"/api/jobs/{theirs.id}/building").status_code == 404
