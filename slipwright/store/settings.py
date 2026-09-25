"""Named settings, mixed into ``JobStore``. Values marked secret are encrypted at rest.

Every setting belongs either to one account or to the installation. Which is which is the
caller's decision, not this module's: it takes a ``user_id`` and stores what it is given.
``INSTALLATION`` -- the empty string -- is the installation's own row, and is what every
caller that predates accounts gets by default, so nothing moved when accounts arrived.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, select

from slipwright.secrets import SecretBox
from slipwright.store.db import Database, one
from slipwright.store.schema import settings

#: The owner of a setting that belongs to the whole installation rather than to a person.
INSTALLATION = ""


class SettingsStoreMixin:
    """Requires ``db`` and a ``secret_box`` on the host class."""

    db: Database
    secret_box: SecretBox

    def get_setting(
        self, name: str, default: Any = None, *, user_id: str = INSTALLATION
    ) -> Any:
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(settings).where(
                        settings.c.user_id == user_id, settings.c.name == name
                    )
                )
            )
        if row is None:
            return default
        raw = row["value_json"]
        if row["encrypted"]:
            raw = self.secret_box.decrypt(raw)
        return json.loads(raw)

    def set_setting(
        self,
        name: str,
        value: Any,
        *,
        secret: bool = False,
        user_id: str = INSTALLATION,
    ) -> None:
        from slipwright.schemas.job import utcnow

        raw = json.dumps(value)
        if secret:
            raw = self.secret_box.encrypt(raw)
        with self.db.begin() as conn:
            conn.execute(
                self.db.upsert(
                    settings,
                    {
                        "user_id": user_id,
                        "name": name,
                        "value_json": raw,
                        "encrypted": int(secret),
                        "updated_at": utcnow().isoformat(),
                    },
                    key=["user_id", "name"],
                    update=["value_json", "encrypted", "updated_at"],
                )
            )

    def delete_setting(self, name: str, *, user_id: str = INSTALLATION) -> None:
        with self.db.begin() as conn:
            conn.execute(
                delete(settings).where(
                    settings.c.user_id == user_id, settings.c.name == name
                )
            )

    def setting_is_set(self, name: str, *, user_id: str = INSTALLATION) -> bool:
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(settings.c.name).where(
                        settings.c.user_id == user_id, settings.c.name == name
                    )
                )
            )
        return row is not None

    def forget_settings(self, user_id: str) -> None:
        """Everything an account had configured. Part of deleting it."""
        with self.db.begin() as conn:
            conn.execute(delete(settings).where(settings.c.user_id == user_id))


__all__ = ["INSTALLATION", "SettingsStoreMixin"]
