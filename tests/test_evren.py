"""EVREN: the three places where its gateway differs from the OpenAI protocol it speaks.

Everything else is ``OpenAICompatProvider`` and is covered by ``test_providers.py``. The
host below answers as the live API did on 2026-09-30: a catalogue that says what each
model is for and can do, a 400 for ``reasoning_effort`` sent to a model without it, and a
403 on everything until the key's owner has accepted the terms.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.providers import ModelRequest, ProviderRejectedError
from slipwright.providers.evren import EvrenProvider
from slipwright.providers.registry import EVREN, PROVIDERS, Credentials, build_client, list_models
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth
from slipwright.store import JobStore
from tests.pipeline import full_engine

KEY = "evren_llm_real"


def _model(id_: str, task: str = "chat", **caps: bool) -> dict[str, Any]:
    return {"id": id_, "task": task, "capabilities": caps}


CATALOGUE: dict[str, Any] = {
    "data": [
        _model("glm-5.3", response_format=True, reasoning_effort=True),
        _model("gemma-4-31b", response_format=True, reasoning_effort=False),
        _model("qwen3-vl-30b", task="vision_chat", response_format=True),
        # a router: a different model per call, and no promise of JSON
        _model("auto", response_format=False),
        _model("dots-ocr", task="ocr", response_format=True),
        _model("qwen3-embedding-8b", task="embedding"),
    ]
}

TERMS_TEXT = "# EVREN LLM Gateway — Kullanım Şartları\n\n..."


class Evren:
    """The gateway, with a key whose terms are accepted or not yet."""

    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.bodies: list[dict[str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1")
        if request.headers.get("Authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json=_error("Geçersiz API anahtarı", "unauthorized"))
        if path == "/terms/status":
            return httpx.Response(
                200, json={"current_version": 1, "is_material": True, "accepted": self.accepted}
            )
        if path == "/terms/text":
            return httpx.Response(200, json={"version": 1, "content": TERMS_TEXT})
        if path == "/terms/accept":
            if json.loads(request.content) != {"version": 1}:
                return httpx.Response(409, json=_error("sürüm güncel değil", "stale_version"))
            self.accepted = True
            return httpx.Response(200, json={"accepted_version": 1})
        if not self.accepted:
            return httpx.Response(
                403,
                json=_error("kullanım şartlarını kabul etmeniz gerekiyor", "terms_not_accepted"),
            )
        if path == "/models":
            return httpx.Response(200, json=CATALOGUE)
        if path == "/chat/completions":
            body = json.loads(request.content)
            self.bodies.append(body)
            if body["model"] == "gemma-4-31b" and "reasoning_effort" in body:
                return httpx.Response(
                    400, json=_error("'reasoning_effort' parametresini desteklemiyor", "bad")
                )
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        return httpx.Response(404)


def _error(message: str, code: str) -> dict[str, Any]:
    return {"error": {"message": message, "type": "error", "code": code}}


def _creds(key: str = KEY) -> Credentials:
    return Credentials(name=EVREN, api_key=key, base_url=PROVIDERS[EVREN].default_base_url)


def _ask(model: str, depth: ThinkingDepth = ThinkingDepth.HIGH) -> ModelRequest:
    return ModelRequest(
        role=RoleName.PO,
        model=model,
        thinking_depth=depth,
        system="Answer in JSON.",
        prompt="Say ok.",
        output_schema={"type": "object"},
        timeout_s=30,
    )


def test_only_chat_models_that_answer_in_json_are_offered() -> None:
    """OCR, embeddings and the ``auto`` router are in the same catalogue. None of them
    can be an agent, so none of them is a choice."""
    models = list_models(_creds(), transport=Evren().transport())

    # a vision model converses too; it can also look at pictures
    assert models == ["gemma-4-31b", "glm-5.3", "qwen3-vl-30b"]


def test_thinking_depth_reaches_the_models_that_take_it_and_spares_the_ones_that_refuse_it() -> (
    None
):
    host = Evren()
    client = build_client(_creds(), transport=host.transport())

    assert client.complete(_ask("glm-5.3")).text == '{"ok": true}'
    assert client.complete(_ask("gemma-4-31b")).text == '{"ok": true}'

    glm, gemma = host.bodies
    assert glm["reasoning_effort"] == "high"
    assert "reasoning_effort" not in gemma


def test_a_model_the_catalogue_does_not_know_is_asked_without_reasoning_effort() -> None:
    """Unknown means no: without the parameter a model answers, with it one can refuse."""
    host = Evren()
    build_client(_creds(), transport=host.transport()).complete(_ask("brand-new-model"))

    assert "reasoning_effort" not in host.bodies[0]


def test_a_key_whose_terms_are_not_accepted_says_where_to_accept_them() -> None:
    with pytest.raises(ProviderRejectedError, match="Settings → Models → EVREN"):
        list_models(_creds(), transport=Evren(accepted=False).transport())


def test_a_development_meeting_unaccepted_terms_stops_saying_why() -> None:
    """EVREN publishing a material new version refuses every call until it is accepted
    again: the job has to say so, not "API error 403"."""
    client = build_client(_creds(), transport=Evren(accepted=False).transport())

    with pytest.raises(ProviderRejectedError, match="terms of use have not been accepted"):
        client.complete(_ask("glm-5.3"))


def test_a_platform_key_is_named_as_the_wrong_kind_not_as_invalid() -> None:
    """The account page issues three kinds of key and the gateway calls the other two
    "invalid", which sends a person to check a key that is perfectly good."""
    with pytest.raises(ProviderRejectedError, match="platform key.*evren_llm_"):
        list_models(_creds("evren_plt_abc"), transport=Evren().transport())


def test_nothing_is_accepted_merely_by_asking_about_the_terms() -> None:
    host = Evren(accepted=False)
    client = build_client(_creds(), transport=host.transport())
    assert isinstance(client, EvrenProvider)

    terms = client.terms()

    assert (terms.version, terms.accepted) == (1, False)
    assert terms.text.startswith("# EVREN")
    assert host.accepted is False


# -- through the settings page ------------------------------------------------------------


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, None)  # no injected provider: routing


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_the_terms_are_shown_then_accepted_on_the_persons_press(
    client: TestClient, engine: Engine
) -> None:
    host = Evren(accepted=False)
    engine.http_transport = host.transport()
    saved = client.put(f"/api/settings/providers/{EVREN}", json={"api_key": KEY})
    assert next(r for r in saved.json() if r["name"] == EVREN)["has_terms"] is True

    assert client.post(f"/api/settings/providers/{EVREN}/test").status_code == 502
    shown = client.get(f"/api/settings/providers/{EVREN}/terms").json()
    assert shown["accepted"] is False and shown["version"] == 1 and shown["text"]
    assert host.accepted is False  # reading them signed nothing

    accepted = client.post(f"/api/settings/providers/{EVREN}/terms", json={"version": 1})
    assert accepted.status_code == 200 and accepted.json()["accepted"] is True

    tested = client.post(f"/api/settings/providers/{EVREN}/test")
    assert tested.json()["models"] == ["gemma-4-31b", "glm-5.3", "qwen3-vl-30b"]


def test_a_version_the_person_was_not_shown_is_not_signed(
    client: TestClient, engine: Engine
) -> None:
    host = Evren(accepted=False)
    engine.http_transport = host.transport()
    client.put(f"/api/settings/providers/{EVREN}", json={"api_key": KEY})

    refused = client.post(f"/api/settings/providers/{EVREN}/terms", json={"version": 2})

    assert refused.status_code == 502
    assert host.accepted is False


def test_a_vendor_without_terms_has_none_to_accept(client: TestClient) -> None:
    assert client.get("/api/settings/providers/openai/terms").status_code == 404
