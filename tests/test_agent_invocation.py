from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from slipwright import invoke
from slipwright.invoke import InvokeErrorKind, RoleResult, invoke_role
from slipwright.providers import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRefusalError,
    ProviderTimeoutError,
)
from slipwright.roles.results import RESULT_SCHEMAS, ArchitectResult, POResult
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth, load_profile

ROOT = Path(__file__).resolve().parent.parent
_PROFILE = load_profile(ROOT / "examples" / "python-fastapi.profile.json")
PLAN_JSON = json.dumps(
    {
        "summary": "one phase",
        "profile": _PROFILE.model_dump(mode="json"),
        "decisions": [],
        "phases": [{"goal": "add endpoint", "files": ["app/main.py"], "task_id": "t1"}],
    }
)
BACKLOG_JSON = json.dumps(
    {
        "summary": "backlog",
        "breakdown": {
            "epics": [
                {
                    "title": "E",
                    "stories": [{"title": "S", "tasks": [{"id": "t1", "title": "add endpoint"}]}],
                }
            ]
        },
    }
)


@pytest.fixture
def profile() -> Profile:
    return load_profile(ROOT / "examples" / "python-fastapi.profile.json")


class FakeProvider:
    """Records requests; replies with fixed text, or raises/sleeps on demand."""

    def __init__(
        self,
        text: str = PLAN_JSON,
        *,
        raises: Exception | None = None,
        delay_s: float = 0.0,
        reply: Callable[[ModelRequest], str] | None = None,
    ) -> None:
        self.text = text
        self.raises = raises
        self.delay_s = delay_s
        self.reply = reply
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.raises is not None:
            raise self.raises
        text = self.reply(request) if self.reply else self.text
        return ModelResponse(text=text, model=request.model, input_tokens=10, output_tokens=5)


@pytest.fixture(autouse=True)
def _no_default_provider() -> None:
    invoke.set_default_provider(None)


# --- model routing -----------------------------------------------------------------------


@pytest.mark.parametrize("role", list(RoleName))
def test_request_uses_model_and_depth_from_profile(profile: Profile, role: RoleName) -> None:
    provider = FakeProvider()
    invoke_role(role, profile, {}, provider=provider)

    (request,) = provider.requests
    role_cfg = profile.roles[role]
    assert request.role is role
    assert request.model == role_cfg.model
    assert request.thinking_depth is role_cfg.thinking_depth
    assert request.permissions == tuple(role_cfg.permissions)
    assert request.output_schema == RESULT_SCHEMAS[role].model_json_schema()


def test_changing_profile_model_changes_request(profile: Profile) -> None:
    data = profile.model_dump(mode="json")
    data["roles"]["architect"]["model"] = "some-other-model"
    data["roles"]["architect"]["thinking_depth"] = "off"
    changed = Profile.model_validate(data)

    provider = FakeProvider()
    result = invoke_role(RoleName.ARCHITECT, changed, {}, provider=provider)

    assert provider.requests[0].model == "some-other-model"
    assert provider.requests[0].thinking_depth is ThinkingDepth.OFF
    assert result.model == "some-other-model"


def test_engine_has_no_hardcoded_model_names() -> None:
    pattern = re.compile(
        r"(?i)\b(claude|gpt|gemini|llama|mistral)-[0-9a-z]|\b(opus|sonnet|haiku)\b"
    )
    offenders = [
        f"{path.relative_to(ROOT)}: {line.strip()}"
        for path in (ROOT / "slipwright").rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if pattern.search(line)
    ]
    assert offenders == []


# --- prompt assembly ---------------------------------------------------------------------


def test_context_is_rendered_into_prompt(profile: Profile) -> None:
    provider = FakeProvider()
    invoke_role(
        RoleName.ARCHITECT,
        profile,
        {"system": "custom system", "instructions": "do the thing", "request": "add login"},
        provider=provider,
    )

    (request,) = provider.requests
    assert request.system == "custom system"
    assert request.prompt.startswith("do the thing")
    assert '"request": "add login"' in request.prompt
    assert "JSON Schema" in request.prompt


def test_default_system_prompt_names_role(profile: Profile) -> None:
    provider = FakeProvider()
    invoke_role(RoleName.QA, profile, {}, provider=provider)
    assert "qa agent" in provider.requests[0].system


# --- structured output -------------------------------------------------------------------


def test_valid_output_is_parsed_into_role_schema(profile: Profile) -> None:
    result = invoke_role(RoleName.ARCHITECT, profile, {}, provider=FakeProvider())

    assert result.ok
    assert isinstance(result.output, ArchitectResult)
    assert result.output.phases[0].goal == "add endpoint"
    assert result.raw_text == PLAN_JSON
    assert result.usage is not None and result.usage.input_tokens == 10


def test_fenced_json_is_accepted(profile: Profile) -> None:
    provider = FakeProvider(f"```json\n{PLAN_JSON}\n```")
    result = invoke_role(RoleName.ARCHITECT, profile, {}, provider=provider)
    assert result.ok


def test_po_output_validates_backlog(profile: Profile) -> None:
    result = invoke_role(RoleName.PO, profile, {}, provider=FakeProvider(BACKLOG_JSON))

    assert result.ok
    assert isinstance(result.output, POResult)
    assert [t.id for t in result.output.breakdown.tasks()] == ["t1"]


def test_result_round_trips_through_json(profile: Profile) -> None:
    result = invoke_role(RoleName.ARCHITECT, profile, {}, provider=FakeProvider())
    dumped = result.model_dump(mode="json")
    assert dumped["output"]["phases"][0]["goal"] == "add endpoint"
    assert RoleResult.model_validate(dumped).role is RoleName.ARCHITECT


# --- typed failures ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["", "not json at all", "[1, 2, 3]", '{"summary": "no phases"}', '{"phases": []}'],
)
def test_malformed_output_returns_typed_error(profile: Profile, text: str) -> None:
    result = invoke_role(RoleName.ARCHITECT, profile, {}, provider=FakeProvider(text))

    assert not result.ok
    assert result.error is not None
    assert result.error.kind is InvokeErrorKind.MALFORMED_OUTPUT
    assert result.output is None
    assert result.raw_text == text


def test_schema_violation_message_is_readable(profile: Profile) -> None:
    result = invoke_role(
        RoleName.ARCHITECT, profile, {}, provider=FakeProvider('{"summary": "x", "phases": []}')
    )
    assert result.error is not None
    assert "ArchitectResult" in result.error.message
    assert "phases" in result.error.message


def test_slow_provider_times_out(profile: Profile) -> None:
    provider = FakeProvider(delay_s=1.0)
    result = invoke_role(RoleName.ARCHITECT, profile, {}, provider=provider, timeout_s=0.05)

    assert result.error is not None
    assert result.error.kind is InvokeErrorKind.TIMEOUT


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ProviderTimeoutError("slow"), InvokeErrorKind.TIMEOUT),
        (ProviderRefusalError("nope"), InvokeErrorKind.REFUSED),
        (ProviderError("500"), InvokeErrorKind.PROVIDER_ERROR),
        (RuntimeError("boom"), InvokeErrorKind.PROVIDER_ERROR),
    ],
)
def test_provider_failures_never_raise(
    profile: Profile, exc: Exception, kind: InvokeErrorKind
) -> None:
    result = invoke_role(RoleName.ARCHITECT, profile, {}, provider=FakeProvider(raises=exc))

    assert not result.ok
    assert result.error is not None
    assert result.error.kind is kind
    assert str(exc) in result.error.message


def test_unknown_role_is_a_programmer_error(profile: Profile) -> None:
    with pytest.raises(KeyError):
        invoke_role("bogus-role", profile, {}, provider=FakeProvider())


def test_default_provider_is_used_when_none_given(profile: Profile) -> None:
    provider = FakeProvider()
    invoke.set_default_provider(provider)
    result = invoke_role(RoleName.ARCHITECT, profile, {})
    assert result.ok
    assert len(provider.requests) == 1
