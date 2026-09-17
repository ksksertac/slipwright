"""Model providers: the only boundary where Slipwright talks to an LLM API.

A provider receives a fully-resolved ``ModelRequest`` (model and thinking depth already
taken from the profile) and returns the model's raw text. Parsing and validation of that
text happen in ``slipwright.invoke``, so every provider stays thin and the engine's error
handling is uniform regardless of backend.

Providers signal failure only through ``ProviderError`` subclasses; the invoke layer turns
those into typed ``InvokeError`` values.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.profile import Permission, RoleName, ThinkingDepth


class ModelRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    role: RoleName
    model: str = Field(min_length=1)
    provider: str | None = Field(
        default=None, description="Provider name from the profile; None means the default."
    )
    thinking_depth: ThinkingDepth
    permissions: tuple[Permission, ...] = ()
    system: str
    prompt: str
    output_schema: dict[str, Any] = Field(
        description="JSON Schema the response text must conform to."
    )
    timeout_s: float = Field(gt=0)


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None


class ProviderError(RuntimeError):
    """Base class for failures a provider reports. Never leaks past ``invoke_role``."""


class ProviderTimeoutError(ProviderError):
    pass


class ProviderRefusalError(ProviderError):
    """The model declined to answer (``stop_reason == "refusal"``)."""


class ProviderUnavailableError(ProviderError):
    """The provider could not be constructed (missing SDK, missing credentials, ...)."""


@runtime_checkable
class ModelProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


__all__ = [
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "ProviderError",
    "ProviderRefusalError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
]
