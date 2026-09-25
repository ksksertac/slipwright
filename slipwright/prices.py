"""What the models cost, fetched once a day.

No vendor publishes a pricing API: Anthropic's ``GET /v1/models`` returns the id, the
display name, the context window and the capabilities, and OpenAI's, DeepSeek's and
Gemini's model endpoints are the same — names and limits, no money. So the figures come
from a public table that is maintained for exactly this purpose (LiteLLM's
``model_prices_and_context_window.json``), refreshed daily, and a person can override any
line by hand in Settings → Models when their own rates differ.

The other half of the job is naming. That table keys some models bare and others behind
the provider that routes them (``<provider>/<id>``); Slipwright stores whatever the
vendor's own ``/models`` endpoint returned, which may carry a prefix of its own or none
at all. ``resolve`` is that lookup, and it is deliberately forgiving: a miss costs an
unpriced call, not a wrong number. No model is named anywhere in this module -- the table
is the only place model names live.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

SOURCE_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
PER_MILLION = 1_000_000

# Slipwright's provider names -> the ones the price table uses in `litellm_provider`.
# `openrouter` is deliberately absent: Slipwright calls the vendors directly, so an
# OpenRouter row carries someone else's margin and is not what this installation pays.
_PROVIDER_ALIASES: dict[str, tuple[str, ...]] = {
    "anthropic": ("anthropic",),
    "openai": ("openai", "text-completion-openai"),
    "deepseek": ("deepseek",),
    "gemini": ("gemini", "vertex_ai-language-models"),
    "qwen": ("dashscope", "qwen_ai_platform", "qwencloud", "vertex_ai-qwen_models"),
    "glm": ("dashscope", "qwen_ai_platform"),
    "minimax": ("minimax", "vertex_ai-minimax_models"),
}


@dataclass(frozen=True)
class Price:
    """Dollars per million tokens."""

    provider: str
    model: str
    input_usd: float
    output_usd: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.input_usd + output_tokens * self.output_usd) / PER_MILLION


class PriceFetchError(RuntimeError):
    """The price table could not be read; the stored prices stay as they are."""


def fetch(
    *, transport: httpx.BaseTransport | None = None, timeout_s: float = 30.0
) -> list[dict[str, Any]]:
    """Read the public table and return the rows Slipwright's providers can use."""
    try:
        with httpx.Client(transport=transport, timeout=timeout_s) as client:
            response = client.get(SOURCE_URL)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
        raise PriceFetchError(f"could not read the price table: {exc}") from exc
    if not isinstance(data, dict):
        raise PriceFetchError("the price table is not an object")
    return list(_rows(data))


def _rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    # one source name can feed more than one of ours (Qwen and GLM are both served
    # through DashScope), so this maps to a list rather than a single provider
    wanted: dict[str, list[str]] = {}
    for name, aliases in _PROVIDER_ALIASES.items():
        for alias in aliases:
            wanted.setdefault(alias, []).append(name)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue  # the file carries a "sample_spec" header row
        providers = wanted.get(str(entry.get("litellm_provider") or ""))
        if not providers:
            continue
        inp, outp = entry.get("input_cost_per_token"), entry.get("output_cost_per_token")
        if not isinstance(inp, int | float) or not isinstance(outp, int | float):
            continue
        model = key.split("/", 1)[1] if "/" in key else key
        for provider in providers:
            if (provider, model) in seen:
                continue
            seen.add((provider, model))
            out.append(
                {
                    "provider": provider,
                    "model": model,
                    "input_usd": float(inp) * PER_MILLION,
                    "output_usd": float(outp) * PER_MILLION,
                }
            )
    return out


def candidates(model: str) -> list[str]:
    """The names one model might be stored under, most exact first. A vendor endpoint may
    answer with a routing prefix (``<prefix>/<id>``) where the price table holds the bare
    id, and a dated snapshot (an id ending in eight digits) is priced like the undated
    alias it is a snapshot of."""
    names = [model]
    if "/" in model:
        names.append(model.rsplit("/", 1)[1])
    bare = names[-1]
    parts = bare.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 8:
        names.append(parts[0])  # a dated snapshot prices as its undated alias
    lowered = [n.lower() for n in names]
    return list(dict.fromkeys([*names, *lowered]))


def resolve(
    lookup: dict[tuple[str, str], dict[str, Any]], provider: str, model: str
) -> Price | None:
    """The price for one call, or ``None`` when the model is not in the table. Never
    guesses a neighbouring model's rate: an unpriced call is reported as unpriced."""
    if not model:
        return None
    for name in candidates(model):
        row = lookup.get((provider, name))
        if row is not None:
            return Price(
                provider=provider,
                model=model,
                input_usd=float(row["input_usd"]),
                output_usd=float(row["output_usd"]),
            )
    return None


def index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Stored rows, keyed for ``resolve``; the lower-cased name is indexed too."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        provider, model = str(row["provider"]), str(row["model"])
        out[(provider, model)] = row
        out.setdefault((provider, model.lower()), row)
    return out


__all__ = [
    "PER_MILLION",
    "SOURCE_URL",
    "Price",
    "PriceFetchError",
    "candidates",
    "fetch",
    "index",
    "resolve",
]
