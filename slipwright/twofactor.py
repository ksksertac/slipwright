"""Two-step sign-in: a six-digit code from an authenticator app, after the password.

Time-based one-time passwords (RFC 6238, the scheme every authenticator app speaks) are
twenty lines of the standard library, so they are written here rather than depended on.
The only dependency is ``segno``, which draws the QR code the app scans -- typing a
32-letter secret into a phone is where people give up.

It is **optional and per person**. Nothing turns it on for somebody: a local install
that has worked for months must not wake up to a login it cannot pass. The setup wizard
offers it once, with a "skip for now", and the Security page keeps offering it.

What protects what:

* The secret is stored encrypted with the installation key, like every other credential,
  because unlike a password hash it *is* the key: a copy of it makes codes forever.
* A code is accepted once. The last time step used is remembered, so a code read over
  somebody's shoulder is worth nothing thirty seconds later -- or even within them.
* Recovery codes are the way in when the phone is lost. Each works once and only their
  hashes are kept; they are shown a single time, when two-step sign-in is turned on.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

import segno

DIGITS = 6
PERIOD = 30
#: Steps either side of now that still count. One: a phone whose clock is half a minute
#: off, or a code typed as it rolled over, is the everyday case, not an attack.
DRIFT = 1
ISSUER = "Slipwright"
RECOVERY_CODES = 8
# no 0/O or 1/I/L: a recovery code is read off paper, often years later
_RECOVERY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def new_secret() -> str:
    """160 random bits, base32 as the apps expect, without the padding they choke on."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def code_at(secret: str, step: int) -> str:
    """The code an authenticator app shows during ``step`` (RFC 4226's truncation)."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    (value,) = struct.unpack(">I", digest[offset : offset + 4])
    return str((value & 0x7FFFFFFF) % 10**DIGITS).zfill(DIGITS)


def matching_step(
    secret: str, code: str, *, after: int = -1, now: float | None = None
) -> int | None:
    """The time step ``code`` belongs to, or ``None``.

    ``after`` is the last step already spent: a code from it or before is refused even
    though it is arithmetically right, which is what makes each code good for one use.
    """
    code = "".join(code.split())
    if len(code) != DIGITS or not code.isdigit():
        return None
    now_step = current_step(now)
    for step in range(now_step - DRIFT, now_step + DRIFT + 1):
        # compare_digest so the time taken says nothing about how many digits were right
        if step > after and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def provisioning_uri(secret: str, account: str) -> str:
    """What the QR code holds: the ``otpauth://`` link authenticator apps understand."""
    label = quote(f"{ISSUER}:{account}", safe=":@")
    query = urlencode({"secret": secret, "issuer": ISSUER, "digits": DIGITS, "period": PERIOD})
    return f"otpauth://totp/{label}?{query}"


def qr_svg(uri: str) -> str:
    """The QR code as an SVG ``data:`` URI, ready for an ``<img>``.

    Drawn here rather than in the browser so the web client needs no QR library, and
    black on white whatever the theme: a scanner is not reading the page's colours."""
    return str(segno.make(uri, error="m").svg_data_uri(scale=5, border=2))


def new_recovery_codes() -> list[str]:
    """Codes for the day the phone is lost, grouped ``XXXXX-XXXXX`` to be copied by hand."""

    def one() -> str:
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        return f"{raw[:5]}-{raw[5:]}"

    return [one() for _ in range(RECOVERY_CODES)]


def recovery_hash(code: str) -> str:
    """Case, spaces and the dash do not matter: a code copied from paper is still the code."""
    canonical = "".join(c for c in code.upper() if c.isalnum())
    return hashlib.sha256(canonical.encode("ascii", "ignore")).hexdigest()


__all__ = [
    "DIGITS",
    "ISSUER",
    "code_at",
    "current_step",
    "matching_step",
    "new_recovery_codes",
    "new_secret",
    "provisioning_uri",
    "qr_svg",
    "recovery_hash",
]
