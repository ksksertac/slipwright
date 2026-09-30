"""Pairing a Mac, and the door it builds through (T14.3).

Two kinds of caller, kept apart:

* **The account's owner**, signed in as usual, under ``/api/workers``: a connection code
  to carry to the Mac, the machines paired, and taking one away. The owner's alone -- a
  member of the team does not lend the account machines.
* **The worker itself**, under ``/api/worker/``, which is outside the login
  (``PUBLIC_PREFIXES``) because a Mac is not a person with a session. Pairing proves itself
  with the code; everything after with the worker's own token, which opens these endpoints
  and nothing else. A worker is given its own account's builds and never another's.

A worker that polls is also what wakes what was waiting for it: the first time anything
but a person's click moves a development, so it is asked per account and each job then
runs on its own owner's keys.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from slipwright import workers as pairing
from slipwright.api.auth import _engine, engine_for, require_owner
from slipwright.engine import Engine
from slipwright.schemas.profile import PLATFORMS
from slipwright.schemas.worker import TaskResult, Worker, WorkerTask

log = logging.getLogger(__name__)

router = APIRouter(tags=["workers"])

#: The longest a poll waits for a build before answering "nothing" (the worker asks again).
LONG_POLL_S = 25.0
#: How often a waiting poll looks for a build.
POLL_TICK_S = 1.0
#: Where the address a person gave for their server is kept, for the next code.
ADDRESS_SETTING = "workers.address"


class CodeRequest(BaseModel):
    address: str | None = Field(
        default=None,
        description="The address the page is open at, or one the person typed: the server "
        "as the Mac should call it. Unused when the installation has its own address.",
    )


class ConnectionCode(BaseModel):
    code: str
    command: str = Field(description="What to run on the Mac.")
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


def _owner(request: Request) -> str | None:
    user = require_owner(request)
    return None if user.id == "anonymous" else str(user.tenant_id)


def _known(capabilities: list[str]) -> list[str]:
    """Only platforms there are; anything else a worker says is ignored, not stored."""
    return sorted({c for c in capabilities if c in PLATFORMS})


# -- the owner's side -------------------------------------------------------------------


@router.get("/workers", response_model=list[Worker])
def list_workers(request: Request) -> list[Worker]:
    """The machines this account has paired, and whether each is there now."""
    owner = _owner(request)
    return engine_for(request).store.list_workers(owner, live_since=pairing.live_since())


@router.post("/workers/code", response_model=ConnectionCode)
def connection_code(body: CodeRequest, request: Request) -> ConnectionCode:
    """A fresh connection code; any earlier one stops working.

    The address in it is the installation's own when it has one (the mail settings' base
    URL), else the one the page sent -- and never ``localhost``, which on the Mac would be
    the Mac. A usable address the person gave is kept for the next code.
    """
    owner = _owner(request)
    engine = engine_for(request)
    kept = engine.store.get_setting(ADDRESS_SETTING)
    try:
        address = pairing.choose_address(
            engine.mail_settings().base_url, body.address, kept if isinstance(kept, str) else None
        )
    except pairing.AddressNeeded as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.address and pairing.reachable(body.address) and address != kept:
        engine.store.set_setting(ADDRESS_SETTING, address)
    secret = pairing.new_secret()
    engine.store.create_worker_code(owner, pairing.secret_hash(secret), ttl=pairing.CODE_TTL)
    code = pairing.pack(address, secret)
    return ConnectionCode(
        code=code,
        command=f"slipwright worker --connect {code}",
        address=address,
        expires_at=datetime.now().astimezone() + pairing.CODE_TTL,
    )


@router.delete("/workers/{worker_id}", status_code=204)
def revoke_worker(worker_id: str, request: Request) -> None:
    """Take a machine away. Its next poll is refused and what it was building goes back
    in the queue. Another account's worker is not found."""
    owner = _owner(request)
    if not engine_for(request).store.revoke_worker(owner, worker_id):
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
    valid, owner = store.redeem_worker_code(pairing.secret_hash(secret))
    if not valid:
        raise HTTPException(
            status_code=403, detail="this code has been used or has run out; make a new one"
        )
    token = pairing.new_token()
    worker = store.add_worker(
        owner, body.name, pairing.token_hash(token), _known(body.capabilities)
    )
    log.info("worker %s paired (%s) for %s", worker.id, body.name, owner or "the installation")
    _wake(request, owner)
    return Paired(worker_id=worker.id, token=token)


@router.post(
    "/worker/poll",
    response_model=None,
    responses={200: {"model": WorkerTask}, 204: {"description": "nothing to build yet"}},
)
def poll(body: PollRequest, request: Request) -> Response:
    """Say what this machine can build, and wait a while for a build of its account.
    Doubles as the heartbeat; an empty answer (204) means ask again."""
    worker = _worker(request)
    store = _engine(request).store
    capabilities = _known(body.capabilities)
    store.touch_worker(worker.id, capabilities)
    _wake(request, worker.owner_id)
    deadline = time.monotonic() + body.wait_s
    while True:
        task = store.claim_worker_task(worker.owner_id, worker.id, capabilities)
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
