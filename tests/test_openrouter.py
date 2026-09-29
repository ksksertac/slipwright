"""OpenRouter: the two places where being a reseller changes the rules.

Everything else about it is the OpenAI protocol and is covered by ``test_providers.py``.
What is only true here is that its catalogue is enormous and partly unusable, and that
its catalogue is public -- so the list has to be filtered, and the connection test cannot
be the list.
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
from slipwright.providers import ProviderRejectedError
from slipwright.providers.registry import OPENROUTER, PROVIDERS, Credentials, list_models
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, None)  # no injected provider: routing


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c

CATALOGUE: dict[str, Any] = {
    "data": [
        {
            "id": "anthropic/claude-opus-5",
            "supported_parameters": ["max_tokens", "reasoning", "response_format"],
        },
        {"id": "openai/gpt-5", "supported_parameters": ["response_format", "tools"]},
        # a model that cannot be asked for JSON: OpenRouter drops the parameter rather
        # than refusing, so this one would answer prose and fail three layers away
        {"id": "some/prose-only", "supported_parameters": ["max_tokens", "temperature"]},
        {"id": "some/undeclared"},  # no capabilities listed at all
    ]
}

KEY = "sk-or-v1-real"


def _host(*, key: str = KEY) -> httpx.MockTransport:
    """OpenRouter as it really behaves: /models answers anyone, /key does not."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, content=json.dumps(CATALOGUE))
        if request.url.path.endswith("/key"):
            if request.headers.get("Authorization") != f"Bearer {key}":
                return httpx.Response(401, json={"error": {"message": "User not found."}})
            return httpx.Response(200, json={"data": {"label": "slipwright", "usage": 0}})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _creds(key: str = KEY) -> Credentials:
    return Credentials(
        name=OPENROUTER, api_key=key, base_url=PROVIDERS[OPENROUTER].default_base_url
    )


def test_only_the_models_that_can_answer_in_json_are_offered() -> None:
    """Every role is asked for JSON. A model that cannot be asked for it is not a choice,
    it is a trap, because OpenRouter drops the parameter instead of refusing the call."""
    models = list_models(_creds(), transport=_host())

    assert models == ["anthropic/claude-opus-5", "openai/gpt-5"]
    assert "some/prose-only" not in models
    assert "some/undeclared" not in models  # nothing declared is nothing promised


def test_a_key_that_does_not_exist_does_not_report_a_connection() -> None:
    """Listing models is the connection test everywhere in Slipwright, and OpenRouter's
    catalogue answers 200 to anybody. Without asking /key, any string a person pasted
    would come back as four hundred models available."""
    with pytest.raises(ProviderRejectedError):
        list_models(_creds("sk-or-v1-nonsense"), transport=_host())


def test_the_settings_page_connects_and_lists(client: TestClient, engine: Engine) -> None:
    engine.http_transport = _host()

    saved = client.put(f"/api/settings/providers/{OPENROUTER}", json={"api_key": KEY})
    assert saved.status_code == 200
    row = next(r for r in saved.json() if r["name"] == OPENROUTER)
    assert row["key_set"] and row["default_base_url"] == "https://openrouter.ai/api/v1"

    tested = client.post(f"/api/settings/providers/{OPENROUTER}/test")
    assert tested.status_code == 200
    assert tested.json()["models"] == ["anthropic/claude-opus-5", "openai/gpt-5"]


def test_a_bad_key_is_reported_as_a_bad_key(client: TestClient, engine: Engine) -> None:
    engine.http_transport = _host()
    client.put(f"/api/settings/providers/{OPENROUTER}", json={"api_key": "sk-or-v1-nonsense"})

    tested = client.post(f"/api/settings/providers/{OPENROUTER}/test")
    assert tested.status_code >= 400
