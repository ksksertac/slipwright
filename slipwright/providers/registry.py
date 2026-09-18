"""Known model providers and the router that picks one per request.

A role names its provider in the profile (``roles.<role>.provider``); unset means the
configured default. Credentials come from the settings store (encrypted) or, failing
that, the provider's environment variable. No module here names a model: the settings
page lists models by asking each vendor's ``/models`` endpoint.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict

from slipwright.providers import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderUnavailableError,
)

ANTHROPIC = "anthropic"
OPENAI = "openai"
DEEPSEEK = "deepseek"
DEFAULT_PROVIDER = ANTHROPIC


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    env_var: str
    default_base_url: str
    supports_effort: bool
    max_tokens_param: str
    docs_url: str
    max_tokens: int = 32_000  # the largest answer the vendor accepts in one call


PROVIDERS: dict[str, ProviderSpec] = {
    ANTHROPIC: ProviderSpec(
        name=ANTHROPIC,
        label="Anthropic (Claude)",
        env_var="ANTHROPIC_API_KEY",
        default_base_url="https://api.anthropic.com",
        supports_effort=True,
        max_tokens_param="max_tokens",
        docs_url="https://console.anthropic.com/settings/keys",
    ),
    OPENAI: ProviderSpec(
        name=OPENAI,
        label="OpenAI (ChatGPT)",
        env_var="OPENAI_API_KEY",
        default_base_url="https://api.openai.com/v1",
        supports_effort=True,
        max_tokens_param="max_completion_tokens",
        docs_url="https://platform.openai.com/api-keys",
    ),
    DEEPSEEK: ProviderSpec(
        name=DEEPSEEK,
        label="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        default_base_url="https://api.deepseek.com",
        supports_effort=False,
        max_tokens_param="max_tokens",
        docs_url="https://platform.deepseek.com/api_keys",
        max_tokens=8_192,  # the chat model rejects anything larger
    ),
}


class Credentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    api_key: str
    base_url: str
    max_tokens: int | None = None  # overrides the vendor's default output limit


def provider_names() -> list[str]:
    return list(PROVIDERS)


def build_client(
    creds: Credentials, *, transport: httpx.BaseTransport | None = None
) -> ModelProvider:
    spec = PROVIDERS.get(creds.name)
    if spec is None:
        raise ProviderUnavailableError(f"unknown provider: {creds.name}")
    if creds.name == ANTHROPIC:
        from slipwright.providers.anthropic import AnthropicProvider

        return AnthropicProvider.from_credentials(
            creds.api_key,
            base_url=creds.base_url,
            transport=transport,
            max_tokens=creds.max_tokens or spec.max_tokens,
        )
    from slipwright.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(
        creds.api_key,
        creds.base_url,
        supports_effort=spec.supports_effort,
        max_tokens_param=spec.max_tokens_param,
        max_tokens=creds.max_tokens or spec.max_tokens,
        transport=transport,
    )


def list_models(creds: Credentials, *, transport: httpx.BaseTransport | None = None) -> list[str]:
    """Ask the vendor which models the key can use (also serves as the connection test)."""
    client = build_client(creds, transport=transport)
    models: list[str] = client.list_models()  # type: ignore[attr-defined]
    return models


CredentialsResolver = Callable[[str], Credentials | None]


class RoutingProvider:
    """Dispatches each request to the provider its role names, building clients lazily
    from whatever credentials the resolver returns at that moment (so a key entered in
    the settings page takes effect on the next request, no restart needed)."""

    def __init__(
        self,
        resolve: CredentialsResolver,
        *,
        default: Callable[[], str] | None = None,
        default_model: Callable[[str], str | None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._resolve = resolve
        self._default = default or (lambda: DEFAULT_PROVIDER)
        # the model a "default" role runs on for a given provider (Settings -> Models)
        self._default_model = default_model or (lambda _name: None)
        self._transport = transport
        self._clients: dict[Credentials, ModelProvider] = {}
        self._lock = threading.Lock()

    def client_for(self, name: str | None) -> ModelProvider:
        name = name or self._default()
        if name not in PROVIDERS:
            raise ProviderUnavailableError(f"unknown provider: {name!r}")
        creds = self._resolve(name)
        if creds is None:
            spec = PROVIDERS[name]
            raise ProviderUnavailableError(
                f"no API key for {spec.label}: add one under Settings → Models "
                f"or set {spec.env_var}"
            )
        with self._lock:
            client = self._clients.get(creds)
            if client is None:
                client = build_client(creds, transport=self._transport)
                self._clients[creds] = client
            return client

    def route(self, provider: str | None, model: str) -> tuple[str, str]:
        """Where a role's request goes. A role that names no provider follows the default
        provider *and* that provider's default model when one is configured -- a model
        name from another vendor's profile would only fail there."""
        if provider:
            return provider, model
        name = self._default()
        return name, self._default_model(name) or model

    def complete(self, request: ModelRequest) -> ModelResponse:
        name, model = self.route(request.provider, request.model)
        if (name, model) != (request.provider, request.model):
            request = request.model_copy(update={"provider": name, "model": model})
        try:
            client = self.client_for(name)
        except ProviderError:
            raise
        return client.complete(request)


__all__ = [
    "ANTHROPIC",
    "DEEPSEEK",
    "DEFAULT_PROVIDER",
    "OPENAI",
    "PROVIDERS",
    "Credentials",
    "CredentialsResolver",
    "ProviderSpec",
    "RoutingProvider",
    "build_client",
    "list_models",
    "provider_names",
]
