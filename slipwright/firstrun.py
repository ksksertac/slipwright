"""The account a server starts with, so that starting it is the whole of the setup.

A person who has just run the container wants to look at the thing, not to read a page
telling them to open a terminal and type a command inside it. So an installation with no
accounts at all makes one: ``admin``, password ``admin``, and the login page says so.

That is a well-known password, and this module's other half is making sure nobody forgets
it is there. It exists only while the database is empty, it is announced in the log at
every start, the interface carries a banner until it is changed, and
``SLIPWRIGHT_DEFAULT_ADMIN=0`` stops it being made at all -- which is what a server open
to the internet should set, along with everything else it has to think about.

It is not a migration. A migration runs once against a schema; this runs at every start
and asks a question about the data -- is there anybody here yet -- which is a different
thing and belongs where the server begins.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slipwright.store import JobStore

log = logging.getLogger(__name__)

NAME = "admin"
PASSWORD = "admin"

#: Said at every start while the password is still the one printed above, because the
#: risk is not that somebody does not know -- it is that they stop noticing.
WARNING = (
    "the default administrator is in place: user 'admin', password 'admin'. Change it "
    "under Settings -> Users, or set SLIPWRIGHT_DEFAULT_ADMIN=0 and make your own. "
    "Anybody who can reach this server can sign in as you until you do."
)


def ensure_default_admin(store: JobStore, *, wanted: bool = True) -> bool:
    """Make the starting account if there is nobody at all. True when one now exists.

    Only ever on an empty database: an installation that has accounts has an owner, and
    handing out a known password to somebody else's server is the opposite of helping.
    """
    if not wanted:
        return False
    if store.list_users():
        return False
    store.create_user(NAME, PASSWORD, is_admin=True)
    log.warning("no accounts existed, so one was made. %s", WARNING)
    return True


def default_admin_still_open(store: JobStore) -> bool:
    """Whether ``admin``/``admin`` still gets in.

    Asked rather than remembered: a flag would go stale the moment somebody changed the
    password, and this is the question every caller actually means.
    """
    try:
        return store.authenticate(NAME, PASSWORD) is not None
    except Exception:  # noqa: BLE001 - a banner must never take the server down
        return False


__all__ = ["NAME", "PASSWORD", "WARNING", "default_admin_still_open", "ensure_default_admin"]
