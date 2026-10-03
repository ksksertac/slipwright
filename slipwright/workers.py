"""The machines an account lends its developments: how one is paired, and when it counts.

A Mac builds what the server cannot -- iOS always, Android on Apple Silicon -- and it
does so by calling out: it polls, so nothing is opened on it and it works behind any
router. What has to get from the server's page to the Mac is therefore two things, the
address to call and a proof that the person who owns the account sent it there. Both
travel in one code:

    SW-0H4K-R8MA-2QZ7-...

The address is the installation's own when it has one. A server opened at ``localhost`` --
a local install, often in Docker, which cannot see the network address of the machine it
runs on -- has none to give, so its code carries only the port and the Mac goes looking:
itself first, then its own network (``worker_agent.pair``). Nobody is asked to look up an
address in ``ipconfig``.

It is packing, not encryption. The address is not a secret; the ten random bytes are, and
they are kept only as a hash, spent on first use and good for fifteen minutes. A check
character catches a code copied with a letter missing before the network is touched.

Crockford's base32: no I, L, O or U, and reading one back forgives O, I and L, since
a code is sometimes read off one screen and typed on another.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import ipaddress
import re
import secrets
import tarfile
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from slipwright.schemas.job import utcnow
from slipwright.workspace import git as g

#: How long a connection code works: time enough to walk to the Mac, not a standing key.
CODE_TTL = timedelta(minutes=15)
#: A worker unheard-of for this long is not there: it polls every ~25 s and sends a
#: heartbeat while it builds, so three missed ones mean it has gone.
LIVE = timedelta(seconds=90)
#: A worktree bigger than this is not shipped to a Mac. node_modules, build output and the
#: like are ignored by git and so never counted; what is left past this is a mistake.
MAX_SNAPSHOT = 200 * 1024 * 1024
#: How the worker gets onto a Mac. Straight from the source: the worker needs none of the
#: web UI -- the one part of the package that is built rather than committed -- so a git
#: install is a whole worker, and needs no tap, release asset or image to exist first.
#: ``uv`` brings the Python it needs.
INSTALL = (
    "brew install uv",
    "uv tool install --force git+https://github.com/ksksertac/slipwright",
)

PREFIX = "SW"
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LOOKALIKE = str.maketrans({"O": "0", "I": "1", "L": "1"})
_VERSION = 1
_SECRET_BYTES = 10
# how the address is packed: an IPv4 address and a port fit in six bytes, which is what
# keeps a LAN code short enough to read; anything else rides as its text. A code made at
# ``localhost`` carries only its port: "this Mac, or one near it". A relay code (T17.3)
# carries the relay's host and the installation's room: "anywhere, through here"
_HTTP_V4, _HTTPS_V4, _URL, _NEARBY, _RELAY, _RELAY_PLAIN = 1, 2, 3, 4, 5, 6
_ROOM = re.compile(r"/v1/rooms/([0-9a-f]{32})")


class CodeError(ValueError):
    """Not a connection code, or not one that survived being copied."""


class AddressNeeded(ValueError):
    """No address at all: not the installation's, and the page sent none."""


def new_secret() -> bytes:
    return secrets.token_bytes(_SECRET_BYTES)


def secret_hash(secret: bytes) -> str:
    return hashlib.sha256(secret).hexdigest()


def pair_key(secret: bytes) -> bytes:
    """What proves the server's key to a machine pairing through the relay (T17.3): only
    the code's holder and the server that made it can compute it, and the relay is neither.
    Kept beside the code's hash for the code's fifteen minutes, then gone with it."""
    return hmac.new(secret, b"slipwright-relay-pair", hashlib.sha256).digest()


def new_token() -> str:
    """What a paired worker authenticates with, from then on. Only its hash is kept."""
    return "swk_" + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def live_since() -> datetime:
    return utcnow() - LIVE


# -- the code ----------------------------------------------------------------------------


def pack(address: str, secret: bytes) -> str:
    """The code a person carries to the Mac."""
    payload = bytes([_VERSION]) + _pack_address(address) + secret
    payload += bytes([zlib.crc32(payload) & 0xFF])
    number = int.from_bytes(payload, "big")
    chars = []
    while number:
        number, digit = divmod(number, 32)
        chars.append(_ALPHABET[digit])
    text = "".join(reversed(chars))
    return f"{PREFIX}-" + "-".join(text[i : i + 4] for i in range(0, len(text), 4))


def unpack(code: str) -> tuple[str, bytes]:
    """(address, secret) out of a code, or ``CodeError`` saying what is wrong with it."""
    text = code.strip().upper().translate(_LOOKALIKE).replace("-", "").replace(" ", "")
    if not text.startswith(PREFIX):
        raise CodeError("not a Slipwright connection code (they start with SW-)")
    text = text[len(PREFIX) :]
    number = 0
    for char in text:
        digit = _ALPHABET.find(char)
        if digit < 0:
            raise CodeError(f"a connection code has no {char!r} in it; check the copy")
        number = number * 32 + digit
    payload = number.to_bytes(max((number.bit_length() + 7) // 8, 1), "big")
    if len(payload) < 2 + _SECRET_BYTES + 1 or payload[0] != _VERSION:
        raise CodeError("this code is incomplete, or from another version of Slipwright")
    body, check = payload[:-1], payload[-1]
    if zlib.crc32(body) & 0xFF != check:
        raise CodeError("this code does not add up: a character is missing or wrong")
    secret = body[-_SECRET_BYTES:]
    return _unpack_address(body[1:-_SECRET_BYTES]), secret


def _pack_address(address: str) -> bytes:
    parts = urlsplit(address)
    room = _ROOM.fullmatch(parts.path)
    if parts.scheme in ("wss", "ws") and room is not None and parts.netloc:
        host = parts.netloc.encode()
        kind = _RELAY if parts.scheme == "wss" else _RELAY_PLAIN  # ws: a test's own relay
        return bytes([kind, len(host)]) + host + bytes.fromhex(room.group(1))
    if parts.scheme == "http" and not reachable(address):
        return bytes([_NEARBY]) + (parts.port or 80).to_bytes(2, "big")
    try:
        ip = ipaddress.IPv4Address(parts.hostname or "")
    except ValueError:
        ip = None
    bare = parts.path in ("", "/") and not parts.query
    if ip is not None and bare and parts.scheme in ("http", "https"):
        port = parts.port or (443 if parts.scheme == "https" else 80)
        kind = _HTTP_V4 if parts.scheme == "http" else _HTTPS_V4
        return bytes([kind]) + ip.packed + port.to_bytes(2, "big")
    return bytes([_URL]) + address.rstrip("/").encode()


def _unpack_address(packed: bytes) -> str:
    if not packed:
        raise CodeError("this code carries no address")
    kind, rest = packed[0], packed[1:]
    if kind in (_HTTP_V4, _HTTPS_V4) and len(rest) == 6:
        scheme = "http" if kind == _HTTP_V4 else "https"
        return f"{scheme}://{ipaddress.IPv4Address(rest[:4])}:{int.from_bytes(rest[4:], 'big')}"
    if kind == _URL:
        return rest.decode(errors="replace")
    if kind == _NEARBY and len(rest) == 2:
        return f"http://localhost:{int.from_bytes(rest, 'big')}"
    if kind in (_RELAY, _RELAY_PLAIN) and rest and len(rest) == 1 + rest[0] + 16:
        host = rest[1 : 1 + rest[0]].decode(errors="replace")
        scheme = "wss" if kind == _RELAY else "ws"
        return f"{scheme}://{host}/v1/rooms/{rest[1 + rest[0] :].hex()}"
    raise CodeError("this code's address cannot be read")


# -- the address -------------------------------------------------------------------------


def reachable(address: str) -> bool:
    """Whether another machine could call this: not loopback, and an http(s) URL."""
    parts = urlsplit(address.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True  # a name: the person knows their network better than this does


def choose_address(*candidates: str | None) -> str:
    """The first address a Mac could reach: the installation's own, then what the page
    was opened at. Failing that, ``localhost`` and its port: the code then says only
    "near you, on this port", and the worker finds the server itself."""
    given = [c.strip() for c in candidates if c and c.strip()]
    for candidate in given:
        if reachable(candidate):
            parts = urlsplit(candidate)
            return f"{parts.scheme}://{parts.netloc}"
    for candidate in given:
        parts = urlsplit(candidate)
        if parts.scheme == "http" and parts.hostname:
            return f"http://localhost:{parts.port or 80}"
    raise AddressNeeded("no address to put in the code")


# -- what a worker builds --------------------------------------------------------------


def snapshot(worktree: Path) -> bytes:
    """The worktree as the gate would see it, as a tar.gz: every file git tracks or would
    track, staged or not. A phase is only committed once it passes, so a commit would be
    last phase's code; ignored files (dependencies, build output) stay behind."""
    names = g.run(worktree, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in sorted(set(filter(None, names.stdout.split("\0")))):
            path = worktree / name
            if path.is_file() and not path.is_symlink():
                tar.add(path, arcname=name, recursive=False)
            if buffer.tell() > MAX_SNAPSHOT:
                raise ValueError(
                    f"the worktree is over {MAX_SNAPSHOT // (1024 * 1024)} MB without its "
                    "ignored files; too big to send to a Mac"
                )
    return buffer.getvalue()


__all__ = [
    "CODE_TTL",
    "LIVE",
    "AddressNeeded",
    "CodeError",
    "choose_address",
    "live_since",
    "new_secret",
    "new_token",
    "pair_key",
    "pack",
    "reachable",
    "secret_hash",
    "snapshot",
    "token_hash",
    "unpack",
]
