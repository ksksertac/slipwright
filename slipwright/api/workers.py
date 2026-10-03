"""Pairing a machine, and the door it works through (T14.3, T17).

Two kinds of caller, kept apart:

* **People on the account**, signed in as usual, under ``/api/workers``: a connection code
  to carry to the machine, the machines paired, and taking one away. The owner sees and
  removes every machine; a member lends their own and sees and removes those (T17.2). A
  machine works for its account whoever lent it, and lending one decides nothing about
  who may approve a gate.
* **The machine itself**, under ``/api/worker/``, which is outside the login
  (``PUBLIC_PREFIXES``) because a machine is not a person with a session. Pairing proves
  itself with the code; everything after with the worker's own token, which opens these
  endpoints and nothing else. A machine is given its own account's builds and calls and
  never another's.

A worker that polls is also what wakes what was waiting for it: the first time anything
but a person's click moves a development, so it is asked per account and each job then
runs on its own owner's keys.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from slipwright import workers as pairing
from slipwright.api.auth import _engine, current_user, engine_for
from slipwright.engine import Engine
from slipwright.relay import host as relay_host
from slipwright.schemas.profile import PLATFORMS
from slipwright.schemas.worker import (
    CallAnswer,
    CallFailure,
    CallProgress,
    TaskResult,
    Worker,
    WorkerCall,
    WorkerTask,
)
from slipwright.store.workers import WRITES

log = logging.getLogger(__name__)

router = APIRouter(tags=["workers"])

#: The longest a poll waits for a build before answering "nothing" (the worker asks again).
LONG_POLL_S = 25.0
#: How often a waiting poll looks for a build.
POLL_TICK_S = 1.0
#: The last address a page was opened at that another machine could reach, for the next
#: code made at ``localhost``.
ADDRESS_SETTING = "workers.address"


class CodeRequest(BaseModel):
    address: str | None = Field(
        default=None,
        description="The address the page is open at: the server "
        "as the Mac should call it. Unused when the installation has its own address.",
    )


class ConnectionCode(BaseModel):
    code: str
    command: str = Field(description="What to run on the machine, without the desktop app.")
    install: list[str] = Field(description="What installs the headless worker, once.")
    address: str = Field(description="The address inside the code.")
    expires_at: datetime


class PairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=10, max_length=400)
    name: str = Field(min_length=1, max_length=120)
    capabilities: list[str] = Field(default_factory=list)


class Paired(BaseModel):
    worker_id: str
    token: str = Field(description="Shown once; the server keeps only its hash.")


class PollRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capabilities: list[str] = Field(default_factory=list)
    wait_s: float = Field(default=LONG_POLL_S, ge=0, le=LONG_POLL_S)
    # optional: a worker from before it was sent keeps the name it paired with
    name: str | None = Field(default=None, min_length=1, max_length=120)


#: The domains a machine may say it writes (``roles/results.py``'s ``PlanPhase.domain``).
DOMAINS = ("backend", "web", "mobile", "infra", "docs", "general")


def _who(request: Request) -> tuple[str | None, str | None]:
    """(account, person): whose machines these are, and -- for a member -- whose own. The
    owner's person is None: the owner is answerable for every machine of the account."""
    user = current_user(request)
    if user.id == "anonymous":
        return None, None
    return str(user.tenant_id), (user.id if user.is_member else None)


def _known(capabilities: list[str]) -> list[str]:
    """Only platforms there are and domains a phase has; anything else a worker says is
    ignored, not stored."""
    writes = {WRITES + d for d in DOMAINS}
    return sorted({c for c in capabilities if c in PLATFORMS or c in writes})


# -- the owner's side -------------------------------------------------------------------


@router.get("/workers", response_model=list[Worker])
def list_workers(request: Request) -> list[Worker]:
    """The machines of this account, whether each is there now, who lent it and what it is
    writing. A member is shown their own."""
    owner, person = _who(request)
    store = engine_for(request).store
    found = store.list_workers(owner, live_since=pairing.live_since())
    if person is not None:
        found = [w for w in found if w.lent_by == person]
    names: dict[str, str] = {}
    if owner is not None:
        names = {u.id: u.username for u in store.list_users(owner)}
    calls = {str(c["worker_id"]): c for c in store.open_worker_calls(owner)}
    return [
        w.model_copy(
            update={
                "lent_by_name": names.get(w.lent_by or "") or names.get(owner or ""),
                "writing": w.id in calls,
                "doing_phase": calls.get(w.id, {}).get("phase"),
                "doing": calls.get(w.id, {}).get("progress"),
            }
        )
        for w in found
    ]


class MachineCall(BaseModel):
    job_id: str
    phase: int | None = None
    role: str
    machine: str | None = Field(default=None, description="The machine writing it.")
    progress: str | None = Field(default=None, description="What it last said it was doing.")
    since: str | None = None


@router.get("/workers/calls", response_model=list[MachineCall])
def open_calls(request: Request) -> list[dict[str, Any]]:
    """The phases machines of this account are writing now: which job and phase, which
    machine, and what it last said. What *Right now* shows beside the server's own calls."""
    owner, _person = _who(request)
    return [
        {
            "job_id": c["job_id"],
            "phase": c.get("phase"),
            "role": c["role"],
            "machine": c.get("worker_name"),
            "progress": c.get("progress"),
            "since": c.get("claimed_at"),
        }
        for c in engine_for(request).store.open_worker_calls(owner)
    ]


@router.post("/workers/code", response_model=ConnectionCode)
def connection_code(body: CodeRequest, request: Request) -> ConnectionCode:
    """A fresh connection code; any earlier one stops working.

    The address in it is the installation's own when it has one (the mail settings' base
    URL), else the one the page was opened at, else the last such one kept. A page open at
    ``localhost`` still gets a code: it carries the port, and the Mac finds the server on
    its own network. Nobody is asked for an address.
    """
    owner, person = _who(request)
    engine = engine_for(request)
    # with the relay on, the code carries the room: a machine anywhere comes in through it
    address = relay_host.room_address(_engine(request).raw_store)
    kept = engine.store.get_setting(ADDRESS_SETTING)
    if address is None:
        try:
            address = pairing.choose_address(
                engine.mail_settings().base_url,
                body.address,
                kept if isinstance(kept, str) else None,
            )
        except pairing.AddressNeeded as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.address and pairing.reachable(body.address) and address != kept:
        engine.store.set_setting(ADDRESS_SETTING, address)
    secret = pairing.new_secret()
    engine.store.create_worker_code(
        owner,
        pairing.secret_hash(secret),
        ttl=pairing.CODE_TTL,
        lent_by=person,
        pair_key=pairing.pair_key(secret).hex(),
    )
    code = pairing.pack(address, secret)
    return ConnectionCode(
        code=code,
        command=f"slipwright worker --connect {code}",
        install=list(pairing.INSTALL),
        address=address,
        expires_at=datetime.now().astimezone() + pairing.CODE_TTL,
    )


class RelayState(BaseModel):
    available: bool = Field(description="This installation may use a relay at all.")
    enabled: bool = Field(description="Machines on other networks may reach it.")
    connected: bool = Field(description="It is in its room on the relay right now.")
    url: str | None = None


class RelayChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _relay_state(request: Request) -> RelayState:
    store = _engine(request).raw_store
    keeper = getattr(request.app.state, "relay", None)
    host = getattr(keeper, "host", None)
    return RelayState(
        available=relay_host.relay_url() is not None,
        enabled=relay_host.enabled(store),
        connected=bool(host is not None and host.connected.is_set()),
        url=relay_host.relay_url(),
    )


@router.get("/workers/relay", response_model=RelayState)
def relay_state(request: Request) -> RelayState:
    """Whether machines on other networks can reach this installation, and whether it is
    in its room right now."""
    current_user(request)
    return _relay_state(request)


@router.put("/workers/relay", response_model=RelayState)
def change_relay(body: RelayChange, request: Request) -> RelayState:
    """Let machines on other networks in, or stop. The installation's to decide -- it opens
    a connection out of this machine -- so the administrator's, on a server with accounts;
    any code made before is unchanged, and a machine paired through the relay waits."""
    user = current_user(request)
    if user.id != "anonymous" and (not user.is_admin or user.is_member):
        raise HTTPException(status_code=403, detail="the installation's administrator decides this")
    if body.enabled and relay_host.relay_url() is None:
        raise HTTPException(status_code=409, detail="this installation has the relay turned off")
    _engine(request).raw_store.set_setting(relay_host.ENABLED, body.enabled)
    return _relay_state(request)


@router.delete("/workers/{worker_id}", status_code=204)
def revoke_worker(worker_id: str, request: Request) -> None:
    """Take a machine away. Its next poll is refused, what it was building goes back in
    the queue and what it was writing is written by the server instead. Another account's
    worker is not found, and neither -- for a member -- is one somebody else lent."""
    owner, person = _who(request)
    if not engine_for(request).store.revoke_worker(owner, worker_id, lent_by=person):
        raise HTTPException(status_code=404, detail="no such worker")


# -- the worker's side --------------------------------------------------------------------


def _worker(request: Request) -> Worker:
    """The worker a request's token belongs to, or 401. Checked before anything is read."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.startswith("swk_"):
        raise HTTPException(status_code=401, detail="a worker token is required")
    found = _engine(request).store.worker_for_token(pairing.token_hash(token.strip()))
    if found is None:
        raise HTTPException(status_code=401, detail="this worker is not paired (or was removed)")
    return found


@router.post("/worker/pair", response_model=Paired)
def pair(body: PairRequest, request: Request) -> Paired:
    """Trade a connection code for a worker token. The code is spent whether it worked
    or not, so it cannot be tried twice."""
    try:
        _address, secret = pairing.unpack(body.code)
    except pairing.CodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store = _engine(request).store
    valid, owner, lent_by = store.redeem_worker_code(pairing.secret_hash(secret))
    if not valid:
        raise HTTPException(
            status_code=403, detail="this code has been used or has run out; make a new one"
        )
    token = pairing.new_token()
    worker = store.add_worker(
        owner, body.name, pairing.token_hash(token), _known(body.capabilities), lent_by=lent_by
    )
    log.info("worker %s paired (%s) for %s", worker.id, body.name, owner or "the installation")
    _wake(request, owner)
    return Paired(worker_id=worker.id, token=token)


@router.post(
    "/worker/poll",
    response_model=None,
    responses={
        200: {"model": WorkerTask | WorkerCall},
        204: {"description": "nothing to do yet"},
    },
)
def poll(body: PollRequest, request: Request) -> Response:
    """Say what this machine can do, and wait a while for a build or a call of its account.
    Doubles as the heartbeat; an empty answer (204) means ask again. A build first: a
    development waiting on a platform has nowhere else to go, a call does."""
    worker = _worker(request)
    store = _engine(request).store
    capabilities = _known(body.capabilities)
    store.touch_worker(worker.id, capabilities, name=body.name)
    _wake(request, worker.owner_id)
    deadline = time.monotonic() + body.wait_s
    while True:
        task: WorkerTask | WorkerCall | None = store.claim_worker_task(
            worker.owner_id, worker.id, [c for c in capabilities if c in PLATFORMS]
        ) or store.claim_worker_call(worker.owner_id, worker.id, capabilities)
        if task is not None:
            return JSONResponse(task.model_dump(mode="json"))
        if time.monotonic() >= deadline:
            return Response(status_code=204)
        time.sleep(min(POLL_TICK_S, max(deadline - time.monotonic(), 0)))
        store.touch_worker(worker.id)


@router.post("/worker/heartbeat", status_code=204)
def heartbeat(request: Request) -> None:
    """Still here, still building: sent while a long build runs."""
    worker = _worker(request)
    _engine(request).store.touch_worker(worker.id)


@router.get("/worker/tasks/{task_id}/snapshot")
def task_snapshot(task_id: str, request: Request) -> Response:
    """The worktree of a build this worker holds, as a tar.gz."""
    worker = _worker(request)
    data = _engine(request).store.worker_task_snapshot(task_id, worker.id)
    if data is None:
        raise HTTPException(status_code=404, detail="no such build held by this worker")
    return Response(content=data, media_type="application/gzip")


@router.post("/worker/tasks/{task_id}/result", status_code=204)
def task_result(task_id: str, body: TaskResult, request: Request) -> None:
    """What the build did. Only the worker holding it may say, and only once."""
    worker = _worker(request)
    if not _engine(request).store.finish_worker_task(task_id, worker.id, body):
        raise HTTPException(status_code=409, detail="this build is not held by this worker")


@router.post("/worker/calls/{call_id}/progress", status_code=204)
def call_progress(call_id: str, body: CallProgress, request: Request) -> None:
    """Still writing, and what it last did. 409 when the call is no longer this machine's
    -- taken back because it went quiet, or its development stopped -- and it should stop."""
    worker = _worker(request)
    if not _engine(request).store.hear_worker_call(call_id, worker.id, body.text):
        raise HTTPException(status_code=409, detail="this call is not held by this machine")


@router.post("/worker/calls/{call_id}/answer", status_code=204)
def call_answer(call_id: str, body: CallAnswer, request: Request) -> None:
    """The model's answer, as it came. Only the machine holding the call may give it, and
    only once; the server reads and checks it as it would its own provider's."""
    worker = _worker(request)
    if not _engine(request).store.answer_worker_call(call_id, worker.id, body):
        raise HTTPException(status_code=409, detail="this call is not held by this machine")


@router.post("/worker/calls/{call_id}/fail", status_code=204)
def call_fail(call_id: str, body: CallFailure, request: Request) -> None:
    """The machine could not write it -- its plan ran out, its model refused, it crashed.
    The server's own model writes it instead; nothing is charged to the development."""
    worker = _worker(request)
    if not _engine(request).store.fail_worker_call(call_id, worker.id, body):
        raise HTTPException(status_code=409, detail="this call is not held by this machine")


# -- waking what waited -----------------------------------------------------------------

_waking: set[str] = set()
_waking_lock = threading.Lock()


def _wake(request: Request, owner_id: str | None) -> None:
    """Carry on this account's developments that a builder now can. Each in its own
    thread, as a resume at startup does, and never two threads for one job."""
    engine = _engine(request)
    for job_id in engine.waiting_for_builders(owner_id):
        with _waking_lock:
            if job_id in _waking:
                continue
            _waking.add(job_id)
        threading.Thread(target=_resume, args=(engine, job_id), daemon=True).start()


def _resume(engine: Engine, job_id: str) -> None:
    try:
        engine.resume(job_id)
    except Exception:  # noqa: BLE001 - a background thread has nobody to raise to
        log.exception("job %s: resuming for a builder failed", job_id)
    finally:
        with _waking_lock:
            _waking.discard(job_id)


__all__ = ["router"]
