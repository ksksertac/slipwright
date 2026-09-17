"""OpenAI-compatible chat-completions provider (OpenAI, DeepSeek, and lookalikes).

Speaks the ``POST {base_url}/chat/completions`` dialect over plain ``httpx``, so no extra
SDK is needed and tests can answer locally through a mock transport. The profile's
``thinking_depth`` maps onto ``reasoning_effort`` where the vendor supports it
(``supports_effort``); ``off`` sends nothing. JSON output is requested through
``response_format`` and, as with every provider, validated by the invoke layer.
"""

from __future__ import annotations

import contextlib
from typing import Any

import httpx

from slipwright.providers import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRefusalError,
    ProviderTimeoutError,
)
from slipwright.schemas.profile import ThinkingDepth

DEFAULT_MAX_TOKENS = 16_000
# reasoning_effort vocabulary: our five depths onto the vendor's three-ish
_EFFORT = {
    ThinkingDepth.LOW: "low",
    ThinkingDepth.MEDIUM: "medium",
    ThinkingDepth.HIGH: "high",
    ThinkingDepth.MAX: "high",
}


class OpenAICompatProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        supports_effort: bool = True,
        max_tokens_param: str = "max_tokens",
        max_tokens: int = DEFAULT_MAX_TOKENS,
        transport: httpx.BaseTransport | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("no API key configured")
        self.base_url = base_url.rstrip("/")
        self.supports_effort = supports_effort
        self.max_tokens_param = max_tokens_param
        self._max_tokens = max_tokens
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "slipwright",
                **(extra_headers or {}),
            },
            transport=transport,
        )

    def build_body(self, request: ModelRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "response_format": {"type": "json_object"},
            self.max_tokens_param: self._max_tokens,
        }
        if self.supports_effort and request.thinking_depth is not ThinkingDepth.OFF:
            body["reasoning_effort"] = _EFFORT[request.thinking_depth]
        return body

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            resp = self._client.post(
                "/chat/completions", json=self.build_body(request), timeout=request.timeout_s
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"connection error: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"API error {resp.status_code}: {_error_message(resp)}")
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("API returned no choices")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            raise ProviderRefusalError("model refused (content_filter)")
        if finish == "length":
            raise ProviderError(f"response truncated at {self.max_tokens_param}={self._max_tokens}")
        message = choice.get("message") or {}
        text = message.get("content") or ""
        if isinstance(text, list):  # some vendors return content parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        usage = data.get("usage") or {}
        return ModelResponse(
            text=text,
            model=data.get("model") or request.model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            stop_reason=finish,
        )

    def list_models(self) -> list[str]:
        try:
            resp = self._client.get("/models", timeout=20.0)
        except httpx.HTTPError as exc:
            raise ProviderError(f"connection error: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"API error {resp.status_code}: {_error_message(resp)}")
        data = resp.json().get("data") or []
        return sorted(str(m["id"]) for m in data if isinstance(m, dict) and m.get("id"))


def _error_message(resp: httpx.Response) -> str:
    with contextlib.suppress(ValueError):
        body = resp.json()
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str):
            return err
    return resp.text[:200]


__all__ = ["DEFAULT_MAX_TOKENS", "OpenAICompatProvider"]
