from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.config import Settings, build_engine
from slipwright.engine import Engine
from slipwright.providers import (
    ModelRequest,
    ProviderError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from slipwright.providers.openai_compat import OpenAICompatProvider
from slipwright.providers.registry import PROVIDERS, Credentials, RoutingProvider
from slipwright.roles.results import ArchitectResult
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName, ThinkingDepth
from slipwright.store import JobStore
from tests.pipeline import full_engine


class FakeVendor:
    """One OpenAI-compatible endpoint (also answers Anthropic's /v1/models) per host."""

    def __init__(self, key: str, models: list[str]) -> None:
        self.key = key
        self.models = models
        self.requests: list[dict[str, Any]] = []
        self.reply: dict[str, Any] | None = None
        self.finish = "stop"
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        api_key = request.headers.get("x-api-key", "")
        if auth != f"Bearer {self.key}" and api_key != self.key:
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in self.models]})
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            self.requests.append(body)
            if self.status != 200:
                return httpx.Response(self.status, json={"error": {"message": "boom"}})
            text = json.dumps(self.reply or {"summary": "ok", "phases": [{"goal": "g"}]})
            return httpx.Response(
                200,
                json={
                    "model": body["model"],
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": text},
                            "finish_reason": self.finish,
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                },
            )
        return httpx.Response(404, json={"error": {"message": "no route"}})


def _request(
    model: str = "m", provider: str | None = None, depth: ThinkingDepth = ThinkingDepth.HIGH
) -> ModelRequest:
    return ModelRequest(
        role=RoleName.ARCHITECT,
        model=model,
        provider=provider,
        thinking_depth=depth,
        system="sys",
        prompt="do it",
        output_schema=ArchitectResult.model_json_schema(),
        timeout_s=5,
    )


# --- OpenAI-compatible provider ---------------------------------------------------------------


def test_openai_compat_request_and_response() -> None:
    vendor = FakeVendor("sk-test", ["a-model", "b-model"])
    provider = OpenAICompatProvider(
        "sk-test", "https://api.example.test/v1", transport=httpx.MockTransport(vendor.handler)
    )
    resp = provider.complete(_request("a-model"))
    assert json.loads(resp.text)["summary"] == "ok"
    assert (resp.model, resp.input_tokens, resp.output_tokens) == ("a-model", 10, 5)
    body = vendor.requests[0]
    assert body["model"] == "a-model"
    assert body["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do it"},
    ]
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "high" and body["max_tokens"] == 16_000
    assert provider.list_models() == ["a-model", "b-model"]

    # depth mapping and vendor knobs
    provider.complete(_request(depth=ThinkingDepth.OFF))
    assert "reasoning_effort" not in vendor.requests[-1]
    provider.complete(_request(depth=ThinkingDepth.MAX))
    assert vendor.requests[-1]["reasoning_effort"] == "high"
    no_effort = OpenAICompatProvider(
        "sk-test",
        "https://api.example.test",
        supports_effort=False,
        max_tokens_param="max_completion_tokens",
        transport=httpx.MockTransport(vendor.handler),
    )
    no_effort.complete(_request())
    assert "reasoning_effort" not in vendor.requests[-1]
    assert "max_completion_tokens" in vendor.requests[-1]


def test_openai_compat_errors_are_typed() -> None:
    vendor = FakeVendor("sk-test", [])
    transport = httpx.MockTransport(vendor.handler)
    with pytest.raises(ProviderError, match="401"):
        OpenAICompatProvider("wrong", "https://x.test", transport=transport).complete(_request())
    provider = OpenAICompatProvider("sk-test", "https://x.test", transport=transport)
    vendor.finish = "content_filter"
    with pytest.raises(ProviderRefusalError):
        provider.complete(_request())
    vendor.finish = "length"
    with pytest.raises(ProviderError, match="truncated"):
        provider.complete(_request())
    vendor.finish, vendor.status = "stop", 500
    with pytest.raises(ProviderError, match="500"):
        provider.complete(_request())
    with pytest.raises(ProviderError):
        OpenAICompatProvider("", "https://x.test")

    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(ProviderTimeoutError):
        OpenAICompatProvider(
            "k", "https://x.test", transport=httpx.MockTransport(timeout)
        ).complete(_request())


# --- routing ---------------------------------------------------------------------------------


def test_routing_provider_dispatches_by_role_provider() -> None:
    vendors = {
        "openai": FakeVendor("sk-openai", ["gpt-model"]),
        "deepseek": FakeVendor("sk-deep", ["deep-model"]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        vendor = vendors["deepseek" if "deepseek" in request.url.host else "openai"]
        return vendor.handler(request)

    creds = {
        "openai": Credentials(
            name="openai", api_key="sk-openai", base_url=PROVIDERS["openai"].default_base_url
        ),
        "deepseek": Credentials(
            name="deepseek", api_key="sk-deep", base_url=PROVIDERS["deepseek"].default_base_url
        ),
    }
    router = RoutingProvider(
        creds.get, default=lambda: "openai", transport=httpx.MockTransport(handler)
    )
    router.complete(_request("gpt-model", "openai"))
    router.complete(_request("deep-model", "deepseek"))
    router.complete(_request("gpt-model", None))  # default
    assert [r["model"] for r in vendors["openai"].requests] == ["gpt-model", "gpt-model"]
    assert [r["model"] for r in vendors["deepseek"].requests] == ["deep-model"]
    assert "reasoning_effort" in vendors["openai"].requests[0]
    assert "reasoning_effort" not in vendors["deepseek"].requests[0]  # DeepSeek: no effort knob
    assert router.client_for("openai") is router.client_for("openai")  # cached
    with pytest.raises(ProviderUnavailableError, match="no API key for Anthropic"):
        router.client_for("anthropic")
    with pytest.raises(ProviderUnavailableError, match="unknown provider"):
        router.client_for("bogus")


# --- engine + settings -----------------------------------------------------------------------


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, None)  # no injected provider: routing


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_credentials_come_from_settings_then_environment(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    for spec in PROVIDERS.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    assert engine.provider_credentials("openai") is None
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    env = engine.provider_credentials("openai")
    assert env is not None and env.api_key == "sk-env"
    assert env.base_url == PROVIDERS["openai"].default_base_url
    engine.update_provider_settings(
        "openai", api_key="sk-stored", base_url="https://proxy.test/v1/"
    )
    stored = engine.provider_credentials("openai")
    assert stored is not None and (stored.api_key, stored.base_url) == (
        "sk-stored",
        "https://proxy.test/v1",
    )
    rows = {r["name"]: r for r in engine.provider_settings()}
    assert rows["openai"]["key_set"] and rows["openai"]["key_hint"] == "…ored"
    assert rows["openai"]["key_from_env"] is False
    assert rows["anthropic"]["is_default"] is True
    engine.update_provider_settings("deepseek", api_key="sk-d", make_default=True)
    assert engine.default_provider_name() == "deepseek"
    engine.update_provider_settings("openai", clear_key=True)
    assert engine.provider_settings()[1]["key_from_env"] is True  # falls back to the env var
    assert engine.provider_credentials("bogus") is None


def test_roles_run_on_the_provider_named_in_the_profile(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for spec in PROVIDERS.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    vendors = {"openai": FakeVendor("sk-o", []), "deepseek": FakeVendor("sk-d", [])}
    # the PO (on DeepSeek) returns a backlog; the Architect (on OpenAI) a matching plan
    from tests.pipeline import default_backlog

    po_reply = {"summary": "s", "breakdown": default_backlog(1)}
    architect_reply = {
        "summary": "s",
        "profile": seed.model_dump(mode="json"),
        "decisions": [],
        "phases": [{"goal": "g", "task_id": "t1"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        vendor = vendors["deepseek" if "deepseek" in request.url.host else "openai"]
        body = request.content.decode()
        vendor.reply = po_reply if "You are the po agent" in body else architect_reply
        return vendor.handler(request)

    data = seed.model_dump(mode="json")
    data["roles"]["po"]["provider"] = "deepseek"
    data["roles"]["architect"]["provider"] = "openai"
    routed = Profile.model_validate(data)
    engine = full_engine(
        store, worktrees_root, routed, None, http_transport=httpx.MockTransport(handler)
    )
    engine.update_provider_settings("openai", api_key="sk-o")
    engine.update_provider_settings("deepseek", api_key="sk-d")

    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL, job.history[-1].detail
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL, job.history[-1].detail
    assert [r["model"] for r in vendors["deepseek"].requests] == [routed.roles[RoleName.PO].model]
    assert [r["model"] for r in vendors["openai"].requests] == [
        routed.roles[RoleName.ARCHITECT].model
    ]

    # a role whose provider has no key fails the job with a readable reason, not a crash
    engine.update_provider_settings("openai", clear_key=True)
    other = engine.start(engine.create_job("y", repo).id)
    other = engine.approve(other.id)
    assert other.state is JobState.FAILED
    assert "provider_unavailable" in (other.history[-1].note or "")
    assert "Settings → Models" in (other.history[-1].detail or "")


def test_provider_settings_endpoints(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    for spec in PROVIDERS.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    vendor = FakeVendor("sk-test", ["model-one", "model-two"])
    engine.http_transport = httpx.MockTransport(vendor.handler)

    rows = client.get("/api/settings/providers").json()
    assert [r["name"] for r in rows] == ["anthropic", "openai", "deepseek"]
    assert all(r["key_set"] is False for r in rows)
    assert rows[1]["label"] == "OpenAI (ChatGPT)" and rows[2]["env_var"] == "DEEPSEEK_API_KEY"
    assert client.post("/api/settings/providers/openai/test").status_code == 400
    assert client.get("/api/settings/providers/bogus/models").status_code == 404

    resp = client.put(
        "/api/settings/providers/openai", json={"api_key": "sk-test", "make_default": True}
    )
    assert resp.status_code == 200
    openai = next(r for r in resp.json() if r["name"] == "openai")
    assert openai["key_set"] and openai["key_hint"] == "…test" and openai["is_default"]
    assert "api_key" not in openai and "sk-test" not in resp.text
    assert client.post("/api/settings/providers/openai/test").json() == {
        "name": "openai",
        "models": ["model-one", "model-two"],
    }
    assert client.get("/api/settings/providers/openai/models").json()["models"] == [
        "model-one",
        "model-two",
    ]

    # the Anthropic listing goes through the SDK against the same fake
    client.put("/api/settings/providers/anthropic", json={"api_key": "sk-test"})
    assert client.post("/api/settings/providers/anthropic/test").json()["models"] == [
        "model-one",
        "model-two",
    ]
    client.put("/api/settings/providers/deepseek", json={"api_key": "wrong"})
    assert client.post("/api/settings/providers/deepseek/test").status_code == 502


def test_provider_settings_are_admin_only(engine: Engine) -> None:
    engine.store.create_user("ada", "pw")
    engine.store.create_user("bob", "pw")
    with TestClient(create_app(engine, resume_on_startup=False)) as c:
        c.post("/api/auth/login", json={"username": "bob", "password": "pw"})
        assert c.get("/api/settings/providers").status_code == 200
        assert c.put("/api/settings/providers/openai", json={"api_key": "x"}).status_code == 403
        assert c.post("/api/settings/providers/openai/test").status_code == 403


def test_serve_provider_names(tmp_path: Path) -> None:
    for name in ("live", "anthropic"):
        settings = Settings.from_env(
            {"SLIPWRIGHT_STATE_DIR": str(tmp_path / name), "SLIPWRIGHT_PROVIDER": name}
        )
        engine = build_engine(settings)
        assert isinstance(engine.provider, RoutingProvider)
        engine.store.close()
    assert Settings.from_env({}).provider == "live"
    with pytest.raises(ValueError, match="unknown provider"):
        build_engine(
            Settings.from_env(
                {"SLIPWRIGHT_STATE_DIR": str(tmp_path / "x"), "SLIPWRIGHT_PROVIDER": "nope"}
            )
        )


def test_models_settings_page_and_role_provider_column_exist() -> None:
    web = Path(__file__).resolve().parent.parent / "web" / "src"
    page = (web / "pages" / "settings" / "ModelsSettingsPage.tsx").read_text(encoding="utf-8")
    for expected in (
        "useProviders",
        "useTestProvider",
        'type="password"',
        "Use as default",
        "key_from_env",
    ):
        assert expected in page, expected
    form = (web / "components" / "ProfileForm.tsx").read_text(encoding="utf-8")
    assert "useProviderModels" in form and "provider: e.target.value" in form and "datalist" in form
    hooks = (web / "api" / "hooks.ts").read_text(encoding="utf-8")
    assert "/api/settings/providers" in hooks


def test_default_roles_follow_the_default_provider_and_its_default_model(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Making DeepSeek the default under Settings -> Models must route every role that
    names no provider there, on DeepSeek's configured default model -- not on the Claude
    model name written in the profile."""
    for spec in PROVIDERS.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    vendor = FakeVendor("sk-d", ["deep-model"])
    from tests.pipeline import default_backlog

    vendor.reply = {"summary": "s", "breakdown": default_backlog(1)}
    engine = full_engine(
        store, worktrees_root, seed, None, http_transport=httpx.MockTransport(vendor.handler)
    )
    engine.update_provider_settings(
        "deepseek", api_key="sk-d", make_default=True, default_model="deep-model"
    )
    assert engine.provider_settings()[2]["default_model"] == "deep-model"
    assert engine.effective_routing(seed.roles[RoleName.PO]) == ("deepseek", "deep-model")
    pinned = seed.roles[RoleName.PO].model_copy(update={"provider": "openai"})
    assert engine.effective_routing(pinned) == ("openai", pinned.model)  # pinned: as written

    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL, job.history[-1].detail
    assert [r["model"] for r in vendor.requests] == ["deep-model"]
    assert seed.roles[RoleName.PO].model != "deep-model"  # the profile still says Claude

    # without a default model the profile's model is used as written
    engine.update_provider_settings("deepseek", default_model="")
    assert engine.effective_routing(seed.roles[RoleName.PO]) == (
        "deepseek",
        seed.roles[RoleName.PO].model,
    )

    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        agents = {a["role"]: a for a in client.get("/api/agents").json()}
        assert agents["po"]["effective_provider"] == "deepseek"
        assert agents["po"]["effective_model"] == seed.roles[RoleName.PO].model
        resp = client.put("/api/settings/providers/deepseek", json={"default_model": "deep-model"})
        assert resp.status_code == 200
        assert [p for p in resp.json() if p["name"] == "deepseek"][0][
            "default_model"
        ] == "deep-model"
        agents = {a["role"]: a for a in client.get("/api/agents").json()}
        assert agents["po"]["effective_model"] == "deep-model" and agents["po"]["provider"] is None
