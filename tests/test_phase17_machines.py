"""T17.1-T17.2: a machine somebody on the account lent writes a phase on its own plan.

To the engine a machine is one more provider: the request goes into a queue, a machine
that writes the phase's domain takes it, and its model's text comes back to be parsed and
checked like any vendor's. What these tests hold it to is the other half -- that a machine
which never comes, goes quiet or gives up costs the development nothing but the wait.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright import costs
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.worker import CallAnswer
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

LAN = "http://192.168.1.20:8500"


def _context(prompt: str) -> dict[str, Any]:
    body = prompt[prompt.index("Context:\n") + len("Context:\n") : prompt.index("\n\nRespond with")]
    return dict(json.loads(body))


def _answer(prompt: str) -> dict[str, Any]:
    """What a phase's specialist writes, wherever it runs: one file named for the phase."""
    number = int(_context(prompt)["current_phase"]["number"])
    return {
        "summary": f"phase {number}",
        "changes": [{"path": f"phase{number}.py", "content": f"# phase {number}\n"}],
    }


def _engine(store: JobStore, worktrees_root: Path, seed: Profile, *, server: bool) -> Engine:
    """Two backend phases. With ``server`` False the account's own model refuses to write a
    phase at all, so a development that finishes was written somewhere else."""
    provider = full_provider(seed, phases=2, domains=["backend", "backend"])

    def develop(req: Any) -> dict[str, Any]:
        if not server:
            raise AssertionError("the server's model was asked to write a phase")
        return _answer(req.prompt)

    provider.replies[RoleName.BACKEND] = develop
    engine = full_engine(store, worktrees_root, seed, provider)
    engine.machine_claim_s = 1.0
    engine.machine_quiet_s = 1.0
    engine.machine_tick_s = 0.05
    return engine


def _client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _pair(client: TestClient, capabilities: list[str], name: str = "laptop") -> str:
    code = client.post("/api/workers/code", json={"address": LAN}).json()["code"]
    paired = client.post(
        "/api/worker/pair", json={"code": code, "name": name, "capabilities": capabilities}
    )
    assert paired.status_code == 200, paired.text
    return str(paired.json()["token"])


def _drive(engine: Engine, job: Job) -> Job:
    for _ in range(40):
        if job.state not in APPROVAL_STATES:
            return job
        job = engine.approve(job.id)
    raise AssertionError(f"still at {job.state}")


class Machine:
    """A machine driven through the worker API, as the desktop app drives it. ``behave``
    decides what it does with a call: answer it, fail it, or take it and go quiet."""

    def __init__(
        self,
        client: TestClient,
        token: str,
        *,
        capabilities: list[str] | None = None,
        behave: Callable[[Machine, dict[str, Any]], None] | None = None,
    ) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self.capabilities = capabilities or ["write:backend"]
        self.behave = behave or Machine.answer
        self.calls: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> Machine:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.is_set():
            got = self.client.post(
                "/api/worker/poll",
                json={"capabilities": self.capabilities, "wait_s": 0.1},
                headers=self.headers,
            )
            if got.status_code == 200 and got.json()["kind"] == "write":
                self.calls.append(got.json())
                self.behave(self, got.json())

    def post(self, call: dict[str, Any], what: str, body: dict[str, Any]) -> int:
        return self.client.post(
            f"/api/worker/calls/{call['id']}/{what}", json=body, headers=self.headers
        ).status_code

    @staticmethod
    def answer(machine: Machine, call: dict[str, Any]) -> None:
        assert machine.post(call, "progress", {"text": "writing"}) == 204
        text = json.dumps(_answer(call["prompt"]))
        assert (
            machine.post(
                call,
                "answer",
                {"text": text, "model": "claude-code", "input_tokens": 10, "output_tokens": 5},
            )
            == 204
        )


@pytest.fixture
def lent(store: JobStore, worktrees_root: Path, seed: Profile) -> Iterator[TestClient]:
    yield from _client(_engine(store, worktrees_root, seed, server=False))


@pytest.fixture
def fallback(store: JobStore, worktrees_root: Path, seed: Profile) -> Iterator[TestClient]:
    yield from _client(_engine(store, worktrees_root, seed, server=True))


def _run(client: TestClient, repo: Path) -> Job:
    engine: Engine = client.app.state.engine  # type: ignore[attr-defined]
    job = engine.start(engine.create_job("two backend phases", repo_path=repo).id)
    return _drive(engine, job)


# -- written on a machine ---------------------------------------------------------------


def test_a_lent_machine_writes_the_phases_and_the_server_applies_them(
    lent: TestClient, repo: Path
) -> None:
    token = _pair(lent, ["write:backend"])
    with Machine(lent, token) as machine:
        job = _run(lent, repo)

    assert job.state is JobState.DONE, job.history[-1].note
    assert [c["phase"] for c in machine.calls] == [1, 2]
    assert machine.calls[0]["role"] == "backend" and machine.calls[0]["phases"] == 2
    assert job.worktree_path is not None
    assert (job.worktree_path / "phase1.py").read_text() == "# phase 1\n"
    assert (job.worktree_path / "phase2.py").read_text() == "# phase 2\n"
    # the machine's plan paid for it: counted, and not the account's bill
    written = [e for e in job.data.invocation_log if e["role"] == "backend"]
    assert {e["provider"] for e in written} == {"machine"}
    assert all(costs.on_a_subscription(e) for e in written)
    assert written[0]["model"] == "claude-code" and written[0]["input_tokens"] == 10


def test_a_wrong_answer_from_a_machine_is_asked_again_never_written(
    lent: TestClient, repo: Path
) -> None:
    said: list[str] = []

    def once_wrong(machine: Machine, call: dict[str, Any]) -> None:
        if not said:
            said.append("garbage")
            machine.post(call, "answer", {"text": "this is not JSON"})
            return
        said.append("good")
        Machine.answer(machine, call)

    token = _pair(lent, ["write:backend"])
    with Machine(lent, token, behave=once_wrong):
        job = _run(lent, repo)

    assert job.state is JobState.DONE
    assert said[:2] == ["garbage", "good"]  # the retry went to the machine again
    assert job.worktree_path is not None
    assert "not JSON" not in (job.worktree_path / "phase1.py").read_text()


# -- and when it does not come ----------------------------------------------------------


def test_a_call_nobody_takes_is_written_by_the_server(fallback: TestClient, repo: Path) -> None:
    _pair(fallback, ["write:backend"])  # paired, and never polls: a laptop closed after
    job = _run(fallback, repo)

    assert job.state is JobState.DONE
    providers = {e["provider"] for e in job.data.invocation_log if e["role"] == "backend"}
    assert "machine" not in providers


def test_a_machine_that_goes_quiet_loses_the_call_to_the_server(
    fallback: TestClient, repo: Path
) -> None:
    def take_and_sleep(machine: Machine, call: dict[str, Any]) -> None:
        machine._stop.set()  # took it, then the lid closed

    token = _pair(fallback, ["write:backend"])
    with Machine(fallback, token, behave=take_and_sleep) as machine:
        job = _run(fallback, repo)
        held = machine.calls[0]
        late = machine.post(held, "answer", {"text": json.dumps({"summary": "late"})})

    assert job.state is JobState.DONE
    assert late == 409  # the server stopped waiting; a late answer is refused
    assert job.worktree_path is not None
    assert (job.worktree_path / "phase1.py").exists()


def test_a_machine_that_gives_up_hands_the_call_back(fallback: TestClient, repo: Path) -> None:
    def give_up(machine: Machine, call: dict[str, Any]) -> None:
        machine.post(call, "fail", {"message": "usage limit reached", "kind": "rejected"})

    token = _pair(fallback, ["write:backend"])
    with Machine(fallback, token, behave=give_up) as machine:
        job = _run(fallback, repo)

    assert job.state is JobState.DONE
    assert machine.calls  # it was asked, said no, and the server wrote the phases


# -- who is given what ------------------------------------------------------------------


def test_a_machine_that_writes_nothing_is_never_given_a_call(
    fallback: TestClient, store: JobStore
) -> None:
    token = _pair(fallback, ["ios"])  # a Mac builder from before machines wrote
    store.enqueue_worker_call(
        None, "job", role="backend", domain="backend", phase=1, request=_request()
    )
    got = fallback.post(
        "/api/worker/poll",
        json={"capabilities": ["ios"], "wait_s": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert got.status_code == 204


def test_a_machine_is_given_only_the_domains_it_writes(store: JobStore) -> None:
    store.enqueue_worker_call(None, "job", role="web_ui", domain="web", phase=1, request=_request())
    assert store.claim_worker_call(None, "m1", ["write:backend"]) is None
    assert store.claim_worker_call(None, "m1", ["write:web"]) is not None


def test_a_call_is_claimed_by_one_machine_only(store: JobStore) -> None:
    store.enqueue_worker_call(
        None, "job", role="backend", domain="backend", phase=1, request=_request()
    )
    first = store.claim_worker_call(None, "m1", ["write:backend"])
    second = store.claim_worker_call(None, "m2", ["write:backend"])
    assert first is not None and second is None
    # and only the one holding it may answer
    assert not store.answer_worker_call(first.id, "m2", CallAnswer(text="{}"))
    assert store.answer_worker_call(first.id, "m1", CallAnswer(text="{}"))
    assert not store.answer_worker_call(first.id, "m1", CallAnswer(text="{}"))  # once


def test_another_accounts_machine_never_sees_the_call(store: JobStore) -> None:
    store.enqueue_worker_call(
        "acct-a", "job", role="backend", domain="backend", phase=1, request=_request()
    )
    assert store.claim_worker_call("acct-b", "theirs", ["write:backend"]) is None
    assert store.claim_worker_call("acct-a", "ours", ["write:backend"]) is not None


def test_removing_a_machine_takes_back_what_it_was_writing(store: JobStore) -> None:
    worker = store.add_worker(None, "laptop", "hash", ["write:backend"])
    call_id = store.enqueue_worker_call(
        None, "job", role="backend", domain="backend", phase=1, request=_request()
    )
    assert store.claim_worker_call(None, worker.id, ["write:backend"]) is not None
    assert store.revoke_worker(None, worker.id)
    row = store.worker_call_row(call_id)
    assert row is not None and row["state"] == "cancelled"


def test_the_machines_page_says_what_a_machine_is_writing(lent: TestClient, repo: Path) -> None:
    hold = threading.Event()

    def slow(machine: Machine, call: dict[str, Any]) -> None:
        machine.post(call, "progress", {"text": "3/7 files"})
        hold.wait(timeout=20)
        Machine.answer(machine, call)

    token = _pair(lent, ["write:backend"], name="Ayşe's MacBook")
    with Machine(lent, token, behave=slow) as machine:
        runner = threading.Thread(target=_run, args=(lent, repo), daemon=True)
        runner.start()
        deadline = time.monotonic() + 20
        listed: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            listed = lent.get("/api/workers/calls").json()
            if listed and listed[0].get("progress"):
                break
            time.sleep(0.05)
        machines = lent.get("/api/workers").json()
        hold.set()
        runner.join(timeout=30)

    assert listed and listed[0]["machine"] == "Ayşe's MacBook"
    assert listed[0]["phase"] == 1 and listed[0]["progress"] == "3/7 files"
    assert machines[0]["writing"] and machines[0]["doing_phase"] == 1
    assert machines[0]["doing"] == "3/7 files"
    assert machines[0]["capabilities"] == ["write:backend"]
    assert machine.calls


def _request() -> dict[str, Any]:
    return {
        "job_id": "job",
        "role": "backend",
        "domain": "backend",
        "system": "s",
        "prompt": "p",
        "output_schema": {},
        "images": [],
        "thinking_depth": "off",
        "timeout_s": 60,
    }


# -- everybody on the account lends machines (T17.2) -------------------------------------


@pytest.fixture
def team(store: JobStore, worktrees_root: Path, seed: Profile) -> Iterator[Engine]:
    from slipwright.workspace import PortAllocator, Workspace
    from tests.test_phase12_teams import BASE

    engine = Engine(
        store, Workspace(worktrees_root, PortAllocator(start=8900, end=8999)), seed_profile=seed
    )
    engine.update_mail_settings(base_url=BASE)
    yield engine


def test_a_member_lends_a_machine_and_answers_only_for_their_own(
    team: Engine, store: JobStore
) -> None:
    from tests.test_phase12_teams import _accept, _invite, _sign_up_owner

    app = create_app(team, resume_on_startup=False, require_auth=True)
    with TestClient(app) as owner, TestClient(app) as member:
        _sign_up_owner(owner, store)
        _invite(owner, role="backend")
        _accept(member, store)

        made = member.post("/api/workers/code", json={"address": LAN})
        assert made.status_code == 200, made.text
        # the owner making a code of their own does not void the member's
        mine = owner.post("/api/workers/code", json={"address": LAN}).json()["code"]
        theirs = made.json()["code"]
        for code, name in ((theirs, "Sertaç's laptop"), (mine, "office Mac")):
            paired = owner.post(
                "/api/worker/pair",
                json={"code": code, "name": name, "capabilities": ["write:web"]},
            )
            assert paired.status_code == 200, paired.text

        everything = {w["name"]: w for w in owner.get("/api/workers").json()}
        assert set(everything) == {"Sertaç's laptop", "office Mac"}
        assert everything["Sertaç's laptop"]["lent_by_name"] == "Sertaç"
        assert everything["office Mac"]["lent_by_name"] == "Ada"  # the owner's own

        own = member.get("/api/workers").json()
        assert [w["name"] for w in own] == ["Sertaç's laptop"]
        office = everything["office Mac"]["id"]
        assert member.delete(f"/api/workers/{office}").status_code == 404
        laptop = everything["Sertaç's laptop"]["id"]
        assert owner.delete(f"/api/workers/{laptop}").status_code == 204
        assert member.get("/api/workers").json() == []
        # both machines work for the account, whoever lent them
        account = store.find_by_email("owner@acme.com")
        assert account is not None
        assert {w.owner_id for w in store.list_workers(account.id)} == {account.id}


def test_an_app_too_old_for_the_server_is_told_to_update_and_keeps_its_pairing(
    fallback: TestClient,
) -> None:
    token = _pair(fallback, ["write:backend"])
    auth = {"Authorization": f"Bearer {token}"}
    old = fallback.post("/api/worker/heartbeat", headers={**auth, "x-slipwright-protocol": "0"})
    assert old.status_code == 426 and "update the app" in old.json()["detail"]
    # saying nothing is the first version: the headless worker, and apps from before
    assert fallback.post("/api/worker/heartbeat", headers=auth).status_code == 204
    said = fallback.post("/api/worker/heartbeat", headers={**auth, "x-slipwright-protocol": "1"})
    assert said.status_code == 204
