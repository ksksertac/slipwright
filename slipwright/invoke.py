"""Agent invocation layer: the one place the engine asks a model to play a role.

``invoke_role`` resolves model and thinking depth from ``profile.roles[role]``, builds a
``ModelRequest``, hands it to a ``ModelProvider``, then parses and validates the response
against the role's result schema. Runtime failures (timeout, provider error, malformed or
refused output) come back as a typed ``InvokeError`` on the ``RoleResult`` — never as a
raised exception. Only programmer errors (an unknown role) raise.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, SerializeAsAny, ValidationError, model_validator

from slipwright.providers import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderTruncatedError,
    ProviderUnavailableError,
)
from slipwright.roles.results import RESULT_SCHEMAS, RoleOutput, result_schema_for
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth

DEFAULT_TIMEOUT_S = 600.0
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class InvokeErrorKind(StrEnum):
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    REFUSED = "refused"
    MALFORMED_OUTPUT = "malformed_output"
    BUDGET = "budget"  # the job's budget is exhausted (T9.7)
    LOOP = "loop"  # the role produced the same output twice in a row (T9.7)
    TRUNCATED = "truncated"  # the answer hit the output limit; ask for a smaller part


# provider errors worth another attempt; refusals and missing providers are not
RETRYABLE: frozenset[InvokeErrorKind] = frozenset(
    {InvokeErrorKind.TIMEOUT, InvokeErrorKind.PROVIDER_ERROR, InvokeErrorKind.MALFORMED_OUTPUT}
)


class InvokeError(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: InvokeErrorKind
    message: str
    detail: str | None = None


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


class RoleResult(BaseModel):
    """Outcome of one role invocation. Exactly one of ``output`` / ``error`` is set."""

    model_config = ConfigDict(extra="forbid")

    role: RoleName
    model: str
    thinking_depth: ThinkingDepth
    output: SerializeAsAny[RoleOutput] | None = None
    error: InvokeError | None = None
    raw_text: str | None = None
    usage: Usage | None = None
    standards: list[str] | None = None  # chunk ids retrieved into the prompt (T9.4)
    attempts: int = 1  # how many calls it took (T9.7)
    prompt_chars: int | None = None  # size of the prompt sent (T9.7)

    @property
    def ok(self) -> bool:
        return self.error is None

    @model_validator(mode="before")
    @classmethod
    def _typed_output(cls, data: Any) -> Any:
        """Reload ``output`` as the role's concrete schema (e.g. from persisted JSON)."""
        if isinstance(data, dict) and isinstance(data.get("output"), dict):
            data = {
                **data,
                "output": RESULT_SCHEMAS[RoleName(data["role"])].model_validate(data["output"]),
            }
        return data


_default_provider: ModelProvider | None = None


def set_default_provider(provider: ModelProvider | None) -> None:
    global _default_provider
    _default_provider = provider


def get_default_provider() -> ModelProvider:
    """Return the configured provider, building the Anthropic one on first use."""
    global _default_provider
    if _default_provider is None:
        from slipwright.providers.anthropic import AnthropicProvider

        _default_provider = AnthropicProvider()
    return _default_provider


def invoke_role(
    role: RoleName | str,
    profile: Profile,
    context: Mapping[str, Any],
    *,
    provider: ModelProvider | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> RoleResult:
    role = _coerce_role(role)
    role_cfg = profile.roles[role]
    schema_cls = result_schema_for(role)
    output_schema = schema_cls.model_json_schema()

    request = ModelRequest(
        role=role,
        model=role_cfg.model,
        provider=role_cfg.provider,
        thinking_depth=role_cfg.thinking_depth,
        permissions=tuple(role_cfg.permissions),
        system=_system_prompt(role, context),
        prompt=_user_prompt(context, output_schema),
        output_schema=output_schema,
        timeout_s=timeout_s,
    )

    def fail(kind: InvokeErrorKind, message: str, *, raw_text: str | None = None) -> RoleResult:
        return RoleResult(
            role=role,
            model=role_cfg.model,
            thinking_depth=role_cfg.thinking_depth,
            error=InvokeError(kind=kind, message=message, detail=raw_text),
            raw_text=raw_text,
            prompt_chars=len(request.system) + len(request.prompt),
        )

    if provider is None:
        try:
            provider = get_default_provider()
        except ProviderUnavailableError as exc:
            return fail(InvokeErrorKind.PROVIDER_UNAVAILABLE, str(exc))

    try:
        response = _call_with_timeout(lambda: provider.complete(request), timeout_s)
    except (ProviderTimeoutError, FutureTimeoutError) as exc:
        why = f" ({exc})" if str(exc) else ""
        return fail(InvokeErrorKind.TIMEOUT, f"{role.value} timed out after {timeout_s:g}s{why}")
    except ProviderRefusalError as exc:
        return fail(InvokeErrorKind.REFUSED, str(exc))
    except ProviderTruncatedError as exc:
        return fail(InvokeErrorKind.TRUNCATED, str(exc))
    except ProviderUnavailableError as exc:
        return fail(InvokeErrorKind.PROVIDER_UNAVAILABLE, str(exc))
    except ProviderError as exc:
        return fail(InvokeErrorKind.PROVIDER_ERROR, str(exc))
    except Exception as exc:  # noqa: BLE001 - the contract is "never a raw exception upward"
        return fail(InvokeErrorKind.PROVIDER_ERROR, f"{type(exc).__name__}: {exc}")

    try:
        output = _parse_output(response.text, schema_cls)
    except _MalformedOutput as exc:
        return fail(InvokeErrorKind.MALFORMED_OUTPUT, str(exc), raw_text=response.text)

    return RoleResult(
        role=role,
        model=role_cfg.model,
        thinking_depth=role_cfg.thinking_depth,
        output=output,
        raw_text=response.text,
        usage=Usage(input_tokens=response.input_tokens, output_tokens=response.output_tokens),
        prompt_chars=len(request.system) + len(request.prompt),
    )


def _coerce_role(role: RoleName | str) -> RoleName:
    if isinstance(role, RoleName):
        return role
    try:
        return RoleName(role)
    except ValueError as exc:
        raise KeyError(f"unknown role: {role}") from exc


def _system_prompt(role: RoleName, context: Mapping[str, Any]) -> str:
    custom = context.get("system")
    if isinstance(custom, str) and custom.strip():
        return custom
    return (
        f"You are the {role.value} agent in Slipwright, a multi-agent software delivery "
        "harness. Work only from the context you are given. Respond with a single JSON "
        "object that matches the provided schema and nothing else."
    )


def _user_prompt(context: Mapping[str, Any], output_schema: dict[str, Any]) -> str:
    parts: list[str] = []
    instructions = context.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        parts.append(instructions.strip())
    rest = {k: v for k, v in context.items() if k not in {"system", "instructions"}}
    if rest:
        parts.append("Context:\n" + json.dumps(rest, indent=2, sort_keys=True, default=str))
    parts.append(
        "Respond with one JSON object matching this JSON Schema:\n"
        + json.dumps(output_schema, indent=2, sort_keys=True)
    )
    return "\n\n".join(parts)


def _call_with_timeout(fn: Callable[[], ModelResponse], timeout_s: float) -> ModelResponse:
    # Not a context manager: ``__exit__`` would block on a hung provider call.
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slipwright-invoke")
    try:
        return pool.submit(fn).result(timeout=timeout_s)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


class _MalformedOutput(ValueError):
    pass


def _parse_output(text: str, schema_cls: type[RoleOutput]) -> RoleOutput:
    body = text.strip()
    if (m := _FENCE.match(body)) is not None:
        body = m.group(1)
    if not body:
        raise _MalformedOutput("empty response")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise _MalformedOutput(f"response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise _MalformedOutput(f"expected a JSON object, got {type(data).__name__}")
    try:
        return schema_cls.model_validate(data)
    except ValidationError as exc:
        lines = [f"output does not match {schema_cls.__name__} ({exc.error_count()} error(s)):"]
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "<root>"
            lines.append(f"  - {loc}: {err['msg']}")
        raise _MalformedOutput("\n".join(lines)) from exc


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "InvokeError",
    "InvokeErrorKind",
    "RoleResult",
    "Usage",
    "get_default_provider",
    "invoke_role",
    "set_default_provider",
]
