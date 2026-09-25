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


# Calls that reuse a role for something other than its pipeline job, recognised by what
# their instructions say. They are answered from ``discovery`` so a test that overrides
# the role's usual reply (the backlog, the plan) does not lose them.
ASIDES: tuple[tuple[str, str], ...] = (
    ("analysis", "write the project brief"),
    ("intake", "the repository is empty"),
    ("deploy", "propose how this project is deployed"),
    ("deploy_write", "Write the deployment files that were approved"),
    ("gate_triage", "was the failing test itself wrong"),
)


class ScriptedProvider:
    def __init__(self, replies: dict[RoleName, Reply] | None = None) -> None:
        self.replies: dict[RoleName, Reply] = dict(replies or {})
        # keyed by the names in ``ASIDES`` rather than by role
        self.discovery: dict[str, Reply] = {}
        self.requests: list[ModelRequest] = []
        self.translation_tag = "translated"

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        translation = self._translation(request)
        if translation is not None:
            return translation
        reply = self._aside(request) or self.replies.get(request.role)
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

    def _aside(self, request: ModelRequest) -> Reply | None:
        for name, marker in ASIDES:
            if marker in request.prompt:
                return self.discovery.get(name)
        return None

    def _translation(self, request: ModelRequest) -> ModelResponse | None:
        """The translator (``slipwright/translate.py``) asks the same provider for the
        other language. A script has no other language, so each string comes back tagged
        -- enough for a test to see that the page took the translated copy."""
        texts = _translation_request(request)
        if texts is None:
            return None
        answer = json.dumps({"texts": [f"[{self.translation_tag}] {t}" for t in texts]})
        return ModelResponse(text=answer, model=request.model, input_tokens=0, output_tokens=0)


def _translation_request(request: ModelRequest) -> list[str] | None:
    """The strings a translation request carries, or None when it is not one."""
    if "You translate short" not in request.system:
        return None
    start = request.prompt.find('{\n  "texts": [')
    if start < 0:
        return None
    payload, _ = json.JSONDecoder().raw_decode(request.prompt, start)
    texts = payload.get("texts")
    return texts if isinstance(texts, list) else None


def canned(profile: Profile) -> ScriptedProvider:
    """A script that takes any job through every phase with harmless outputs."""
    provider = ScriptedProvider(
        {
            RoleName.PO: {
                "summary": "scripted backlog",
                "breakdown": {
                    "epics": [
                        {
                            "id": "e1",
                            "title": "Record the request",
                            "stories": [
                                {
                                    "id": "s1",
                                    "title": "As a user I can see my request recorded",
                                    "tasks": [
                                        {"id": "t1", "title": "record the request"},
                                    ],
                                }
                            ],
                        }
                    ]
                },
            },
            RoleName.DESIGNER: {
                "summary": "scripted design",
                "principles": ["one column"],
                "screens": [
                    {
                        "name": "Recorded",
                        "platform": "both",
                        "purpose": "see the request recorded",
                        "layout": "the request under a title",
                        "states": ["empty"],
                    }
                ],
            },
            RoleName.ARCHITECT: {
                "summary": "scripted architecture",
                "profile": profile.model_dump(mode="json"),
                "decisions": ["write the request into SLIPWRIGHT.md"],
                "phases": [
                    {"goal": "record the request", "files": ["SLIPWRIGHT.md"], "task_id": "t1"}
                ],
            },
            RoleName.BACKEND: lambda req: {
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
    for specialist in (RoleName.WEB_UI, RoleName.MOBILE_UI):
        provider.replies[specialist] = provider.replies[RoleName.BACKEND]
    provider.discovery = {
        # a failed gate in the canned script is the code's doing, not the test's
        "gate_triage": {
            "summary": "scripted triage: the test asserts what the plan asked for",
            "gate_verdict": "code_is_wrong",
        },
        "analysis": {
            "summary": "scripted analysis",
            "items": [
                {"category": "stack", "title": "Python and FastAPI", "detail": "per the manifest"},
                {"category": "testing", "title": "pytest", "detail": ""},
            ],
        },
        # nothing to deploy: the gate is skipped, so a scripted pipeline still walks
        # end to end. A test that wants the gate replaces this with a real target.
        "deploy": {"summary": "scripted: nothing to deploy", "target": "none", "scripts": []},
        "deploy_write": {
            "summary": "scripted deployment files",
            "changes": [{"path": "deployment/README.md", "content": "# Deployment\n\nScripted.\n"}],
        },
        # asked twice: a round of questions, then the story once they are answered
        "intake": lambda req: (
            {
                "summary": "scripted questions",
                "questions": [
                    {"question": "What is it for?", "why": "scope", "hint": "one sentence"},
                    {"question": "Who uses it?", "why": "audience", "hint": "a role"},
                ],
            }
            if '"rounds": []' in req.prompt
            else {
                "summary": "scripted story",
                "ready": True,
                "story": "Build the thing the answers describe.",
                "items": [
                    {"category": "product", "title": "What it is for", "detail": "as answered"}
                ],
            }
        ),
    }
    return provider


def _request_from(req: ModelRequest) -> str:
    marker = '"request": '
    start = req.prompt.find(marker)
    if start < 0:
        return ""
    end = req.prompt.find("\n", start)
    return str(json.loads(req.prompt[start + len(marker) : end].rstrip(",")))


__all__ = ["Reply", "ScriptedProvider", "canned"]
