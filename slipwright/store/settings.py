"""Named settings, mixed into ``JobStore``. Values marked secret are encrypted at rest."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from slipwright.secrets import SecretBox

SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    name       TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    encrypted  INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


class SettingsStoreMixin:
    """Requires ``_conn``, ``_lock``, ``_tx`` and a ``secret_box`` on the host class."""

    _conn: sqlite3.Connection
    _lock: threading.RLock
    _tx: Callable[[], AbstractContextManager[sqlite3.Connection]]
    secret_box: SecretBox

    def get_setting(self, name: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value_json, encrypted FROM settings WHERE name = ?", (name,)
            ).fetchone()
        if row is None:
            return default
        raw = row["value_json"]
        if row["encrypted"]:
            raw = self.secret_box.decrypt(raw)
        return json.loads(raw)

    def set_setting(self, name: str, value: Any, *, secret: bool = False) -> None:
        from slipwright.schemas.job import utcnow

        raw = json.dumps(value)
        if secret:
            raw = self.secret_box.encrypt(raw)
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO settings (name, value_json, encrypted, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                "value_json = excluded.value_json, encrypted = excluded.encrypted, "
                "updated_at = excluded.updated_at",
                (name, raw, int(secret), utcnow().isoformat()),
            )

    def delete_setting(self, name: str) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM settings WHERE name = ?", (name,))

    def setting_is_set(self, name: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM settings WHERE name = ?", (name,)).fetchone()
        return row is not None


__all__ = ["SETTINGS_SCHEMA", "SettingsStoreMixin"]
