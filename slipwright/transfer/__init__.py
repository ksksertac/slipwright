"""Moving an account's work to another Slipwright on the same network, in one go.

The receiving machine shows a code for thirty seconds; the person types it on the sending
one, beside the receiving machine's card. Everything the account has -- projects,
developments and their history, attachments, briefs, standards pages, settings with the
model keys and Git tokens in them, and every checkout with its branches and uncommitted
work -- goes across, sealed with a key the code alone could produce, and is written on
the other side all at once or not at all. The people do not move: users, sessions and
memberships stay, and on arrival everything belongs to whoever showed the code.

* ``channel`` -- the code, the key it makes (SPAKE2) and how a part is sealed.
* ``rows``    -- what is carried, and how it travels.
* ``outgoing``-- the sender: reading it out, sending it, deleting it after if asked.
* ``incoming``-- the receiver: codes on show, staging, and writing it.
* ``nearby``  -- finding the other installations on the network.

``slipwright db copy`` is the other way to move: a whole installation's database, from
one engine to another, on one machine. This is an account, between machines.
"""

from __future__ import annotations

import os

#: On by default for a local installation; off for one on PostgreSQL, which is a hosted
#: server where looking around the network it sits on is nobody's business.
ENV = "SLIPWRIGHT_TRANSFER"
_OFF = frozenset({"0", "false", "no", "off"})


def enabled_by_default(database_url: str | None, env: dict[str, str] | None = None) -> bool:
    env = dict(os.environ) if env is None else env
    raw = env.get(ENV, "").strip().lower()
    if raw:
        return raw not in _OFF
    return database_url is None


__all__ = ["ENV", "enabled_by_default"]
