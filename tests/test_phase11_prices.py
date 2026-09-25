"""T11 — what the models cost: the daily table, and the price of a finished call.

No vendor publishes a pricing API, so the figures come from a published table that is
fetched once a day. These tests pin the two things that can quietly go wrong: the mapping
from that table's names onto the ones a vendor's own ``/models`` endpoint returns, and the
rule that a price a person typed in survives every later fetch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from slipwright import prices
from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

TABLE: dict[str, Any] = {
    "sample_spec": "this row is documentation, not a model",
    "claude-opus-5": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 5e-06,
        "output_cost_per_token": 2.5e-05,
    },
    "claude-haiku-4-5": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 1e-06,
        "output_cost_per_token": 5e-06,
    },
    "gemini/gemini-2.5-flash": {
        "litellm_provider": "gemini",
        "input_cost_per_token": 3e-07,
        "output_cost_per_token": 2.5e-06,
    },
    "dashscope/glm-5.1": {
        "litellm_provider": "dashscope",
        "input_cost_per_token": 6e-07,
        "output_cost_per_token": 2e-06,
    },
    "openrouter/some-reseller-model": {
        "litellm_provider": "openrouter",
        "input_cost_per_token": 9e-06,
        "output_cost_per_token": 9e-05,
    },
    "whisper-1": {"litellm_provider": "openai", "mode": "audio_transcription"},
}


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == prices.SOURCE_URL
        return httpx.Response(200, content=json.dumps(TABLE))

    return httpx.MockTransport(handler)


def test_the_table_is_read_into_the_providers_we_call(store: JobStore) -> None:
    rows = prices.fetch(transport=_transport())
    got = {(r["provider"], r["model"]): (r["input_usd"], r["output_usd"]) for r in rows}

    assert got[("anthropic", "claude-opus-5")] == (5.0, 25.0)  # per million, not per token
    assert got[("gemini", "gemini-2.5-flash")] == (0.3, 2.5)  # the routing prefix is dropped
    # DashScope serves both Qwen and GLM, so one source row feeds two of our providers
    assert ("qwen", "glm-5.1") in got and ("glm", "glm-5.1") in got
    # a reseller's rate is someone else's margin, not what this installation pays
    assert not any(model == "some-reseller-model" for _, model in got)
    # a row with no token price at all (an audio model) is skipped rather than stored as 0
    assert not any(model == "whisper-1" for _, model in got)


def test_a_model_resolves_through_the_name_its_vendor_returns() -> None:
    rows = prices.fetch(transport=_transport())
    index = prices.index(rows)

    exact = prices.resolve(index, "anthropic", "claude-opus-5")
    assert exact is not None and exact.input_usd == 5.0
    # Gemini's own endpoint answers "models/<id>"; the table holds the bare id
    assert prices.resolve(index, "gemini", "models/gemini-2.5-flash") is not None
    # a dated snapshot is priced as the alias it is a snapshot of
    assert prices.resolve(index, "anthropic", "claude-opus-5-20260401") is not None
    # a model nobody priced is reported as unpriced, never as a neighbour's rate
    assert prices.resolve(index, "anthropic", "claude-something-unreleased") is None
    assert prices.resolve(index, "openai", "claude-opus-5") is None  # wrong vendor


def test_cost_is_dollars_per_million_tokens() -> None:
    price = prices.Price(
        provider="anthropic", model="claude-opus-5", input_usd=5.0, output_usd=25.0
    )
    assert price.cost(1_000_000, 0) == pytest.approx(5.0)
    assert price.cost(0, 1_000_000) == pytest.approx(25.0)
    assert price.cost(200_000, 40_000) == pytest.approx(5.0 * 0.2 + 25.0 * 0.04)


def test_a_hand_entered_price_survives_the_daily_fetch(store: JobStore) -> None:
    store.put_price("anthropic", "claude-opus-5", input_usd=3.0, output_usd=12.0, source="manual")
    store.put_prices(prices.fetch(transport=_transport()), source="litellm")

    kept = store.get_price("anthropic", "claude-opus-5")
    assert kept is not None
    assert (kept["input_usd"], kept["source"]) == (3.0, "manual")  # the negotiated rate stands
    fetched = store.get_price("anthropic", "claude-haiku-4-5")
    assert fetched is not None and fetched["source"] == "litellm"

    store.delete_price("anthropic", "claude-opus-5")
    store.put_prices(prices.fetch(transport=_transport()), source="litellm")
    back = store.get_price("anthropic", "claude-opus-5")
    assert back is not None and back["input_usd"] == 5.0  # the published rate returns


def test_the_engine_refreshes_and_prices_a_model(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    engine.http_transport = _transport()

    written = engine.refresh_prices()
    # 2 Anthropic + 1 Gemini + the DashScope row counted once for Qwen and once for GLM;
    # the spec header, the reseller and the audio model are not priced calls we make
    assert written == 5

    price = engine.price_of("anthropic", "claude-opus-5")
    assert price is not None and (price.input_usd, price.output_usd) == (5.0, 25.0)
    assert engine.price_of("anthropic", None) is None
    assert engine.price_of(None, "claude-opus-5") is None
    assert engine.store.get_setting("prices.last_fetch", {})["rows"] == 5


def test_a_failed_fetch_leaves_the_stored_prices_alone(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    engine.http_transport = _transport()
    engine.refresh_prices()

    engine.http_transport = httpx.MockTransport(lambda _r: httpx.Response(503))
    with pytest.raises(prices.PriceFetchError):
        engine.refresh_prices()
    still = engine.price_of("anthropic", "claude-opus-5")
    assert still is not None and still.input_usd == 5.0


def test_the_endpoints_list_refresh_and_override(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    engine.http_transport = _transport()
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        assert client.get("/api/settings/prices").json()["prices"] == []

        body = client.post("/api/settings/prices/refresh").json()
        assert len(body["prices"]) == 5 and body["last_fetch"]

        only = client.get("/api/settings/prices", params={"provider": "anthropic"}).json()
        assert {p["model"] for p in only["prices"]} == {"claude-opus-5", "claude-haiku-4-5"}

        put = client.put(
            "/api/settings/prices/anthropic/claude-opus-5",
            json={"input_usd": 3.0, "output_usd": 12.0},
        )
        assert put.status_code == 200 and put.json()["source"] == "manual"

        assert client.delete("/api/settings/prices/anthropic/claude-opus-5").status_code == 204
        assert engine.store.get_price("anthropic", "claude-opus-5") is None


def test_a_finished_call_records_what_it_cost(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The per-call log is where "what did we burn, and where" comes from, so the price
    has to land on the entry, not only in a total."""
    priced = seed.model_copy(
        update={
            "roles": {
                **seed.roles,
                RoleName.PO: seed.roles[RoleName.PO].model_copy(
                    update={"provider": "anthropic", "model": "claude-opus-5"}
                ),
            }
        }
    )
    engine: Engine = full_engine(store, worktrees_root, priced, full_provider(priced, phases=1))
    engine.http_transport = _transport()
    engine.refresh_prices()

    job = engine.start(engine.create_job("health", repo).id)
    entry = next(e for e in job.data.invocation_log if e["role"] == "po")
    assert entry["provider"] == "anthropic" and entry["model"] == "claude-opus-5"
    expected = prices.Price("anthropic", "claude-opus-5", 5.0, 25.0).cost(
        entry["input_tokens"] or 0, entry["output_tokens"] or 0
    )
    assert entry["cost_usd"] == pytest.approx(expected, abs=1e-6)
    assert job.data.cost_usd == pytest.approx(expected, abs=1e-6)


def test_a_call_on_an_unpriced_model_is_reported_as_unpriced(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Never a guess: a model with no stored price adds nothing to the total, and its
    entry says so, so a report can separate "cost nothing" from "we do not know"."""
    engine: Engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    engine.http_transport = _transport()
    engine.refresh_prices()

    job = engine.start(engine.create_job("health", repo).id)
    entry = next(e for e in job.data.invocation_log if e["role"] == "po")
    assert entry["cost_usd"] is None  # the scripted provider is not a vendor we price
    assert job.data.cost_usd == 0.0
