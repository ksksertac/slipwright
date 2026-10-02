"""Moving an account to another Slipwright on the network (``slipwright/transfer``).

Two kinds of caller, kept apart as on the Mac's door (``api/workers.py``):

* **The account's owner**, signed in, under ``/api/transfer``: this machine's card, the
  others found on the network, a code to show, a transfer to start and how it is going.
  The owner's alone -- a member of the team does not move the account.
* **Another installation**, under ``/api/transfer/peer/``, outside the login
  (``PUBLIC_PREFIXES``) because it is a machine, not a person. ``hello`` says what this
  is to anybody who asks on the network; ``pair`` is the key exchange, whose success is
  the proof; every part after it is sealed with the key, and one that does not open ends
  the transfer.

All of it answers 404 on an installation with transfers off (``SLIPWRIGHT_TRANSFER``) --
a hosted server by default -- apart from the page's own question of whether they are on.
"""

from __future__ import annotations

import base64
import binascii
import logging
import secrets
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from slipwright import workers as macs
from slipwright.api.auth import _engine, require_owner
from slipwright.api.workers import ADDRESS_SETTING
from slipwright.engine import Engine
from slipwright.schemas.transfer import (
    TransferCode,
    TransferHello,
    TransferHere,
    TransferPaired,
    TransferPairRequest,
    TransferPeer,
    TransferSendRequest,
    TransferStatus,
    TransferStep,
)
from slipwright.store.migrate import current_revision
from slipwright.transfer import incoming, nearby, outgoing
from slipwright.transfer.channel import confirmation
from slipwright.transfer.rows import Progress
from slipwright.update import running_version

log = logging.getLogger(__name__)

router = APIRouter(tags=["transfer"])

#: Which installation this is, so one found twice -- by two of its addresses -- is shown
#: once, and this one is not shown to itself.
INSTANCE_SETTING = "transfer.instance"
#: Key exchanges one address may start in a minute. Each spends a code, so this is not
#: what stops guessing; it stops somebody on the network spending every code shown.
PAIR_LIMIT = 20


def _on(engine: Engine) -> None:
    if not getattr(engine, "transfer_enabled", True):
        raise HTTPException(status_code=404, detail="moving to another machine is off here")


def _desk(request: Request) -> incoming.Desk:
    desk: incoming.Desk | None = getattr(request.app.state, "transfer_desk", None)
    if desk is None:
        desk = request.app.state.transfer_desk = incoming.Desk()
    return desk


def _instance(engine: Engine) -> str:
    found = engine.store.get_setting(INSTANCE_SETTING)
    if isinstance(found, str) and found:
        return found
    made = secrets.token_hex(8)
    engine.store.set_setting(INSTANCE_SETTING, made)
    return made


def _scope(request: Request) -> outgoing.Scope:
    """Whose work this request may move: the account's, and the installation's too for
    its administrator. With sign-in off there is one person and it is all theirs."""
    user = require_owner(request)
    if user.id == "anonymous":
        return outgoing.Scope(owner=None, admin=True, everything=True)
    return outgoing.Scope(owner=str(user.tenant_id), admin=bool(user.is_admin))


def _revision(engine: Engine) -> str | None:
    return current_revision(engine.raw_store.db)


def _client(request: Request) -> httpx.Client:
    """What this server calls another with. Replaceable, so a test can point one app at
    another in the same process."""
    client: httpx.Client | None = getattr(request.app.state, "transfer_client", None)
    return client or httpx.Client(timeout=httpx.Timeout(30, read=15 * 60))


def _page_port(address: str | None) -> int:
    from urllib.parse import urlsplit

    if address:
        port = urlsplit(address).port
        if port:
            return port
    return nearby.DEFAULT_PORT


def _addresses(engine: Engine, page: str | None) -> list[str]:
    """Where another machine might reach this one: the page's own address when it is a
    network one, the one a Mac was last given, then this machine's outbound address."""
    found: list[str] = []
    kept = engine.store.get_setting(ADDRESS_SETTING)
    for candidate in (page, kept if isinstance(kept, str) else None):
        if candidate and macs.reachable(candidate):
            base = candidate.rstrip("/")
            if base not in found:
                found.append(base)
    own = nearby.own_address()
    if own is not None:
        base = f"http://{own}:{_page_port(page)}"
        if base not in found:
            found.append(base)
    return found


def _steps(progress: Progress) -> list[TransferStep]:
    return [
        TransferStep(key=s.key, total=s.total, done=s.done, state=s.state) for s in progress.steps
    ]


def _summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "moved": [str(n) for n in summary.get("projects", [])],
        "skipped": len(summary.get("skipped", [])),
        "counts": {str(k): int(v) for k, v in (summary.get("counts") or {}).items()},
    }


# -- the owner's side -------------------------------------------------------------------


@router.get("/transfer", response_model=TransferHere)
def here(request: Request, address: str | None = None) -> TransferHere:
    """This installation, as its own card shows it, and whether transfers are on."""
    scope = _scope(request)
    engine = _engine(request)
    enabled = bool(getattr(engine, "transfer_enabled", True))
    return TransferHere(
        enabled=enabled,
        instance=_instance(engine),
        name=nearby.machine_name(),
        version=running_version(),
        revision=_revision(engine),
        addresses=_addresses(engine, address) if enabled else [],
        projects=len(outgoing.projects_of(engine, scope)),
        admin=scope.admin,
    )


@router.get("/transfer/nearby", response_model=list[TransferPeer])
def nearby_installations(request: Request, address: str | None = None) -> list[TransferPeer]:
    """The other Slipwrights on this network. ``address`` is where the page is open:
    the best clue to which network that is. Takes a few seconds."""
    _scope(request)
    engine = _engine(request)
    _on(engine)
    kept = engine.store.get_setting(ADDRESS_SETTING)
    mine = _revision(engine)
    with httpx.Client() as client:
        found = nearby.look(
            address,
            kept if isinstance(kept, str) else None,
            instance=_instance(engine),
            client=client,
        )
    return [
        TransferPeer(
            address=str(p["address"]),
            instance=str(p.get("instance", "")),
            name=str(p.get("name", "")) or str(p["address"]),
            version=str(p.get("version", "")),
            revision=p.get("revision") if isinstance(p.get("revision"), str) else None,
            compatible=p.get("revision") == mine,
        )
        for p in found
    ]


@router.post("/transfer/code", response_model=TransferCode)
def transfer_code(request: Request) -> TransferCode:
    """A code to type on the sending machine. The page asks for a new one when this one's
    time is up; the one before keeps working for a while, for whoever is half-way
    through typing it."""
    scope = _scope(request)
    _on(_engine(request))
    code, shown = _desk(request).offer(scope.owner, admin=scope.admin)
    return TransferCode(code=code, shown_s=shown)


@router.delete("/transfer/code", status_code=204)
def stop_receiving(request: Request) -> None:
    """No more codes: whatever is on show stops working."""
    scope = _scope(request)
    _desk(request).withdraw(scope.owner)


@router.get(
    "/transfer/incoming",
    response_model=None,
    responses={200: {"model": TransferStatus}, 204: {"description": "nothing arriving"}},
)
def incoming_status(request: Request) -> Response | TransferStatus:
    """The transfer arriving for this account, or the last one that did."""
    scope = _scope(request)
    rec = _desk(request).latest(scope.owner)
    if rec is None:
        return Response(status_code=204)
    return TransferStatus(
        id=rec.id,
        direction="in",
        peer=rec.sender,
        state=rec.state,
        error=rec.error,
        steps=_steps(rec.progress),
        **_summary(rec.summary),
    )


@router.post("/transfer/send", response_model=TransferStatus, status_code=202)
def send(body: TransferSendRequest, request: Request) -> TransferStatus:
    """Start moving this account to ``address`` with the code shown there. Runs in the
    background; ask ``/transfer/send/{id}`` how it goes. Refused at once (409) while a
    development is running."""
    scope = _scope(request)
    engine = _engine(request)
    _on(engine)
    address = body.address.strip().rstrip("/")
    if not address.startswith(("http://", "https://")):
        address = f"http://{address}"
    try:
        outgoing.plan(engine, scope)
    except outgoing.Refused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    sending = outgoing.Sending(target=address, owner=scope.owner)
    _desk(request).keep_sending(sending)
    outgoing.start(
        engine,
        scope,
        sending,
        address=address,
        code=body.code,
        http=_client(request),
        name=nearby.machine_name(),
        version=running_version(),
        delete_after=body.delete_after,
    )
    return _sending_status(sending)


@router.get("/transfer/send/{sending_id}", response_model=TransferStatus)
def sending_status(sending_id: str, request: Request) -> TransferStatus:
    scope = _scope(request)
    sending = _desk(request).sending.get(sending_id)
    if sending is None or sending.owner != scope.owner:
        raise HTTPException(status_code=404, detail="no such transfer")
    return _sending_status(sending)


def _sending_status(sending: outgoing.Sending) -> TransferStatus:
    return TransferStatus(
        id=sending.id,
        direction="out",
        peer=sending.target,
        state=sending.state,
        error=sending.error,
        steps=_steps(sending.progress),
        **_summary(sending.summary),
    )


# -- the other installation's side -------------------------------------------------------


@router.get("/transfer/peer/hello", response_model=TransferHello)
def hello(request: Request) -> TransferHello:
    """What this is, to anybody on the network who asks: a name and a version, nothing
    of anybody's."""
    engine = _engine(request)
    _on(engine)
    return TransferHello(
        instance=_instance(engine),
        name=nearby.machine_name(),
        version=running_version(),
        revision=_revision(engine),
    )


@router.post("/transfer/peer/pair", response_model=TransferPaired)
def pair(body: TransferPairRequest, request: Request) -> TransferPaired:
    """The sender's half of the exchange in, the receiver's out. The code is spent."""
    engine = _engine(request)
    _on(engine)
    caller = request.client.host if request.client else "?"
    if engine.store.hit_rate_limit(f"transfer:{caller}", limit=PAIR_LIMIT, window_s=60):
        raise HTTPException(status_code=429, detail="too many attempts; try again in a minute")
    mine = _revision(engine)
    if body.revision != mine:
        raise HTTPException(
            status_code=409,
            detail="the two machines run different versions of Slipwright "
            f"({body.version or 'unknown'} sending, {running_version()} receiving); "
            "update the older one first",
        )
    try:
        message = base64.b64decode(body.message, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="not a key exchange") from exc
    try:
        rec, answer = _desk(request).pair(body.slot, message, body.name or caller)
    except incoming.Rejected as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    log.info("transfer from %s (%s) started", body.name or "?", caller)
    return TransferPaired(
        session=rec.id,
        message=base64.b64encode(answer).decode("ascii"),
        confirm=confirmation(rec.key),
    )


@router.post("/transfer/peer/{session}/part")
async def part(session: str, request: Request) -> dict[str, Any]:
    """One sealed part of a transfer. The body is opaque to anybody without the key."""
    engine = _engine(request)
    _on(engine)
    rec = _desk(request).receiving(session)
    if rec is None:
        raise HTTPException(status_code=404, detail="no such transfer, or it ran out")
    # refused before it is read: anybody on the network can send to this door
    declared = request.headers.get("content-length", "")
    if not declared.isdigit() or int(declared) > incoming.MAX_PART:
        raise HTTPException(status_code=413, detail="a part larger than any sender makes")
    sealed = await request.body()
    try:
        return await run_in_threadpool(incoming.accept, engine, rec, sealed)
    except incoming.Rejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
