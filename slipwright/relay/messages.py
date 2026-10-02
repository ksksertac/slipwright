"""Messages cut into frames the relay will carry, and joined again (protocol §3).

The relay takes frames of up to 1 MiB of JSON text. A request is small; a build's
snapshot can be two hundred megabytes. So every message is cut into parts of at most
``PART`` bytes of payload, each a frame of its own, and the receiver joins them by
``mid`` in order. Base64 inflates by a third, which is what keeps a part well under the
frame limit.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from slipwright.relay.crypto import b64, unb64

PART = 512 * 1024
#: A message whose parts stop arriving is dropped after this: a guest that went away
#: halfway through sending must not hold its pieces in the server's memory for ever.
STALE_S = 120.0
#: The most parts one message may have (~256 MB): more is not a message, it is a flood.
MAX_PARTS = 512


def new_mid() -> str:
    return secrets.token_hex(8)


def frames(to: str, message: dict[str, Any]) -> list[dict[str, Any]]:
    """``message`` as the frames that carry it to ``to``."""
    data = json.dumps(message, separators=(",", ":")).encode()
    mid = new_mid()
    chunks = [data[i : i + PART] for i in range(0, len(data), PART)] or [b""]
    return [
        {"to": to, "mid": mid, "part": n, "parts": len(chunks), "data": b64(chunk)}
        for n, chunk in enumerate(chunks)
    ]


class Joiner:
    """Collects parts per (sender, mid) and hands back whole messages."""

    def __init__(self) -> None:
        self._open: dict[tuple[str, str], tuple[float, list[bytes | None]]] = {}

    def add(self, frame: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
        """(sender, message) once the last part is in; None until then, or for a frame
        that is not a well-formed part (ignored, never raised: anyone can send one)."""
        try:
            sender = str(frame["from"])
            mid = str(frame["mid"])
            part = int(frame["part"])
            parts = int(frame["parts"])
            data = unb64(str(frame["data"]))
        except (KeyError, TypeError, ValueError):
            return None
        if not 0 < parts <= MAX_PARTS or not 0 <= part < parts:
            return None
        now = time.monotonic()
        self._open = {k: v for k, v in self._open.items() if now - v[0] < STALE_S}
        started, pieces = self._open.setdefault((sender, mid), (now, [None] * parts))
        if len(pieces) != parts:
            return None
        pieces[part] = data
        if any(p is None for p in pieces):
            return None
        del self._open[(sender, mid)]
        try:
            message = json.loads(b"".join(p for p in pieces if p is not None))
        except ValueError:
            return None
        return (sender, message) if isinstance(message, dict) else None


__all__ = ["PART", "Joiner", "frames", "new_mid"]
