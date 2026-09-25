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
    assert body["reasoning_effort"] == "high" and body["max_tokens"] == 32_000
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


def test_a_vendor_that_refuses_the_account_ends_the_step_at_once() -> None:
    """No balance, a bad key: the second call is refused for the same reason as the first.

    So it is not a retryable failure. Spending the role's retries on it wastes the wait
    and tells the person `provider_error after 3 attempts` when what happened was that
    the account has nothing left to spend.
    """
    from slipwright.invoke import RETRYABLE, InvokeErrorKind
    from slipwright.providers import ProviderRejectedError

    def broke(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "Insufficient Balance"}})

    provider = OpenAICompatProvider(
        "sk-test", "https://x.test", transport=httpx.MockTransport(broke)
    )
    with pytest.raises(ProviderRejectedError, match="Insufficient Balance"):
        provider.complete(_request())
    assert InvokeErrorKind.PROVIDER_REJECTED not in RETRYABLE

    # a 500 is the vendor having a bad minute, and that is worth asking again
    def wobble(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "upstream"}})

    with pytest.raises(ProviderError, match="500"):
        OpenAICompatProvider(
            "sk-test", "https://x.test", transport=httpx.MockTransport(wobble)
        ).complete(_request())


def test_a_model_call_that_never_left_is_made_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dropped handshake costs a development its step, and nothing was charged for it.

    The connection never opened, so the vendor has no call to bill and none to answer;
    sending it again is the difference between a step that fails and one that runs. A read
    that dies half way through is a different thing and stays a failure: something was
    sent, and asking again would pay for the same answer twice.
    """
    from slipwright import net

    monkeypatch.setattr(net.time, "sleep", lambda _s: None)
    vendor = FakeVendor("sk-test", [])
    tries = 0

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal tries
        tries += 1
        if tries < 3:
            raise httpx.ConnectError("[SSL: UNEXPECTED_EOF_WHILE_READING]", request=request)
        return vendor.handler(request)

    provider = OpenAICompatProvider(
        "sk-test", "https://x.test", transport=httpx.MockTransport(flaky)
    )
    assert provider.complete(_request()).text  # the third try is the one that arrives
    assert tries == 3

    def cut(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("the answer stopped half way")

    with pytest.raises(ProviderError, match="connection error"):
        OpenAICompatProvider(
            "sk-test", "https://x.test", transport=httpx.MockTransport(cut)
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
    assert [r["name"] for r in rows] == list(PROVIDERS)
    assert rows[0]["name"] == "anthropic"  # the built-in default comes first
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


def test_a_model_key_belongs_to_the_account_that_entered_it(engine: Engine) -> None:
    """Everybody brings their own key, so everybody may enter one -- and sees only theirs."""
    engine.store.create_user("ada", "pw")  # admin
    engine.store.create_user("bob", "pw")
    app = create_app(engine, resume_on_startup=False)

    def openai_row(person: TestClient) -> dict[str, object]:
        rows = person.get("/api/settings/providers").json()
        return next(r for r in rows if r["name"] == "openai")

    with TestClient(app) as bob, TestClient(app) as ada:
        bob.post("/api/auth/login", json={"username": "bob", "password": "pw"})
        ada.post("/api/auth/login", json={"username": "ada", "password": "pw"})

        assert bob.get("/api/settings/providers").status_code == 200
        saved = bob.put("/api/settings/providers/openai", json={"api_key": "sk-bob-9876"})
        assert saved.status_code == 200, saved.text

        mine = openai_row(bob)
        assert mine["key_set"] is True and mine["key_hint"] == "…9876"
        assert "sk-bob-9876" not in bob.get("/api/settings/providers").text
        assert openai_row(ada)["key_set"] is False, "the admin must not inherit bob's key"


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
    # an agent's page pins it to a provider and model and can test the connection
    agent = (web / "pages" / "AgentDetailPage.tsx").read_text(encoding="utf-8")
    assert "useAssignAgent" in agent and "useTestProvider" in agent and "assigned_model" in agent


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


def test_an_agent_assigned_a_model_runs_on_it_whatever_the_profile_says(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pinning the PO to OpenAI's ``gpt-model`` under Agents must win over both the
    project profile (which names DeepSeek) and the default provider; clearing the pin
    puts the profile back in charge."""
    for spec in PROVIDERS.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    vendors = {"openai": FakeVendor("sk-o", ["gpt-model"]), "deepseek": FakeVendor("sk-d", [])}
    from tests.pipeline import default_backlog

    def handler(request: httpx.Request) -> httpx.Response:
        vendor = vendors["deepseek" if "deepseek" in request.url.host else "openai"]
        vendor.reply = {"summary": "s", "breakdown": default_backlog(1)}
        return vendor.handler(request)

    data = seed.model_dump(mode="json")
    data["roles"]["po"]["provider"] = "deepseek"
    routed = Profile.model_validate(data)
    engine = full_engine(
        store, worktrees_root, routed, None, http_transport=httpx.MockTransport(handler)
    )
    engine.update_provider_settings("deepseek", api_key="sk-d", make_default=True)

    # no key for OpenAI yet: the assignment is refused, not saved
    with pytest.raises(ProviderUnavailableError, match="no API key for OpenAI"):
        engine.assign_agent(RoleName.PO, "openai", "gpt-model")
    assert engine.agent_routing("po") is None
    with pytest.raises(ValueError, match="unknown provider"):
        engine.assign_agent(RoleName.PO, "bogus", "m")
    with pytest.raises(ValueError, match="pick a model"):
        engine.assign_agent(RoleName.PO, "deepseek", "")

    engine.update_provider_settings("openai", api_key="sk-o")
    engine.assign_agent(RoleName.PO, "openai", "gpt-model")
    assert engine.agent_routing("po") == ("openai", "gpt-model")
    assert engine.effective_routing(routed.roles[RoleName.PO], RoleName.PO) == (
        "openai",
        "gpt-model",
    )
    # other roles are untouched
    assert engine.effective_routing(routed.roles[RoleName.QA], RoleName.QA)[0] == "deepseek"

    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL, job.history[-1].detail
    assert [r["model"] for r in vendors["openai"].requests] == ["gpt-model"]
    assert vendors["deepseek"].requests == []
    # the call log records the model that answered, not the profile's name
    assert job.data.invocation_log[-1]["model"] == "gpt-model"

    # the assigned provider stops working (key revoked): the job fails with the reason
    engine.update_provider_settings("openai", clear_key=True)
    broken = engine.start(engine.create_job("y", repo).id)
    assert broken.state is JobState.FAILED
    assert "provider_unavailable" in (broken.history[-1].note or "")
    assert "OpenAI" in (broken.history[-1].detail or "")

    # cleared: back to the profile's own provider
    engine.assign_agent(RoleName.PO, None, None)
    assert engine.agent_routing("po") is None
    again = engine.start(engine.create_job("z", repo).id)
    assert again.state is JobState.AWAITING_BACKLOG_APPROVAL, again.history[-1].detail
    assert len(vendors["deepseek"].requests) == 1


def test_agent_routing_endpoint(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    for spec in PROVIDERS.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    engine.store.create_user("ada", "pw")
    engine.store.create_user("bob", "pw")
    engine.update_provider_settings("deepseek", api_key="sk-d", make_default=True)
    with TestClient(create_app(engine, resume_on_startup=False)) as c:
        c.post("/api/auth/login", json={"username": "bob", "password": "pw"})
        body = {"provider": "deepseek", "model": "deep-model"}
        assert c.put("/api/agents/qa/routing", json=body).status_code == 403
        c.post("/api/auth/login", json={"username": "ada", "password": "pw"})
        # a provider without a key is a 400 with the same note the job would fail with
        resp = c.put("/api/agents/qa/routing", json={"provider": "openai", "model": "gpt"})
        assert resp.status_code == 400 and "no API key for OpenAI" in resp.json()["detail"]
        resp = c.put("/api/agents/qa/routing", json={"provider": "deepseek", "model": ""})
        assert resp.status_code == 400 and "pick a model" in resp.json()["detail"]
        assert c.put("/api/agents/nope/routing", json=body).status_code == 422

        resp = c.put("/api/agents/qa/routing", json=body)
        assert resp.status_code == 200, resp.text
        card = resp.json()
        assert card["role"] == "qa"
        assert (card["assigned_provider"], card["assigned_model"]) == ("deepseek", "deep-model")
        assert (card["effective_provider"], card["effective_model"]) == ("deepseek", "deep-model")
        agents = {a["role"]: a for a in c.get("/api/agents").json()}
        assert agents["qa"]["assigned_model"] == "deep-model"
        assert agents["po"]["assigned_model"] is None

        resp = c.put("/api/agents/qa/routing", json={"provider": None, "model": None})
        assert resp.status_code == 200 and resp.json()["assigned_model"] is None


def test_every_provider_is_reachable_with_its_own_client(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each vendor in the registry can be configured, tested and assigned to an agent:
    Anthropic has its own client, the rest speak the OpenAI protocol on their own host."""
    for spec in PROVIDERS.values():
        monkeypatch.delenv(spec.env_var, raising=False)
    vendors = {name: FakeVendor(f"sk-{name}", [f"{name}-model"]) for name in PROVIDERS}

    def route(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        name = next(n for n, s in PROVIDERS.items() if httpx.URL(s.default_base_url).host == host)
        return vendors[name].handler(request)

    engine.http_transport = httpx.MockTransport(route)
    for name, spec in PROVIDERS.items():
        resp = client.put(f"/api/settings/providers/{name}", json={"api_key": f"sk-{name}"})
        assert resp.status_code == 200, (name, resp.text)
        row = next(r for r in resp.json() if r["name"] == name)
        assert row["key_set"] and row["default_base_url"] == spec.default_base_url
        assert client.post(f"/api/settings/providers/{name}/test").json()["models"] == [
            f"{name}-model"
        ]
        assert (
            client.put(
                "/api/agents/backend/routing", json={"provider": name, "model": f"{name}-model"}
            ).json()["effective_provider"]
            == name
        )
    assert client.put("/api/agents/backend/routing", json={}).status_code == 200
