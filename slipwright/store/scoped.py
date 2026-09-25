"""A store that reads and writes one account's settings.

The engine touches settings in some forty places -- model keys, Git tokens, Jira, which
model each agent runs on -- and threading an account id through every one of those
signatures would be forty chances to forget one, in the place where forgetting means one
tenant spending another's key.

So the account is bound once, here. ``ScopedStore`` is the real store in every respect
except the four settings methods, which it answers on behalf of one person. Everything
else -- jobs, projects, users, prices -- passes straight through untouched, because those
are scoped by their own owner column and not by this.

Which settings are personal and which belong to the server is decided in one place,
``INSTALLATION_SETTINGS``, rather than at each call.
"""

from __future__ import annotations

from typing import Any

from slipwright.store.settings import INSTALLATION
from slipwright.store.sqlite import JobStore

#: Settings that belong to the installation however they are asked for: the sender it
#: mails from, what models cost, where it posts webhooks, and how the shared standards
#: index is built. Matched exactly or as the part before the first dot.
INSTALLATION_SETTINGS = frozenset({"mail", "prices", "notifications", "standards"})


def is_personal(name: str) -> bool:
    """Whether this setting belongs to a person rather than to the server."""
    return name.split(".", 1)[0] not in INSTALLATION_SETTINGS


class ScopedStore:
    """The store, with settings bound to one account."""

    def __init__(self, store: JobStore, user_id: str | None) -> None:
        self._store = store
        # None is "the installation": a local install with no accounts, the CLI, a job
        # that predates ownership. It reads and writes exactly what it always did.
        self._user_id = user_id or INSTALLATION

    @property
    def scoped_to(self) -> str:
        return self._user_id

    def _owner(self, name: str) -> str:
        return self._user_id if is_personal(name) else INSTALLATION

    # -- the four that are scoped --------------------------------------------------------

    def get_setting(self, name: str, default: Any = None, **kw: Any) -> Any:
        kw.setdefault("user_id", self._owner(name))
        return self._store.get_setting(name, default, **kw)

    def set_setting(self, name: str, value: Any, **kw: Any) -> None:
        kw.setdefault("user_id", self._owner(name))
        self._store.set_setting(name, value, **kw)

    def delete_setting(self, name: str, **kw: Any) -> None:
        kw.setdefault("user_id", self._owner(name))
        self._store.delete_setting(name, **kw)

    def setting_is_set(self, name: str, **kw: Any) -> bool:
        kw.setdefault("user_id", self._owner(name))
        return bool(self._store.setting_is_set(name, **kw))

    # -- everything else is the store ----------------------------------------------------

    def __getattr__(self, item: str) -> Any:
        return getattr(self._store, item)


__all__ = ["INSTALLATION_SETTINGS", "ScopedStore", "is_personal"]
