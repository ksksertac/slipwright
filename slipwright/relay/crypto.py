"""The seal on everything said through the relay (docs/machines-protocol.md §3).

X25519 to agree a key, HKDF-SHA256 to shape it, ChaCha20-Poly1305 to seal: all three in
``cryptography``, already a dependency, and all three in Node's own ``crypto`` -- so the
desktop app needs no library either, and the two sides are checked against the same
vectors (``tests/test_phase17_relay.py``).

The relay sees who talks to whom and how much. It cannot read a word, cannot change one
without the seal breaking, and cannot pass itself off as the server: the server's key is
proved to a pairing machine with a key only the code's holder and the server can compute.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

INFO = b"slipwright-relay-v1"
#: A guest's request and the host's answer are sealed for different directions, so the
#: relay cannot hand a request back to its sender as if it were the answer.
TO_SERVER = b"c2s"
TO_MACHINE = b"s2c"


class SealBroken(ValueError):
    """Not sealed by who it says, or changed on the way."""


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def new_secret_key() -> bytes:
    return X25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )


def public_key(secret_key: bytes) -> bytes:
    return (
        X25519PrivateKey.from_private_bytes(secret_key)
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )


def shared_key(secret_key: bytes, their_public: bytes, *, client: bytes, server: bytes) -> bytes:
    """The key one machine and the server share. ``client`` and ``server`` are the two
    public keys, in that order whichever side asks, so both derive the same one."""
    try:
        agreed = X25519PrivateKey.from_private_bytes(secret_key).exchange(
            X25519PublicKey.from_public_bytes(their_public)
        )
    except ValueError as exc:  # a key of the wrong length, or the all-zero point
        raise SealBroken(f"not a usable key: {exc}") from exc
    return HKDF(hashes.SHA256(), 32, salt=client + server, info=INFO).derive(agreed)


def seal(
    key: bytes, plaintext: bytes, direction: bytes, nonce: bytes | None = None
) -> tuple[bytes, bytes]:
    """(nonce, ciphertext ‖ tag). A fresh random nonce unless a test pins one."""
    nonce = nonce or os.urandom(12)
    return nonce, ChaCha20Poly1305(key).encrypt(nonce, plaintext, direction)


def open_sealed(key: bytes, nonce: bytes, ciphertext: bytes, direction: bytes) -> bytes:
    try:
        return ChaCha20Poly1305(key).decrypt(nonce, ciphertext, direction)
    except InvalidTag as exc:
        raise SealBroken("the seal does not hold") from exc


def code_id(secret: bytes) -> str:
    """How a pairing machine names its code without showing it: the hash the server
    already keeps (``workers.secret_hash``)."""
    return hashlib.sha256(secret).hexdigest()


def welcome_mac(pair_key: bytes, server_public: bytes, client_public: bytes) -> bytes:
    """What proves to a pairing machine that ``server_public`` is the server's: only the
    code's holder and the server that made the code know ``pair_key``."""
    return hmac.new(pair_key, server_public + client_public, hashlib.sha256).digest()


__all__ = [
    "TO_MACHINE",
    "TO_SERVER",
    "SealBroken",
    "b64",
    "code_id",
    "new_secret_key",
    "open_sealed",
    "public_key",
    "seal",
    "shared_key",
    "unb64",
    "welcome_mac",
]
