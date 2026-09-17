"""Anthropic Messages API provider.

Model and thinking depth arrive on the request; this module never names a model. The
profile's ``thinking_depth`` maps onto the API like so:

- ``off``  -> ``thinking: {"type": "disabled"}`` and no effort setting
- others   -> adaptive thinking with ``output_config.effort`` set to the same word

Structured output is requested through ``output_config.format`` so the response text is
guaranteed to be JSON matching the role's result schema; validation still happens in the
invoke layer so all providers are treated the same.
"""

from __future__ import annotations

from typing import Any

from slipwright.providers import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from slipwright.schemas.profile import ThinkingDepth

# Non-streaming ceiling that keeps responses well under the SDK's HTTP timeout.
DEFAULT_MAX_TOKENS = 16_000


class AnthropicProvider:
    def __init__(self, client: Any | None = None, *, max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise ProviderUnavailableError("the `anthropic` package is not installed") from exc
            try:
                client = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise ProviderUnavailableError(f"could not build Anthropic client: {exc}") from exc
        self._client = client
        self._max_tokens = max_tokens

    @classmethod
    def from_credentials(
        cls,
        api_key: str,
        *,
        base_url: str | None = None,
        transport: Any | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AnthropicProvider:
        """Build from an explicit key (the settings page) instead of the environment."""
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderUnavailableError("the `anthropic` package is not installed") from exc
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        if transport is not None:
            kwargs["http_client"] = _sdk_http_client(transport)
        return cls(anthropic.Anthropic(**kwargs), max_tokens=max_tokens)

    def list_models(self) -> list[str]:
        """Model ids the key can use; doubles as the connection test."""
        import anthropic

        try:
            page = self._client.models.list(limit=100)
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.AnthropicError as exc:
            raise ProviderError(str(exc)) from exc
        return sorted(str(m.id) for m in page.data)

    def complete(self, request: ModelRequest) -> ModelResponse:
        import anthropic

        kwargs = build_request_kwargs(request, max_tokens=self._max_tokens)
        try:
            message = self._client.with_options(timeout=request.timeout_s).messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"connection error: {exc}") from exc
        except anthropic.AnthropicError as exc:
            raise ProviderError(str(exc)) from exc

        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) if details is not None else None
            raise ProviderRefusalError(f"model refused (category={category})")
        if message.stop_reason == "max_tokens":
            raise ProviderError(f"response truncated at max_tokens={self._max_tokens}")

        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        return ModelResponse(
            text=text,
            model=message.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            stop_reason=message.stop_reason,
        )


def _sdk_http_client(transport: Any) -> Any:
    """The SDK ships its own ``httpx2``; adapt a plain ``httpx`` mock transport (what the
    rest of Slipwright and its tests use) so one fake vendor can answer every provider."""
    import httpx
    import httpx2

    if not isinstance(transport, httpx.MockTransport):
        return httpx2.Client(transport=transport)
    handler = transport.handler

    def bridge(request: Any) -> Any:
        upstream = httpx.Request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.content,
        )
        resp = handler(upstream)
        assert isinstance(resp, httpx.Response)  # sync handlers only
        return httpx2.Response(resp.status_code, content=resp.content, headers=dict(resp.headers))

    return httpx2.Client(transport=httpx2.MockTransport(bridge))


def build_request_kwargs(request: ModelRequest, *, max_tokens: int) -> dict[str, Any]:
    """Pure translation from ``ModelRequest`` to ``messages.create`` keyword arguments."""
    from anthropic import transform_schema

    output_config: dict[str, Any] = {
        "format": {"type": "json_schema", "schema": transform_schema(request.output_schema)}
    }
    thinking: dict[str, Any]
    if request.thinking_depth is ThinkingDepth.OFF:
        thinking = {"type": "disabled"}
    else:
        thinking = {"type": "adaptive"}
        output_config["effort"] = request.thinking_depth.value

    return {
        "model": request.model,
        "max_tokens": max_tokens,
        "system": request.system,
        "messages": [{"role": "user", "content": request.prompt}],
        "thinking": thinking,
        "output_config": output_config,
    }


__all__ = ["DEFAULT_MAX_TOKENS", "AnthropicProvider", "build_request_kwargs"]
