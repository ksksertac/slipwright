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


class ImageInput(BaseModel):
    """A picture shown to the model beside the prompt: a screen somebody attached, or a
    page of a PDF rendered to look at. Already small enough to send -- the attachments
    module scales it down -- so a provider only has to wrap it."""

    model_config = ConfigDict(frozen=True, ser_json_bytes="base64", val_json_bytes="base64")

    media_type: str  # image/png | image/jpeg
    data: bytes
    label: str = ""  # which file and page, said in the prompt next to it


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
    # what the model is to look at as well as read. Empty on nearly every call; a
    # provider that cannot show pictures refuses the call rather than dropping them, so
    # the caller can decide to ask again without (``attachments.read``)
    images: tuple[ImageInput, ...] = ()


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    model: str | None = None
    provider: str | None = None  # which vendor answered; set by the router, priced later
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None


class ProviderError(RuntimeError):
    """Base class for failures a provider reports. Never leaks past ``invoke_role``.

    A call that failed can still have cost money, and the largest failure costs the most:
    an answer cut off at the output limit was generated in full, is billed in full, and
    the vendor reports its tokens in the same usage block a good answer carries. So the
    tokens ride on the error. They are ``None`` when the vendor never got far enough to
    report any -- a connection that never opened is not a bill of zero, it is a bill
    nobody knows -- and the two stay apart all the way out to the cost panel."""

    def __init__(
        self,
        *args: object,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        super().__init__(*args)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class ProviderTimeoutError(ProviderError):
    pass


class ProviderRefusalError(ProviderError):
    """The model declined to answer (``stop_reason == "refusal"``)."""


class ProviderTruncatedError(ProviderError):
    """The answer hit the output limit: the same prompt would be cut off again, so the
    caller has to ask for less (a smaller part of the work), not simply retry."""


class ProviderUnavailableError(ProviderError):
    """The provider could not be constructed (missing SDK, missing credentials, ...)."""


#: What a vendor says when it is refusing the account rather than the request: the key is
#: wrong (401), it is not allowed here (403), or there is nothing left to spend (402).
REJECTED_STATUS = frozenset({401, 402, 403})


class ProviderRejectedError(ProviderError):
    """The vendor refused the account, not the request: no balance, a bad key, a key that
    is not allowed this model.

    It is the one provider failure that asking again cannot mend -- the second call is
    refused for the same reason as the first -- so it ends the step at once instead of
    spending the role's retries, and says which account and why."""


@runtime_checkable
class ModelProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


__all__ = [
    "ImageInput",
    "REJECTED_STATUS",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "ProviderError",
    "ProviderRejectedError",
    "ProviderRefusalError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
]
