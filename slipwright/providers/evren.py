"""EVREN: the Turkish defence industry's model platform, and three rules of its own.

EVREN (evren.ssyz.org.tr) serves open-weight models on hardware in Turkey through an
OpenAI-compatible gateway, so ``OpenAICompatProvider`` does the calling. What it does
not do is know three things that were each found against the live API (2026-09-30):

**Half the catalogue cannot be an agent.** ``/models`` lists OCR, embedding, reranking
and speech models beside the chat ones, and ``auto`` -- a router that picks a different
model per call and does not promise JSON. Unlike OpenRouter, EVREN says so outright:
every entry carries its ``task`` and ``capabilities``. Only a chat model that can answer
in JSON (``response_format``) is offered, because every role asks for JSON.

**Reasoning effort is per model, and refused where it is not supported.** GLM and
DeepSeek take ``reasoning_effort``; Gemma answers 400 to the very same body. A provider
that said "supported" broke Gemma, one that said "not supported" threw away the thinking
depth of every model that has one. So the catalogue decides, per call.

**Nothing works until the terms are accepted.** A new key is refused with 403
``terms_not_accepted`` everywhere, the model list included, and the platform's own web
site has no button for it -- only ``POST /v1/terms/accept``. Slipwright never accepts on
anyone's behalf: the Models page shows EVREN's own text and the person presses the
button (``terms`` / ``accept_terms``). A job that meets the refusal later, because EVREN
published a material new version, stops saying where to go rather than "API error 403".
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any

import httpx

from slipwright import net
from slipwright.providers import (
    REJECTED_STATUS,
    ModelRequest,
    ProviderError,
    ProviderRejectedError,
)
from slipwright.providers.openai_compat import OpenAICompatProvider, error_message

#: The only kind of key the model gateway takes. The same account page also issues
#: platform (``evren_plt_``) and model-inference keys, and the gateway calls any of those
#: simply "invalid" -- which sends a person to check a key that is perfectly good.
LLM_KEY_PREFIX = "evren_llm_"
TERMS_NOT_ACCEPTED = "terms_not_accepted"
#: What a model is for, as the catalogue says it: a vision model converses as well,
#: it can also look at pictures.
CHAT_TASKS = frozenset({"chat", "vision_chat"})
#: How stale the capability list may be before a model it does not know is looked up
#: again: long enough not to ask before every call, short enough that a model added to
#: the fleet gets its reasoning effort the same afternoon.
CATALOGUE_TTL_S = 600.0

TERMS_REFUSED = (
    "EVREN's terms of use have not been accepted for this key: "
    "accept them under Settings → Models → EVREN"
)


@dataclass(frozen=True)
class Terms:
    version: int
    accepted: bool
    text: str


class EvrenProvider(OpenAICompatProvider):
    def __init__(self, api_key: str, base_url: str, **kwargs: Any) -> None:
        super().__init__(api_key, base_url, **kwargs)
        self._key_kind = _key_kind(api_key)
        # model id -> takes reasoning_effort; None until the catalogue has been read
        self._effort: dict[str, bool] | None = None
        self._read_at = 0.0

    # -- the models ----------------------------------------------------------------------

    def list_models(self) -> list[str]:
        """The chat models that can answer in JSON; the connection test as well."""
        return sorted(str(m["id"]) for m in self._catalogue() if _usable(m))

    def build_body(self, request: ModelRequest) -> dict[str, Any]:
        body = super().build_body(request)
        if "reasoning_effort" in body and not self._takes_effort(request.model):
            del body["reasoning_effort"]
        return body

    def _takes_effort(self, model: str) -> bool:
        """Whether this model accepts ``reasoning_effort``. Unknown means no: a request
        without it is answered, one with it can be refused outright."""
        stale = time.monotonic() - self._read_at > CATALOGUE_TTL_S
        if self._effort is None or (model not in self._effort and stale):
            # a catalogue that cannot be read costs the call its thinking depth, not the call
            with contextlib.suppress(ProviderError):
                self._catalogue()
        return bool((self._effort or {}).get(model))

    def _catalogue(self) -> list[dict[str, Any]]:
        listed = self._json("/models").get("data") or []
        data = [m for m in listed if isinstance(m, dict) and m.get("id")]
        self._effort = {
            str(m["id"]): bool((m.get("capabilities") or {}).get("reasoning_effort")) for m in data
        }
        self._read_at = time.monotonic()
        return data

    # -- the terms -----------------------------------------------------------------------

    def terms(self) -> Terms:
        """Where this key stands with EVREN's terms, and their text to read first."""
        status = self._json("/terms/status")
        text = self._json("/terms/text")
        return Terms(
            version=int(status.get("current_version") or 0),
            accepted=bool(status.get("accepted")),
            text=str(text.get("content") or ""),
        )

    def accept_terms(self, version: int) -> Terms:
        """Accept ``version`` -- the one the person was shown, never whatever is current:
        a version published between reading and pressing is refused, not signed unread."""
        try:
            resp = net.request(
                self._client, "POST", "/terms/accept", json={"version": version}, timeout=20.0
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"connection error: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"EVREN did not accept it: {error_message(resp)}")
        return self.terms()

    # -- refusals ------------------------------------------------------------------------

    def refused(self, resp: httpx.Response) -> ProviderError:
        if _code(resp) == TERMS_NOT_ACCEPTED:
            return ProviderRejectedError(TERMS_REFUSED)
        if resp.status_code == 401 and self._key_kind not in (None, "llm"):
            return ProviderRejectedError(
                f"this is an EVREN {self._key_kind} key; the models need an "
                f"“LLM Çıkarım” key ({LLM_KEY_PREFIX}…) from API Anahtarları"
            )
        return super().refused(resp)

    def _json(self, path: str) -> dict[str, Any]:
        resp = self._get(path)
        if resp.status_code in REJECTED_STATUS:
            raise self.refused(resp)
        if resp.status_code >= 400:
            raise ProviderError(f"API error {resp.status_code}: {error_message(resp)}")
        body = resp.json()
        return body if isinstance(body, dict) else {}

    def _get(self, path: str) -> httpx.Response:
        try:
            return net.request(self._client, "GET", path, timeout=20.0)
        except httpx.HTTPError as exc:
            raise ProviderError(f"connection error: {exc}") from exc


def _usable(model: dict[str, Any]) -> bool:
    caps = model.get("capabilities") or {}
    return model.get("task") in CHAT_TASKS and bool(caps.get("response_format"))


def _key_kind(key: str) -> str | None:
    """``llm`` for ``evren_llm_…``, ``plt`` for a platform key; None for anything else,
    which is left for EVREN to judge rather than second-guessed here."""
    if not key.startswith("evren_"):
        return None
    kind = key.removeprefix("evren_").partition("_")[0]
    return "platform" if kind == "plt" else kind or None


def _code(resp: httpx.Response) -> str | None:
    with contextlib.suppress(ValueError, AttributeError):
        err = resp.json().get("error")
        if isinstance(err, dict):
            return str(err.get("code") or "") or None
    return None


__all__ = ["CATALOGUE_TTL_S", "LLM_KEY_PREFIX", "TERMS_REFUSED", "EvrenProvider", "Terms"]
