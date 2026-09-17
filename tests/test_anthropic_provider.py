from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx2
import pytest

from slipwright.providers import (
    ModelRequest,
    ProviderError,
    ProviderRefusalError,
    ProviderTimeoutError,
)
from slipwright.providers.anthropic import AnthropicProvider, build_request_kwargs
from slipwright.roles.results import ArchitectResult
from slipwright.schemas.profile import RoleName, ThinkingDepth


def _request(depth: ThinkingDepth = ThinkingDepth.HIGH) -> ModelRequest:
    return ModelRequest(
        role=RoleName.ARCHITECT,
        model="model-from-profile",
        thinking_depth=depth,
        system="sys",
        prompt="do it",
        output_schema=ArchitectResult.model_json_schema(),
        timeout_s=12.5,
    )


# --- request translation -----------------------------------------------------------------


def test_kwargs_carry_model_and_structured_output() -> None:
    kwargs = build_request_kwargs(_request(), max_tokens=999)

    assert kwargs["model"] == "model-from-profile"
    assert kwargs["max_tokens"] == 999
    assert kwargs["system"] == "sys"
    assert kwargs["messages"] == [{"role": "user", "content": "do it"}]
    fmt = kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert "phases" in fmt["schema"]["properties"]


@pytest.mark.parametrize(
    "depth", [ThinkingDepth.LOW, ThinkingDepth.MEDIUM, ThinkingDepth.HIGH, ThinkingDepth.MAX]
)
def test_thinking_depth_maps_to_adaptive_effort(depth: ThinkingDepth) -> None:
    kwargs = build_request_kwargs(_request(depth), max_tokens=1)
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"]["effort"] == depth.value


def test_thinking_off_disables_thinking() -> None:
    kwargs = build_request_kwargs(_request(ThinkingDepth.OFF), max_tokens=1)
    assert kwargs["thinking"] == {"type": "disabled"}
    assert "effort" not in kwargs["output_config"]


# --- response handling -------------------------------------------------------------------


@dataclass
class _Block:
    type: str
    text: str = ""


@dataclass
class _Usage:
    input_tokens: int = 3
    output_tokens: int = 4


@dataclass
class _Message:
    content: list[_Block]
    stop_reason: str = "end_turn"
    model: str = "served-model"
    usage: _Usage = field(default_factory=_Usage)
    stop_details: Any = None


class _FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _FakeClient:
    def __init__(self, outcome: Any) -> None:
        self.messages = _FakeMessages(outcome)
        self.timeouts: list[float] = []

    def with_options(self, *, timeout: float) -> _FakeClient:
        self.timeouts.append(timeout)
        return self


def test_complete_returns_text_and_usage() -> None:
    client = _FakeClient(
        _Message([_Block("thinking"), _Block("text", '{"a":'), _Block("text", "1}")])
    )
    response = AnthropicProvider(client=client).complete(_request())

    assert response.text == '{"a":1}'
    assert response.model == "served-model"
    assert response.input_tokens == 3 and response.output_tokens == 4
    assert client.timeouts == [12.5]
    assert client.messages.calls[0]["model"] == "model-from-profile"


def test_refusal_raises_typed_error() -> None:
    client = _FakeClient(_Message([], stop_reason="refusal"))
    with pytest.raises(ProviderRefusalError):
        AnthropicProvider(client=client).complete(_request())


def test_truncation_raises_provider_error() -> None:
    client = _FakeClient(_Message([_Block("text", "{")], stop_reason="max_tokens"))
    with pytest.raises(ProviderError, match="max_tokens"):
        AnthropicProvider(client=client).complete(_request())


def test_sdk_timeout_maps_to_provider_timeout() -> None:
    exc = anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.example"))
    with pytest.raises(ProviderTimeoutError):
        AnthropicProvider(client=_FakeClient(exc)).complete(_request())


def test_sdk_status_error_maps_to_provider_error() -> None:
    response = httpx2.Response(500, request=httpx2.Request("POST", "https://api.example"))
    exc = anthropic.APIStatusError("server down", response=response, body=None)
    with pytest.raises(ProviderError, match="500"):
        AnthropicProvider(client=_FakeClient(exc)).complete(_request())
