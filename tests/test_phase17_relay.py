"""T17.3: a machine on another network pairs and works through the relay, sealed end to end.

The relay here is a few lines of Python that route frames as the Cloudflare one does
(relay/src/frames.ts): host and guests in one room, ``from`` set by the relay. Against it
the server's real host and the worker's real transport talk the real protocol -- which is
what has to hold, wherever the relay runs.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from websockets.asyncio.server import ServerConnection, serve

from slipwright import worker_agent
from slipwright import workers as pairing
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.relay import crypto
from slipwright.relay.guest import RelayGuest
from slipwright.relay.host import RelayHost
from slipwright.relay.messages import Joiner, frames
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

# -- the vectors the desktop app is checked against too ---------------------------------


def test_the_seal_matches_the_vectors_the_desktop_app_is_held_to() -> None:
    client_sk = crypto.unb64("AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=")
    server_sk = crypto.unb64("ZWZnaGlqa2xtbm9wcXJzdHV2d3h5ent8fX5/gIGCg4Q=")
    client_pk, server_pk = crypto.public_key(client_sk), crypto.public_key(server_sk)
    assert crypto.b64(client_pk) == "B6N8vBQgk8i3VdwbEOhstCY3StFqqFPtC9/AsrhtHHw="
    assert crypto.b64(server_pk) == "VxR2nRFr92Q2rnS8eT0sMK0ZA8WaxSc4BcfiaYtBDDY="
    key = crypto.shared_key(client_sk, server_pk, client=client_pk, server=server_pk)
    assert key == crypto.shared_key(server_sk, client_pk, client=client_pk, server=server_pk)
    assert crypto.b64(key) == "kw878q5tUXKJ7G9zxHemHSiN0IYUkrbS2JRfz645FMA="
    _nonce, sealed = crypto.seal(key, b'{"hello":"world"}', crypto.TO_SERVER, bytes(range(12)))
    assert crypto.b64(sealed) == "nXWYcoCnu0lQZYGFxDaVEJ9TQh3b50fsfh4GJV2fYKOC"
    secret = crypto.unb64("yMnKy8zNzs/Q0Q==")
    assert crypto.b64(pairing.pair_key(secret)) == "jzVXSmhT/tM4vZiUgV5E9ddU98ZDO2a34whwsbIzv5A="
    mac = crypto.welcome_mac(pairing.pair_key(secret), server_pk, client_pk)
    assert crypto.b64(mac) == "rWDeEvhZcENAquiPKDXUscUzC2Zz2VQJy793xrGIc/Q="


def test_a_sealed_message_read_the_wrong_way_or_changed_does_not_open() -> None:
    key = bytes(32)
    nonce, sealed = crypto.seal(key, b"poll", crypto.TO_SERVER)
    with pytest.raises(crypto.SealBroken):
        crypto.open_sealed(key, nonce, sealed, crypto.TO_MACHINE)  # reflected back
    with pytest.raises(crypto.SealBroken):
        crypto.open_sealed(key, nonce, bytes([sealed[0] ^ 1]) + sealed[1:], crypto.TO_SERVER)


def test_a_relay_code_carries_the_room_and_survives_being_copied() -> None:
    room = "0f" * 16
    code = pairing.pack(f"wss://relay.slipwright.app/v1/rooms/{room}", bytes(range(10)))
    address, secret = pairing.unpack(code.lower())
    assert address == f"wss://relay.slipwright.app/v1/rooms/{room}"
    assert secret == bytes(range(10))


def test_a_big_message_is_cut_into_parts_and_joined_whatever_the_order() -> None:
    message = {"k": "box", "c": "x" * 1_300_000}
    parts = frames("host", message)
    assert len(parts) == 3
    joiner = Joiner()
    got = None
    for frame in reversed(parts):
        got = joiner.add({**frame, "from": "peer"}) or got
    assert got == ("peer", message)


# -- a relay of our own ---------------------------------------------------------------------


class Relay:
    """Routes frames the way relay/src/frames.ts does, in a thread of its own."""

    def __init__(self) -> None:
        self.host: ServerConnection | None = None
        self.guests: dict[str, ServerConnection] = {}
        self.seen: list[str] = []  # every frame, as the relay could read it
        self.loop = asyncio.new_event_loop()
        self.port = 0
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> Relay:
        self._thread.start()
        assert self._ready.wait(10)
        return self

    def __exit__(self, *exc: object) -> None:
        async def close() -> None:
            self.server.close()
            await self.server.wait_closed()

        asyncio.run_coroutine_threadsafe(close(), self.loop).result(10)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(10)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)

        async def start() -> None:
            self.server = await serve(self._handle, "127.0.0.1", 0, max_size=2**21)
            self.port = self.server.sockets[0].getsockname()[1]
            self._ready.set()

        self.loop.run_until_complete(start())
        self.loop.run_forever()

    async def _handle(self, ws: ServerConnection) -> None:
        path = ws.request.path if ws.request else ""
        if "/host" in path:
            self.host = ws
            async for raw in ws:
                self.seen.append(str(raw))
                frame = json.loads(raw)
                guest = self.guests.get(frame.pop("to"))
                frame["from"] = "host"
                if guest is not None:
                    await guest.send(json.dumps(frame))
            return
        peer = path.split("peer=")[1]
        if self.host is None:
            await ws.close(4004)
            return
        self.guests[peer] = ws
        async for raw in ws:
            self.seen.append(str(raw))
            frame = json.loads(raw)
            frame.pop("to", None)
            frame["from"] = peer
            await self.host.send(json.dumps(frame))


@pytest.fixture
def relay() -> Iterator[Relay]:
    with Relay() as r:
        yield r


@pytest.fixture
def server(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    relay: Relay,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, RelayHost]]:
    """An installation with the relay on, in its room."""
    monkeypatch.setenv("SLIPWRIGHT_RELAY", relay.url)
    engine: Engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        turned = client.put("/api/workers/relay", json={"enabled": True})
        assert turned.status_code == 200 and turned.json()["enabled"], turned.text
        host = RelayHost(store, app=client.app)
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()
        running = asyncio.run_coroutine_threadsafe(host.run(), loop)
        deadline = time.monotonic() + 10
        while relay.host is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert relay.host is not None
        yield client, host
        running.cancel()
        time.sleep(0.1)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(10)


# -- the whole way --------------------------------------------------------------------------


def test_a_machine_pairs_and_works_through_the_relay(
    server: tuple[TestClient, RelayHost], relay: Relay, store: JobStore
) -> None:
    client, _host = server
    made = client.post("/api/workers/code", json={"address": "http://localhost:8500"}).json()
    assert made["address"].startswith(f"{relay.url}/v1/rooms/")  # the room, not the LAN

    config = worker_agent.pair(made["code"], name="far laptop")
    assert config["address"] == made["address"] and config["server_key"]
    listed = client.get("/api/workers").json()
    assert [w["name"] for w in listed] == ["far laptop"]

    store.enqueue_worker_call(
        None, "job", role="backend", domain="backend", phase=1, request=_request()
    )
    worker = worker_agent.Worker(config, found=worker_agent.Found(), name="far laptop")
    got = worker.http.post(
        "/api/worker/poll",
        json={"capabilities": ["write:backend"], "wait_s": 0},
        headers=worker.headers,
    )
    assert got.status_code == 200 and got.json()["kind"] == "write"
    answered = worker.http.post(
        f"/api/worker/calls/{got.json()['id']}/answer",
        json={"text": "{}"},
        headers=worker.headers,
    )
    assert answered.status_code == 204

    # the relay carried all of it and could read none of it
    everything = "\n".join(relay.seen)
    assert "swk_" not in everything and "far laptop" not in everything
    assert made["code"] not in everything and "write:backend" not in everything


def test_a_code_the_server_did_not_make_is_never_answered(
    server: tuple[TestClient, RelayHost], relay: Relay
) -> None:
    client, host = server
    stranger = RelayGuest(f"{relay.url}/v1/rooms/{host.room}", crypto.new_secret_key())
    with pytest.raises(httpx.ConnectError, match="used or has run out"):
        stranger.meet(b"0123456789", wait_s=1.0)
    stranger.close()


def test_a_relay_that_offers_its_own_key_is_not_believed(relay: Relay) -> None:
    """The welcome is signed with the code's pair key; a relay -- or anybody in the room --
    signing with something else is ignored, and the pairing waits for the real one."""
    guest = RelayGuest(f"{relay.url}/v1/rooms/{'ab' * 16}", crypto.new_secret_key())
    guest._welcomes.put(
        {
            "k": "welcome",
            "pk": crypto.b64(crypto.public_key(crypto.new_secret_key())),
            "mac": crypto.b64(bytes(32)),
        }
    )
    relay.host = object()  # type: ignore[assignment]  # a room to be in; nobody answers
    with pytest.raises(httpx.ConnectError):
        guest.meet(b"0123456789", wait_s=0.5)
    assert guest.server is None


def test_a_replayed_request_and_a_path_outside_the_worker_api_are_refused(
    server: tuple[TestClient, RelayHost],
) -> None:
    _client, host = server
    machine = crypto.new_secret_key()
    public = crypto.public_key(machine)
    key = crypto.shared_key(machine, host.public, client=public, server=host.public)

    def ask(request: dict[str, Any]) -> int:
        nonce, sealed = crypto.seal(key, json.dumps(request).encode(), crypto.TO_SERVER)
        box = {
            "k": "box",
            "pk": crypto.b64(public),
            "n": crypto.b64(nonce),
            "c": crypto.b64(sealed),
        }
        answer = asyncio.run(host.open_and_serve(public[:16].hex(), box))
        opened = crypto.open_sealed(
            key, crypto.unb64(answer["n"]), crypto.unb64(answer["c"]), crypto.TO_MACHINE
        )
        return int(json.loads(opened)["status"])

    base = {"ts": int(time.time()), "method": "POST", "headers": {}, "body": ""}
    assert ask({**base, "id": "a1", "path": "/api/worker/heartbeat"}) == 401  # no token
    assert ask({**base, "id": "a1", "path": "/api/worker/heartbeat"}) == 409  # again: replay
    assert ask({**base, "id": "a2", "path": "/api/workers"}) == 404  # not the worker API
    assert ask({**base, "id": "a3", "ts": 1, "path": "/api/worker/heartbeat"}) == 400  # stale
    # and a box that claims to be from a peer whose key it is not is not opened at all
    nonce, sealed = crypto.seal(key, b"{}", crypto.TO_SERVER)
    with pytest.raises(crypto.SealBroken):
        asyncio.run(
            host.open_and_serve(
                "00" * 16,
                {
                    "k": "box",
                    "pk": crypto.b64(public),
                    "n": crypto.b64(nonce),
                    "c": crypto.b64(sealed),
                },
            )
        )


def test_the_relay_is_off_until_somebody_turns_it_on(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        state = client.get("/api/workers/relay").json()
        assert state == {**state, "enabled": False, "connected": False}
        code = client.post("/api/workers/code", json={"address": "http://192.168.1.20:8500"})
        assert code.json()["address"] == "http://192.168.1.20:8500"  # the LAN, as before
        assert store.get_setting("relay.room") is None  # no room made, nothing opened


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
