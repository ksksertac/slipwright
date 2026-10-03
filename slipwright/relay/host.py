"""The server's end of the relay (T17.3): out to its room, and the worker API through it.

An installation behind a home router cannot be called; it can call out. So when somebody
turns *Reach machines on other networks* on, the server opens one WebSocket to its room on
the relay and keeps it open, and a machine anywhere reaches it through that. Every
request arrives sealed (``crypto``); it is opened here, checked, and served by the very
same ``/api/worker/`` endpoints a machine on the LAN calls -- in process, through the ASGI
app -- so there is one worker API, not two that drift. Anything outside ``/api/worker/``
is refused: the relay is a door for machines, not a way into the account.

Off by default. Nothing leaves an installation unasked, and a hosted one that never turns
it on never opens the connection at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from slipwright.relay import crypto
from slipwright.relay.messages import Joiner, frames

log = logging.getLogger(__name__)

#: Where rooms are, unless the installation names its own relay; ``off`` is never.
DEFAULT_RELAY = "wss://relay.slipwright.app"
ENABLED = "relay.enabled"
ROOM = "relay.room"
TOKEN = "relay.host_token"
SECRET = "relay.secret_key"
#: How far a request's clock may be from ours: past it, it is a replay or a broken clock.
SKEW_S = 300.0
#: Only these are served through the relay.
WORKER_API = "/api/worker/"


def relay_url() -> str | None:
    """The relay this installation would use, or None when the operator said ``off``."""
    url = os.environ.get("SLIPWRIGHT_RELAY", DEFAULT_RELAY).strip().rstrip("/")
    return None if not url or url.lower() == "off" else url


def enabled(store: Any) -> bool:
    return relay_url() is not None and store.get_setting(ENABLED) is True


def identity(store: Any) -> tuple[str, str, bytes]:
    """(room, host token, secret key), made the first time and kept: a room that changed
    would strand every machine paired through it. Installation settings, never an
    account's, and never carried by a move -- they describe this machine."""
    room = store.get_setting(ROOM)
    token = store.get_setting(TOKEN)
    secret = store.get_setting(SECRET)
    if not (isinstance(room, str) and isinstance(token, str) and isinstance(secret, str)):
        room, token = secrets.token_hex(16), secrets.token_hex(32)
        secret = crypto.b64(crypto.new_secret_key())
        store.set_setting(ROOM, room)
        store.set_setting(TOKEN, token, secret=True)
        store.set_setting(SECRET, secret, secret=True)
    return room, token, crypto.unb64(secret)


def room_address(store: Any) -> str | None:
    """What a connection code carries when the relay is on: the room, on the relay."""
    url = relay_url()
    if url is None or not enabled(store):
        return None
    room, _token, _secret = identity(store)
    return f"{url}/v1/rooms/{room}"


Serve = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class RelayHost:
    """One installation, in its room. ``serve`` answers an opened request; by default the
    ASGI app it is given, which is the server's own worker API."""

    def __init__(
        self,
        store: Any,
        *,
        app: Any = None,
        serve: Serve | None = None,
        url: str | None = None,
        connect: Any = None,
    ) -> None:
        self.store = store
        self.url = url or relay_url() or DEFAULT_RELAY
        room, token, secret = identity(store)
        self.room = room
        self.token = token
        self.secret = secret
        self.public = crypto.public_key(secret)
        self._serve = serve or _asgi(app)
        self._connect = connect
        self._seen: dict[str, float] = {}
        self.connected = asyncio.Event()

    async def run(self) -> None:
        """Stay in the room until cancelled. A relay that drops us is called again, waiting
        longer each time up to a minute: the machines wait out a server restart the same
        way, so nobody has to do anything when the network comes back."""
        if self._connect is None:
            from websockets.asyncio.client import connect

            self._connect = connect
        pause = 1.0
        address = f"{self.url}/v1/rooms/{self.room}/host?token={self.token}"
        while True:
            try:
                async with self._connect(address, max_size=2**20 + 4096) as ws:
                    pause = 1.0
                    self.connected.set()
                    log.info("relay: in room %s at %s", self.room[:8], self.url)
                    await self._listen(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a dropped relay is waited out
                log.warning("relay: %s; trying again in %.0fs", exc, pause)
            finally:
                self.connected.clear()
            await asyncio.sleep(pause)
            pause = min(pause * 2, 60.0)

    async def _listen(self, ws: Any) -> None:
        joiner = Joiner()
        lock = asyncio.Lock()
        tasks: set[asyncio.Task[None]] = set()

        async def send(to: str, message: dict[str, Any]) -> None:
            async with lock:  # one message's parts are not interleaved with another's
                for frame in frames(to, message):
                    await ws.send(json.dumps(frame, separators=(",", ":")))

        async for raw in ws:
            try:
                frame = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(frame, dict) or "error" in frame:
                continue  # the relay's own word about a frame: nothing to answer
            whole = joiner.add(frame)
            if whole is None:
                continue
            task = asyncio.create_task(self._answer(send, *whole))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

    async def _answer(
        self, send: Callable[[str, dict[str, Any]], Awaitable[None]], peer: str, msg: dict[str, Any]
    ) -> None:
        try:
            if msg.get("k") == "hello":
                welcome = self.welcome(peer, msg)
                if welcome is not None:
                    await send(peer, welcome)
            elif msg.get("k") == "box":
                await send(peer, await self.open_and_serve(peer, msg))
        except crypto.SealBroken as exc:
            log.info("relay: refused a message from %s: %s", peer[:8], exc)
        except Exception:  # noqa: BLE001 - one bad message must not end the room
            log.exception("relay: answering %s failed", peer[:8])

    def welcome(self, peer: str, hello: dict[str, Any]) -> dict[str, Any] | None:
        """The server's key, proved with the code's pair key. A code it does not know --
        used, run out, never made -- gets no answer, so a stranger learns nothing."""
        try:
            client = crypto.unb64(str(hello["pk"]))
            key = self.store.worker_code_pair_key(str(hello["code_id"]))
        except (KeyError, ValueError):
            return None
        if key is None or len(client) != 32 or peer != client[:16].hex():
            return None
        mac = crypto.welcome_mac(bytes.fromhex(key), self.public, client)
        return {"k": "welcome", "pk": crypto.b64(self.public), "mac": crypto.b64(mac)}

    async def open_and_serve(self, peer: str, box: dict[str, Any]) -> dict[str, Any]:
        client = crypto.unb64(str(box.get("pk", "")))
        if len(client) != 32 or peer != client[:16].hex():
            raise crypto.SealBroken("the key is not the sender's")
        key = crypto.shared_key(self.secret, client, client=client, server=self.public)
        request = json.loads(
            crypto.open_sealed(
                key, crypto.unb64(str(box["n"])), crypto.unb64(str(box["c"])), crypto.TO_SERVER
            )
        )
        answer = self._check(request) or await self._serve(request)
        answer["id"] = request.get("id")
        nonce, sealed = crypto.seal(
            key, json.dumps(answer, separators=(",", ":")).encode(), crypto.TO_MACHINE
        )
        return {
            "k": "box",
            "pk": crypto.b64(self.public),
            "n": crypto.b64(nonce),
            "c": crypto.b64(sealed),
        }

    def _check(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """An answer of refusal, or None when the request may be served."""
        now = time.time()
        self._seen = {k: t for k, t in self._seen.items() if now - t < 2 * SKEW_S}
        rid = str(request.get("id") or "")
        path = str(request.get("path") or "")
        if not rid or rid in self._seen:
            return _refusal(409, "this request was already answered")
        if abs(now - float(request.get("ts") or 0)) > SKEW_S:
            return _refusal(400, "this request's clock is more than five minutes out")
        if not path.startswith(WORKER_API) or ".." in path:
            return _refusal(404, "only the worker API is reachable through the relay")
        self._seen[rid] = now
        return None


def _refusal(status: int, detail: str) -> dict[str, Any]:
    body = json.dumps({"detail": detail}).encode()
    return {
        "status": status,
        "headers": {"content-type": "application/json"},
        "body": crypto.b64(body),
    }


def _asgi(app: Any) -> Serve:
    """Serve an opened request with the app's own routes, as if it had come in the door."""

    async def serve(request: dict[str, Any]) -> dict[str, Any]:
        headers = {
            k: v
            for k, v in dict(request.get("headers") or {}).items()
            if k.lower() in ("authorization", "content-type", "x-slipwright-protocol")
        }
        body = crypto.unb64(str(request.get("body") or "")) if request.get("body") else b""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://relay") as client:
            got = await client.request(
                str(request.get("method") or "GET"),
                str(request["path"]),
                headers=headers,
                content=body,
                timeout=None,
            )
        return {
            "status": got.status_code,
            "headers": {"content-type": got.headers.get("content-type", "")},
            "body": crypto.b64(got.content),
        }

    return serve


class Keeper:
    """Keeps the server in its room while the setting says so, and out of it when not:
    turning the switch on the Machines page takes effect within ``tick_s``."""

    def __init__(self, store: Any, app: Any, *, tick_s: float = 5.0) -> None:
        self.store = store
        self.app = app
        self.tick_s = tick_s
        self.host: RelayHost | None = None
        self._task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        try:
            while True:
                want = await asyncio.to_thread(enabled, self.store)
                if want and self._task is None:
                    self.host = await asyncio.to_thread(RelayHost, self.store, app=self.app)
                    self._task = asyncio.create_task(self.host.run())
                elif not want and self._task is not None:
                    self._task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await self._task
                    self._task, self.host = None, None
                await asyncio.sleep(self.tick_s)
        finally:
            if self._task is not None:
                self._task.cancel()


__all__ = [
    "DEFAULT_RELAY",
    "ENABLED",
    "Keeper",
    "RelayHost",
    "enabled",
    "identity",
    "relay_url",
    "room_address",
]
