"""Asking again when the request never left.

A TLS handshake cut short somewhere between here and the other end is not an answer. It
happens on ordinary internet connections -- a middlebox, a flaky link -- often enough to
matter: measured against one Atlassian site it was roughly one request in sixty, and every
one of those surfaced as a failed sync, a failed model call or a failed push.

``httpx`` reports it as a connect error, and that is exactly the case where asking again is
safe whatever the method was: a connection that never opened carried no request, so there
is nothing on the other side to duplicate -- no second issue, no second model call to pay
for. Anything the server itself said, including an error and including a read that died
half way through an answer, is left alone here and handled by the caller: it is an answer,
and repeating it would either change nothing or charge twice.

The original exception is re-raised when the last try fails, so each client keeps its own
words for what went wrong.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

#: Three tries in all, a breath longer each time. Long enough to ride out the one-off drop
#: this exists for, short enough that a link which is genuinely down still says so quickly.
CONNECT_TRIES = 3
CONNECT_PAUSE_S = 0.4


def request(client: httpx.Client, method: str, url: str, **kw: Any) -> httpx.Response:
    """Send a request, trying again while the connection itself is what failed."""
    for attempt in range(1, CONNECT_TRIES + 1):
        try:
            return client.request(method, url, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == CONNECT_TRIES:
                raise
            time.sleep(CONNECT_PAUSE_S * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


__all__ = ["CONNECT_PAUSE_S", "CONNECT_TRIES", "request"]
