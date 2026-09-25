"""Keeping an access token out of anything a person or an agent will read.

Cloning and pushing a private repository means handing git a URL with the token in it.
git then prints that URL back in its error messages, and Slipwright writes those messages
into the job's history, shows them on the page and feeds them to the next agent -- so one
failed clone used to put a working credential in all three places.

Bitbucket already did this for its pushes. It belongs in one place, applied by every
host, to every message, rather than being remembered per call site.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: What replaces it. Short, and obviously not a token.
MASK = "…"

#: Anything shaped like a credential in a URL, whatever host it is for. Catches the token
#: even when it is not the one we were holding -- a stale one in a remote, say.
_IN_URL = re.compile(r"(?P<scheme>https?://)(?P<user>[^/@\s:]+):(?P<secret>[^/@\s]+)@")


def scrub(text: str | None, *secrets: str | None) -> str:
    """``text`` with every secret, and anything in URL-credential position, masked."""
    if not text:
        return text or ""
    out = text
    for secret in secrets:
        if secret and len(secret) >= 8:  # a short "secret" would mask ordinary words
            out = out.replace(secret, MASK)
    return _IN_URL.sub(rf"\g<scheme>\g<user>:{MASK}@", out)


def scrub_all(texts: Iterable[str | None], *secrets: str | None) -> list[str]:
    return [scrub(t, *secrets) for t in texts]


__all__ = ["MASK", "scrub", "scrub_all"]
