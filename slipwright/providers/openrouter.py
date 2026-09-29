"""OpenRouter: one key, four hundred models, two of which are traps.

OpenRouter speaks the OpenAI protocol, so ``OpenAICompatProvider`` does all the work of
actually calling it. What it does not do is survive OpenRouter's model catalogue, and
that is what this module is for. Two things are different enough here to be worth code
rather than a comment:

**Not every model can answer.** Slipwright asks for JSON on every single call
(``response_format``), and OpenRouter drops a parameter a model does not support instead
of refusing the request. So a model without ``response_format`` does not fail at the API
-- it answers in prose, and the failure surfaces three layers away in the invoke layer as
a schema error on text nobody asked for. Of the 460 models listed, 67 are like this. They
are filtered out of the list a person picks from, because a model that cannot be used is
not a choice.

**The catalogue is public.** ``GET /models`` answers 200 to anyone, key or no key, right
or wrong. That matters because listing models *is* the connection test everywhere else in
Slipwright: paste any string at all, press Test connection, and OpenRouter would report
four hundred models available on a key that does not exist. So the key is proved first,
against ``GET /key``, which is the endpoint that actually answers 401.
"""

from __future__ import annotations

from typing import Any

import httpx

from slipwright import net
from slipwright.providers import (
    REJECTED_STATUS,
    ProviderError,
    ProviderRejectedError,
)
from slipwright.providers.openai_compat import OpenAICompatProvider

#: The parameter Slipwright cannot do without: every role is asked for JSON.
REQUIRED_PARAM = "response_format"


class OpenRouterProvider(OpenAICompatProvider):
    def list_models(self) -> list[str]:
        """The models this key can actually be used with, having first proved the key."""
        self._prove_key()
        return sorted(
            str(m["id"])
            for m in self._catalogue()
            if m.get("id") and REQUIRED_PARAM in (m.get("supported_parameters") or [])
        )

    def _prove_key(self) -> None:
        """``GET /key`` is the only endpoint that cares whether the key is real."""
        resp = self._get("/key")
        if resp.status_code in REJECTED_STATUS:
            raise ProviderRejectedError(f"OpenRouter rejected the key ({resp.status_code})")
        if resp.status_code >= 400:
            raise ProviderError(f"API error {resp.status_code}")

    def _catalogue(self) -> list[dict[str, Any]]:
        resp = self._get("/models")
        if resp.status_code >= 400:
            raise ProviderError(f"API error {resp.status_code}")
        data = resp.json().get("data") or []
        return [m for m in data if isinstance(m, dict)]

    def _get(self, path: str) -> httpx.Response:
        try:
            return net.request(self._client, "GET", path, timeout=20.0)
        except httpx.HTTPError as exc:
            raise ProviderError(f"connection error: {exc}") from exc


__all__ = ["REQUIRED_PARAM", "OpenRouterProvider"]
