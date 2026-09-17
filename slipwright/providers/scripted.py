"""A provider that answers from a script instead of a model.

Used by tests and by ``slipwright --provider scripted`` to exercise the whole pipeline
without network access. Each role maps to a reply: a JSON string, a dict, or a callable
taking the ``ModelRequest``. ``canned`` builds a script that walks a job end to end.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from slipwright.providers import ModelRequest, ModelResponse, ProviderError
from slipwright.schemas.profile import Profile, RoleName

Reply = (
    str | dict[str, Any] | BaseModel | Callable[[ModelRequest], "str | dict[str, Any] | BaseModel"]
)


class ScriptedProvider:
    def __init__(self, replies: dict[RoleName, Reply] | None = None) -> None:
        self.replies: dict[RoleName, Reply] = dict(replies or {})
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        reply = self.replies.get(request.role)
        if reply is None:
            raise ProviderError(f"no scripted reply for role {request.role.value}")
        if callable(reply) and not isinstance(reply, BaseModel):
            reply = reply(request)
        if isinstance(reply, BaseModel):
            text = reply.model_dump_json()
        elif isinstance(reply, dict):
            text = json.dumps(reply)
        else:
            text = reply
        return ModelResponse(text=text, model=request.model, input_tokens=0, output_tokens=0)


def canned(profile: Profile) -> ScriptedProvider:
    """A script that takes any job through every phase with harmless outputs."""
    provider = ScriptedProvider(
        {
            RoleName.ANALYST: {
                "summary": "scripted analysis",
                "profile": profile.model_dump(mode="json"),
            },
            RoleName.PLANNER: {
                "summary": "scripted plan",
                "phases": [{"goal": "record the request", "files": ["SLIPWRIGHT.md"]}],
            },
            RoleName.DEVELOPER: lambda req: {
                "summary": "scripted development",
                "phase_complete": True,
                "changes": [
                    {
                        "path": "SLIPWRIGHT.md",
                        "content": f"# Slipwright\n\n{_request_from(req)}\n",
                    }
                ],
            },
            RoleName.QA: lambda req: (
                {
                    "summary": "scripted test plan",
                    "test_cases": [{"name": "smoke", "description": "the project imports"}],
                }
                if '"stage": 1' in req.prompt
                else {"summary": "scripted tests", "changes": []}
            ),
            RoleName.DEVOPS: {
                "summary": "scripted devops",
                "pr_title": "Slipwright change",
                "pr_body": "Automated change.",
            },
            RoleName.SUPERVISOR: {
                "summary": "scripted supervisor",
                "decision": "approve",
                "confidence": 0.9,
                "risk": "low",
                "reasons": ["scripted"],
            },
        }
    )
    for specialist in (RoleName.BACKEND, RoleName.WEB_UI, RoleName.MOBILE_UI):
        provider.replies[specialist] = provider.replies[RoleName.DEVELOPER]
    return provider


def _request_from(req: ModelRequest) -> str:
    marker = '"request": '
    start = req.prompt.find(marker)
    if start < 0:
        return ""
    end = req.prompt.find("\n", start)
    return str(json.loads(req.prompt[start + len(marker) : end].rstrip(",")))


__all__ = ["Reply", "ScriptedProvider", "canned"]
