"""Secrets at rest: a Fernet key from ``SLIPWRIGHT_SECRET_KEY`` or a file in the state dir.

Tokens for GitHub and Jira are encrypted with this key before they reach SQLite, so a
copy of the database alone reveals nothing. Losing the key means re-entering them.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Mapping
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_ENV = "SLIPWRIGHT_SECRET_KEY"
KEY_FILE = "secret.key"


class SecretBox:
    def __init__(self, key: bytes | str) -> None:
        self._fernet = Fernet(key if isinstance(key, bytes) else key.encode("ascii"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError(
                "cannot decrypt a stored secret: wrong SLIPWRIGHT_SECRET_KEY?"
            ) from exc


def generate_key() -> bytes:
    return Fernet.generate_key()


def load_or_create_key(state_dir: Path, env: Mapping[str, str] | None = None) -> bytes:
    """The key from the environment, else from ``<state_dir>/secret.key`` (created once)."""
    env = os.environ if env is None else env
    if env.get(KEY_ENV):
        return env[KEY_ENV].strip().encode("ascii")
    path = state_dir / KEY_FILE
    if path.is_file():
        return path.read_bytes().strip()
    state_dir.mkdir(parents=True, exist_ok=True)
    key = generate_key()
    path.write_bytes(key + b"\n")
    with contextlib.suppress(OSError):  # best effort on platforms without POSIX modes
        path.chmod(0o600)
    return key


__all__ = ["KEY_ENV", "KEY_FILE", "SecretBox", "generate_key", "load_or_create_key"]
