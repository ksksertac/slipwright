"""A machine's end of the relay, for ``slipwright worker`` (T17.3).

The worker already speaks HTTP to the worker API through an ``httpx.Client``. Through the
relay it still does: ``RelayTransport`` is an httpx transport that seals each request,
sends it to the room, and opens the answer -- so the worker's loop is the same code on a
LAN and across the world, and only the client it is handed differs.

Pairing is the one exchange that is not a request: before it the machine does not know
the server's key, and the relay could offer its own. ``meet`` asks for the key and checks
it against the code's secret, which the relay never sees.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import queue
import secrets
import threading
import time
from typing import Any

import httpx

from slipwright import workers as pairing
from slipwright.relay import crypto
from slipwright.relay.messages import Joiner, frames

#: How long a request waits for its answer when httpx gives no read timeout of its own.
DEFAULT_WAIT_S = 120.0


class RelayGuest:
    """One machine in one room: a socket, a reader that sorts answers to their requests,
    and the keys. ``address`` is ``wss://relay/v1/rooms/<room>``, as a code carries it."""

    def __init__(
        self,
        address: str,
        secret_key: bytes,
        server_public: bytes | None = None,
        *,
        connect: Any = None,
    ) -> None:
        self.address = address.rstrip("/")
        self.secret = secret_key
        self.public = crypto.public_key(secret_key)
        self.server = server_public
        self._connect = connect
        self._ws: Any = None
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._waiting: dict[str, queue.Queue[dict[str, Any] | Exception]] = {}
        self._welcomes: queue.Queue[dict[str, Any]] = queue.Queue()

    @property
    def peer(self) -> str:
        return self.public[:16].hex()

    # -- the socket -------------------------------------------------------------------------

    def _socket(self) -> Any:
        with self._lock:
            if self._ws is not None:
                return self._ws
            if self._connect is None:
                from websockets.sync.client import connect

                self._connect = connect
            try:
                # entered by hand: the socket outlives any one block of code here, and
                # websockets 17 warns about a connection that was never entered at all
                ws = self._connect(
                    f"{self.address}/guest?peer={self.peer}", max_size=2**20 + 4096
                ).__enter__()
            except Exception as exc:  # noqa: BLE001 - said as the network failure it is
                raise httpx.ConnectError(f"cannot reach the relay: {exc}") from exc
            self._ws = ws
            threading.Thread(target=self._read, args=(ws,), daemon=True).start()
            return ws

    def _read(self, ws: Any) -> None:
        joiner = Joiner()
        why: Exception = httpx.ReadError("the relay closed the connection")
        try:
            for raw in ws:
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    continue
                if "error" in frame:
                    # the relay's word, about *some* frame of ours: the only one that is
                    # everybody's problem is the server not being in its room
                    if frame["error"] == "host-offline":
                        self._fail_all(
                            httpx.ConnectError("the server is not connected to the relay")
                        )
                    continue
                whole = joiner.add(frame)
                if whole is not None and whole[0] == "host":
                    self._deliver(whole[1])
        except Exception as exc:  # noqa: BLE001 - whatever ended the socket ends the waits
            why = httpx.ReadError(f"the relay connection broke: {exc}")
            code = getattr(getattr(exc, "rcvd", None), "code", None)
            if code == 4004:
                why = httpx.ConnectError("the server is not connected to the relay")
        finally:
            with self._lock:
                if self._ws is ws:
                    self._ws = None
            self._fail_all(why)

    def _deliver(self, message: dict[str, Any]) -> None:
        if message.get("k") == "welcome":
            self._welcomes.put(message)
            return
        if message.get("k") != "box" or self.server is None:
            return
        try:
            key = self._key()
            answer = json.loads(
                crypto.open_sealed(
                    key,
                    crypto.unb64(str(message["n"])),
                    crypto.unb64(str(message["c"])),
                    crypto.TO_MACHINE,
                )
            )
        except (crypto.SealBroken, KeyError, ValueError):
            return  # not the server's: dropped, and the request it claims to answer waits on
        waiter = self._waiting.get(str(answer.get("id")))
        if waiter is not None:
            waiter.put(answer)

    def _fail_all(self, why: Exception) -> None:
        for waiter in list(self._waiting.values()):
            waiter.put(why)

    def _send(self, message: dict[str, Any]) -> None:
        ws = self._socket()
        with self._send_lock:
            try:
                for frame in frames("host", message):
                    ws.send(json.dumps(frame, separators=(",", ":")))
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    if self._ws is ws:
                        self._ws = None
                raise httpx.WriteError(f"the relay connection broke: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                ws.close()

    # -- pairing and requests -----------------------------------------------------------------

    def meet(self, secret: bytes, wait_s: float = 20.0) -> bytes:
        """The server's key, proved: asked with the code's id and checked with its pair key.
        The relay can answer with a key of its own, but cannot sign one."""
        self._send({"k": "hello", "pk": crypto.b64(self.public), "code_id": crypto.code_id(secret)})
        deadline = time.monotonic() + wait_s
        while True:
            try:
                welcome = self._welcomes.get(timeout=max(deadline - time.monotonic(), 0.01))
            except queue.Empty as exc:
                raise httpx.ConnectError(
                    "the server did not answer: the code has been used or has run out, "
                    "or the server is not connected to the relay"
                ) from exc
            try:
                server = crypto.unb64(str(welcome["pk"]))
                mac = crypto.unb64(str(welcome["mac"]))
            except (KeyError, ValueError):
                continue
            expected = crypto.welcome_mac(pairing.pair_key(secret), server, self.public)
            if hmac.compare_digest(mac, expected):
                self.server = server
                return server
            # a welcome that does not add up is somebody else's: keep waiting for the server

    def request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
        wait_s: float = DEFAULT_WAIT_S,
    ) -> tuple[int, dict[str, str], bytes]:
        if self.server is None:
            raise httpx.ConnectError("not paired through this relay")
        rid = secrets.token_hex(8)
        plain = {
            "id": rid,
            "ts": int(time.time()),
            "method": method,
            "path": path,
            "headers": headers,
            "body": crypto.b64(body),
        }
        nonce, sealed = crypto.seal(
            self._key(), json.dumps(plain, separators=(",", ":")).encode(), crypto.TO_SERVER
        )
        waiter: queue.Queue[dict[str, Any] | Exception] = queue.Queue()
        self._waiting[rid] = waiter
        try:
            self._send(
                {
                    "k": "box",
                    "pk": crypto.b64(self.public),
                    "n": crypto.b64(nonce),
                    "c": crypto.b64(sealed),
                }
            )
            try:
                got = waiter.get(timeout=wait_s)
            except queue.Empty as exc:
                raise httpx.ReadTimeout("no answer through the relay in time") from exc
        finally:
            self._waiting.pop(rid, None)
        if isinstance(got, Exception):
            raise got
        return (
            int(got.get("status") or 502),
            dict(got.get("headers") or {}),
            crypto.unb64(str(got.get("body") or "")),
        )

    def _key(self) -> bytes:
        assert self.server is not None
        return crypto.shared_key(self.secret, self.server, client=self.public, server=self.server)


class RelayTransport(httpx.BaseTransport):
    """httpx through the relay: what ``slipwright worker`` is handed instead of the network."""

    def __init__(self, guest: RelayGuest) -> None:
        self.guest = guest

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        timeouts = request.extensions.get("timeout") or {}
        wait = timeouts.get("read") or DEFAULT_WAIT_S
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() in ("authorization", "content-type")
        }
        status, got_headers, content = self.guest.request(
            request.method,
            request.url.raw_path.decode(),
            headers,
            request.read(),
            wait_s=float(wait) + 10,
        )
        return httpx.Response(status, headers=got_headers, content=content, request=request)

    def close(self) -> None:
        self.guest.close()


def is_relay(address: str) -> bool:
    return address.startswith(("wss://", "ws://"))


__all__ = ["RelayGuest", "RelayTransport", "is_relay"]
