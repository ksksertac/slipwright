"""The code a person carries between two screens, and the channel it opens.

The receiving machine shows a code; the person types it on the sending one. Whatever
crosses the network after that carries every model key and Git token the account has,
in the clear as far as the payload is concerned -- the receiver has a different
``secret.key`` and must re-encrypt them -- over plain HTTP on a home network. So the code
is not a password sent to be checked. It is the input to a PAKE (SPAKE2, the exchange
magic-wormhole uses): both sides derive one key from it without the code, or anything a
listener could test a guess against, ever crossing the wire.

That is what lets the code be short enough to type in the thirty seconds it is shown
for. Forty bits would be nothing against an offline search, but there is no offline
search to make: a guess can only be tried by running the exchange with the receiver, and
the receiver spends a code on its first attempt, right or wrong.

    SW-K3M9-QX7A-2PRT
       ^^^ ^^^^ ^^^^ ^
       slot  secret   check

The slot is public -- it only says which of the receiver's codes is meant, so one that
has just been replaced can still be typed -- the secret is the PAKE password, and the
check character catches a mistyped code before it is spent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import struct
import zlib
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from spake2 import SPAKE2_A, SPAKE2_B  # type: ignore[import-untyped]

PREFIX = "SW"
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LOOKALIKE = str.maketrans({"O": "0", "I": "1", "L": "1"})
_SLOT, _SECRET = 3, 8
_LENGTH = _SLOT + _SECRET + 1
# who is who in the exchange: SPAKE2 binds the key to both names, so a message replayed in
# the other direction does not fit
_SENDER, _RECEIVER = b"slipwright-transfer-sender", b"slipwright-transfer-receiver"


class CodeError(ValueError):
    """Not a transfer code, or not one that survived being typed."""


class ChannelError(ValueError):
    """The two sides did not agree on a key, or a part did not open with it."""


def _check(chars: str) -> str:
    return _ALPHABET[zlib.crc32(chars.encode()) % 32]


def new_code() -> tuple[str, str, str]:
    """(code, slot, secret): a fresh code and its two halves."""
    slot = "".join(secrets.choice(_ALPHABET) for _ in range(_SLOT))
    secret = "".join(secrets.choice(_ALPHABET) for _ in range(_SECRET))
    body = slot + secret
    text = body + _check(body)
    return f"{PREFIX}-" + "-".join(text[i : i + 4] for i in range(0, _LENGTH, 4)), slot, secret


def parse_code(code: str) -> tuple[str, str]:
    """(slot, secret) out of what somebody typed, or ``CodeError`` saying what is wrong."""
    text = code.strip().upper().translate(_LOOKALIKE)
    text = "".join(c for c in text if c.isalnum())
    if text.startswith(PREFIX) and len(text) == _LENGTH + len(PREFIX):
        text = text[len(PREFIX) :]
    if len(text) != _LENGTH:
        raise CodeError(f"a transfer code has {_LENGTH} characters after SW-")
    for char in text:
        if char not in _ALPHABET:
            raise CodeError(f"a transfer code has no {char!r} in it; check the copy")
    body, check = text[:-1], text[-1]
    if _check(body) != check:
        raise CodeError("this code does not add up: a character is missing or wrong")
    return body[:_SLOT], body[_SLOT:]


# -- the exchange ------------------------------------------------------------------------


class SenderHandshake:
    """The sending side: ``start`` once, ``finish`` with the receiver's answer."""

    def __init__(self, secret: str) -> None:
        self._spake = SPAKE2_A(secret.encode(), idA=_SENDER, idB=_RECEIVER)

    def start(self) -> bytes:
        message: bytes = self._spake.start()
        return message

    def finish(self, message: bytes, confirm: str) -> bytes:
        """The shared key, once the receiver has shown it holds the same one."""
        try:
            key: bytes = self._spake.finish(message)
        except Exception as exc:  # noqa: BLE001 - spake2 raises its own bare errors
            raise ChannelError("the other side's answer is not a key exchange") from exc
        if not hmac.compare_digest(confirmation(key), confirm):
            raise ChannelError("the code did not match")
        return key


def receive_handshake(secret: str, message: bytes) -> tuple[bytes, bytes]:
    """The receiving side, in one step: (its answer, the shared key)."""
    spake = SPAKE2_B(secret.encode(), idA=_SENDER, idB=_RECEIVER)
    answer: bytes = spake.start()
    try:
        key: bytes = spake.finish(message)
    except Exception as exc:  # noqa: BLE001
        raise ChannelError("not a key exchange") from exc
    return answer, key


def confirmation(key: bytes) -> str:
    """What the receiver sends back to prove it derived the same key. A wrong code
    gives a different key, so the sender learns it before sending a single row."""
    return hmac.new(key, b"receiver confirms", hashlib.sha256).hexdigest()


# -- parts -------------------------------------------------------------------------------


@dataclass
class Part:
    """One message of a transfer: what it is (``header``) and its bytes (``body``)."""

    header: dict[str, Any]
    body: bytes = b""


def _aead(key: bytes) -> AESGCM:
    return AESGCM(hashlib.sha256(b"slipwright transfer data" + key).digest())


def _aad(session: str, seq: int) -> bytes:
    # the session and the part's place in it are bound into each part: one replayed,
    # reordered or carried over from another transfer does not open
    return f"{session}:{seq}".encode()


def seal(key: bytes, session: str, seq: int, part: Part) -> bytes:
    header = json.dumps(part.header, separators=(",", ":")).encode()
    frame = struct.pack(">I", len(header)) + header + part.body
    nonce = os.urandom(12)
    return nonce + _aead(key).encrypt(nonce, frame, _aad(session, seq))


def unseal(key: bytes, session: str, seq: int, sealed: bytes) -> Part:
    if len(sealed) < 12 + 16 + 4:
        raise ChannelError("a part too short to be one")
    try:
        frame = _aead(key).decrypt(sealed[:12], sealed[12:], _aad(session, seq))
    except InvalidTag as exc:
        raise ChannelError("a part did not open with this transfer's key") from exc
    (size,) = struct.unpack(">I", frame[:4])
    header = json.loads(frame[4 : 4 + size])
    if not isinstance(header, dict):
        raise ChannelError("a part without a header")
    return Part(header=header, body=frame[4 + size :])


__all__ = [
    "ChannelError",
    "CodeError",
    "Part",
    "SenderHandshake",
    "confirmation",
    "new_code",
    "parse_code",
    "receive_handshake",
    "seal",
    "unseal",
]
