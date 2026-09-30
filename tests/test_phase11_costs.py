"""T11 — what a development cost, what it was expected to cost, and the gap.

The numbers come from what is already stored, so these tests pin the three ways that can
go wrong quietly: a call with no price counted as free, an estimate invented where there
is no history to base it on, and a variance reported against such an estimate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from slipwright import prices
from slipwright.api import create_app
from slipwright.costs import job_cost, per_call_average, planned_calls, project_costs
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, set_plan

TABLE: dict[str, Any] = {
    "priced-model": {
        "litellm_provider": "anthropic",
        "input_cost_per_token": 5e-06,
        "output_cost_per_token": 2.5e-05,
    }
}


def _transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda _r: httpx.Response(200, content=json.dumps(TABLE)))


def _priced(seed: Profile, *roles: RoleName) -> Profile:
    """The seed with the named roles pointed at a model the test has a price for."""
    return seed.model_copy(
        update={
            "roles": {
                **seed.roles,
                **{
                    r: seed.roles[r].model_copy(
                        update={"provider": "anthropic", "model": "priced-model"}
                    )
                    for r in roles
                },
            }
        }
    )


def _engine(store: JobStore, worktrees_root: Path, seed: Profile, domains: list[str]) -> Engine:
    provider = full_provider(seed, phases=len(domains))
    set_plan(
        provider,
        seed,
        [{"goal": f"step {i + 1}", "files": ["OK"], "domain": d} for i, d in enumerate(domains)],
    )
    engine = full_engine(store, worktrees_root, seed, provider)
    engine.http_transport = _transport()
    engine.refresh_prices()
    return engine


def test_planned_calls_follow_the_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed, ["backend", "web"])
    job = engine.create_job("health", repo)

    # before a plan there is nothing to count but the two planning roles
    assert planned_calls(job) == {RoleName.PO: 1, RoleName.ARCHITECT: 1}

    job = engine.approve(engine.approve(engine.start(job.id).id).id)
    counts = planned_calls(job)
    assert counts[RoleName.BACKEND] == 1 and counts[RoleName.WEB_UI] == 1
    assert counts[RoleName.DESIGNER] == 1  # the plan has a screen in it
    assert counts[RoleName.QA] == 2 and counts[RoleName.DEVOPS] == 1


def test_a_backend_only_plan_expects_no_designer(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed, ["backend"])
    job = engine.approve(engine.approve(engine.start(engine.create_job("health", repo).id).id).id)
    assert RoleName.DESIGNER not in planned_calls(job)


def _spent(job: Any, log: list[dict[str, Any]]) -> Any:
    """Put a per-call log on a job the way the engine would have. The scripted provider
    reports no tokens, so a driven job costs a true zero — useless for testing the sums."""
    job.data.invocation_log = log
    job.data.cost_usd = round(sum(e["cost_usd"] or 0 for e in log), 6)
    return job


def test_spend_is_grouped_and_unpriced_calls_are_not_counted_as_free(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """ "Cost nothing" and "we do not know" are different answers and must stay apart."""
    engine = _engine(store, worktrees_root, seed, ["backend"])
    job = _spent(
        engine.create_job("health", repo),
        [
            {
                "role": "po",
                "model": "a",
                "phase": None,
                "state": "backlog",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cost_usd": 0.0075,
                "ok": True,
            },
            {
                "role": "backend",
                "model": "b",
                "phase": 1,
                "state": "developing",
                "input_tokens": 2000,
                "output_tokens": 500,
                "cost_usd": 0.02,
                "ok": True,
            },
            {
                "role": "backend",
                "model": "b",
                "phase": 1,
                "state": "developing",
                "input_tokens": 500,
                "output_tokens": 50,
                "cost_usd": None,
                "ok": True,
            },
        ],
    )

    cost = job_cost(job, profile=seed)
    assert cost.calls == 3 and cost.unpriced_calls == 1
    assert cost.spent_usd == 0.0275  # the unpriced call added nothing, and is not a zero
    by_role = {r.key: r for r in cost.by_role}
    assert by_role["backend"].calls == 2 and by_role["backend"].unpriced_calls == 1
    assert by_role["backend"].usd == 0.02 and by_role["po"].usd == 0.0075
    assert round(sum(r.usd for r in cost.by_role), 6) == cost.spent_usd
    assert sum(r.calls for r in cost.by_model) == cost.calls
    by_phase = {r.key: r for r in cost.by_phase}
    # a call inside a phase is grouped by it; one outside falls back to its state
    assert by_phase["phase 1"].calls == 2 and by_phase["backlog"].calls == 1


def test_a_call_left_unpriced_is_priced_again_once_the_table_carries_its_model(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The price table is fetched daily, so a model released today is written down
    unpriced — and the refresh that adds it tomorrow cannot go back and mend the entry.
    The log keeps the vendor, the model and both token counts, so the page prices it on
    the way out instead. What was charged at the time still wins where it was recorded."""
    engine = _engine(store, worktrees_root, seed, ["backend"])
    lookup = prices.index(engine.store.list_prices())
    job = _spent(
        engine.create_job("health", repo),
        [
            {  # priced when it was made: that figure is what was charged, and it stands
                "role": "po",
                "provider": "anthropic",
                "model": "priced-model",
                "phase": None,
                "state": "backlog",
                "input_tokens": 1000,
                "output_tokens": 0,
                "cost_usd": 0.004,
                "ok": True,
            },
            {  # made before the table carried the model: no figure, but the tokens are there
                "role": "backend",
                "provider": "anthropic",
                "model": "priced-model",
                "phase": 1,
                "state": "developing",
                "input_tokens": 1_000_000,
                "output_tokens": 100_000,
                "cost_usd": None,
                "ok": True,
            },
            {  # a model nothing knows the price of: unpriced is the honest answer
                "role": "backend",
                "provider": "anthropic",
                "model": "never-heard-of-it",
                "phase": 1,
                "state": "developing",
                "input_tokens": 1000,
                "output_tokens": 100,
                "cost_usd": None,
                "ok": True,
            },
        ],
    )

    cost = job_cost(job, profile=seed, lookup=lookup)
    assert cost.calls == 3
    assert cost.unpriced_calls == 1  # only the model the table still does not carry
    # $5 per million in, $25 per million out: the call written down unpriced is $7.50
    assert cost.spent_usd == 7.504
    by_role = {r.key: r for r in cost.by_role}
    assert by_role["backend"].usd == 7.5 and by_role["backend"].unpriced_calls == 1
    # the stored figure is never recomputed: today's table would make this call $0.005
    assert by_role["po"].usd == 0.004
    assert round(sum(r.usd for r in cost.by_role), 6) == cost.spent_usd
    assert round(sum(r.usd for r in cost.by_phase), 6) == cost.spent_usd


def test_without_a_price_table_nothing_is_invented(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Re-pricing reads the table; with no table the call stays unpriced, not zero."""
    engine = _engine(store, worktrees_root, seed, ["backend"])
    job = _spent(
        engine.create_job("health", repo),
        [
            {
                "role": "backend",
                "provider": "anthropic",
                "model": "priced-model",
                "phase": 1,
                "state": "developing",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cost_usd": None,
                "ok": True,
            }
        ],
    )

    cost = job_cost(job, profile=seed, lookup={})
    assert cost.unpriced_calls == 1 and cost.spent_usd == 0.0


def test_an_estimate_without_history_is_reported_as_absent(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """A number invented from nothing would later read as a measurement. It is None."""
    engine = _engine(store, worktrees_root, seed, ["backend"])
    job = engine.create_job("health", repo)

    cost = job_cost(job, profile=seed, averages={}, lookup={})
    assert cost.expected_usd is None
    assert cost.variance_usd is None  # no basis, so no miss
    assert all(e.usd is None and e.basis_calls == 0 for e in cost.expectations)


def test_history_turns_into_an_estimate_and_a_variance(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    priced = _priced(seed, RoleName.PO, RoleName.ARCHITECT)
    engine = _engine(store, worktrees_root, priced, ["backend"])
    past = _spent(
        engine.create_job("one", repo),
        [
            {
                "role": "po",
                "model": "priced-model",
                "phase": None,
                "state": "backlog",
                "input_tokens": 1_000_000,
                "output_tokens": 0,
                "cost_usd": 5.0,
                "ok": True,
            }
        ],
    )

    averages = per_call_average([past])
    assert averages["po"] == (1_000_000.0, 0.0, 1)  # one real call is the whole basis
    lookup = prices.index(engine.store.list_prices())
    fresh = engine.create_job("two", repo)

    cost = job_cost(fresh, profile=priced, averages=averages, lookup=lookup)
    po = next(e for e in cost.expectations if e.role is RoleName.PO)
    assert po.model == "priced-model" and po.calls == 1
    assert po.usd == 5.0 and po.basis_calls == 1  # a million input tokens at $5/1M
    assert cost.expected_usd == 5.0  # the architect is on the same model with no history
    assert cost.variance_usd == cost.spent_usd - 5.0  # nothing spent yet, so -5


def test_a_refused_call_does_not_drag_the_average_down(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed, ["backend"])
    job = engine.start(engine.create_job("health", repo).id)
    job.data.invocation_log.append(
        {"role": "po", "model": "m", "ok": False, "input_tokens": 0, "output_tokens": 0}
    )

    averages = per_call_average([job])
    real = [e for e in job.data.invocation_log if e["role"] == "po" and e.get("ok")]
    assert averages["po"][2] == len(real)  # the failed call is not part of the basis


def test_the_endpoint_serves_the_project(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed, ["backend"])
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    engine.store.save(
        _spent(
            job,
            [
                {
                    "role": "po",
                    "model": "priced-model",
                    "phase": None,
                    "state": "backlog",
                    "input_tokens": 200_000,
                    "output_tokens": 0,
                    "cost_usd": 1.0,
                    "ok": True,
                }
            ],
        )
    )

    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        body = client.get(f"/api/projects/{project.id}/costs").json()

    assert len(body["jobs"]) == 1
    row = body["jobs"][0]
    assert row["spent_usd"] == 1.0 and row["calls"] == 1
    assert body["spent_usd"] == row["spent_usd"]
    assert body["priced_models"] == 1
    assert {s["key"] for s in row["by_role"]} <= {r.value for r in RoleName}


def test_an_empty_project_costs_nothing_without_claiming_an_estimate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    costs = project_costs("p", [], stored_prices=[])
    assert costs.spent_usd == 0.0 and costs.expected_usd is None and costs.jobs == []


def test_the_estimate_prices_the_model_that_will_answer(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """A profile can carry one vendor's model names while the installation runs another:
    a role with no provider of its own follows the default provider and that provider's
    model, and the name in the profile is never asked for. Quoting the named model would
    put a price on the table that nobody is going to pay."""
    engine = _engine(store, worktrees_root, seed, ["backend"])
    named = _priced(seed, RoleName.PO)  # the profile says anthropic/priced-model
    job = engine.create_job("health", repo)
    averages = {"po": (1_000_000.0, 0.0, 3)}
    lookup = prices.index(engine.store.list_prices())

    # nothing overrides it: the profile's own provider and model are used
    own = job_cost(job, profile=named, averages=averages, lookup=lookup)
    assert next(e for e in own.expectations if e.role is RoleName.PO).model == "priced-model"

    # the installation routes elsewhere, so that is what the estimate must price
    def elsewhere(_cfg: Any, _role: Any) -> tuple[str, str]:
        return "deepseek", "some-other-model"

    routed = job_cost(job, profile=named, averages=averages, lookup=lookup, route=elsewhere)
    po = next(e for e in routed.expectations if e.role is RoleName.PO)
    assert po.model == "some-other-model"
    assert po.usd is None  # that model has no stored price, so no number is invented


def test_a_failed_call_is_recorded_against_the_model_it_was_headed_for(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """A profile can name one vendor's model while the installation routes to another.
    A call that fails has no response to read the routed model off, and recording the
    profile's name put failures — and any spend beside them — against a model that was
    never asked for. The cost report then listed vendors nobody had called."""
    from slipwright.invoke import InvokeErrorKind, invoke_role
    from slipwright.providers import ModelRequest, ModelResponse, ProviderError

    class Routed:
        """A provider that routes everything elsewhere, and then fails."""

        def route(self, _role: str, _provider: str | None, _model: str) -> tuple[str, str]:
            return "deepseek", "deepseek-flash"

        def complete(self, _request: ModelRequest) -> ModelResponse:
            raise ProviderError("the vendor is down")

    named = _priced(seed, RoleName.PO)  # the profile says anthropic/priced-model
    result = invoke_role(
        RoleName.PO, named, {"instructions": "x", "request": "y"}, provider=Routed()
    )

    assert not result.ok and result.error is not None
    assert result.error.kind is InvokeErrorKind.PROVIDER_ERROR
    assert (result.provider, result.model) == ("deepseek", "deepseek-flash")


def test_a_call_counts_every_attempt_it_paid_for(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """One role call can be several calls to the vendor, and every one of them is billed.

    An answer cut off at the output limit was generated in full and charged in full, and
    asking for a smaller part sends the whole prompt again. The log kept only the attempt
    that finally worked, so a phase that took four tries was written down as one, and the
    cost panel showed a figure well under the money. What is recorded now is the call:
    every attempt it took, added up."""
    from slipwright.providers import ProviderTruncatedError

    provider = full_provider(seed, phases=1)
    answer = provider.replies[RoleName.BACKEND]
    attempts = {"n": 0}

    def cut_off_once(_req: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ProviderTruncatedError(
                "response truncated at max_tokens=8192", input_tokens=1200, output_tokens=8192
            )
        return answer

    provider.replies[RoleName.BACKEND] = cut_off_once
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.approve(engine.approve(engine.start(engine.create_job("x", repo).id).id).id)

    backend = [e for e in job.data.invocation_log if e["role"] == "backend"]
    assert backend and backend[0]["attempts"] == 2
    # the scripted answer that worked reports no tokens, so what is left in the entry is
    # exactly the attempt that was cut off -- the one that used to vanish
    assert backend[0]["input_tokens"] == 1200
    assert backend[0]["output_tokens"] == 8192


def test_a_subscription_call_costs_nothing_rather_than_an_unknown_amount() -> None:
    """A ChatGPT plan is a flat monthly fee, so there is no price to look up.

    Counting those calls as "unpriced" put a line on the costs page telling somebody that
    calls had run on a model with no stored price — which reads as a gap to go and fill,
    and there is nothing to fill it with.
    """
    from slipwright.costs import job_cost
    from slipwright.schemas.job import Job, JobState

    job = Job(request="x", repo_path=Path("."))
    job.state = JobState.DONE
    job.data.invocation_log = [
        {"role": "po", "provider": "chatgpt", "model": "default",
         "input_tokens": 900, "output_tokens": 300},
        {"role": "qa", "provider": "deepseek", "model": "never-priced",
         "input_tokens": 500, "output_tokens": 100},
    ]

    costs = job_cost(job, profile=None, averages={}, lookup={})
    assert costs.spent_usd == 0.0
    assert costs.subscription_calls == 1, "the plan paid for it; nought is the answer"
    assert costs.unpriced_calls == 1, "and the other one is genuinely unknown"

    by_role = {row.key: row for row in costs.by_role}
    assert by_role["po"].subscription_calls == 1 and by_role["po"].unpriced_calls == 0
    assert by_role["qa"].unpriced_calls == 1 and by_role["qa"].subscription_calls == 0


def test_a_call_given_up_on_is_counted_even_though_nobody_says_what_it_cost(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """A timeout is the one failure that leaves money behind and no record of it.

    The model was writing when we stopped waiting: those tokens exist and the vendor
    charges for them, but a call that never finished answering returns no usage block, so
    nothing arrives to add up. Every other failure reports what it burned and is already
    counted. This one read as though those minutes had been free -- which is what "it
    feels like it is eating tokens in the background" is describing.
    """
    from slipwright.providers import ProviderTimeoutError

    provider = full_provider(seed, phases=1)
    answer = provider.replies[RoleName.BACKEND]
    attempts = {"n": 0}

    def time_out_once(_req: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ProviderTimeoutError("read timed out")  # no tokens: none will ever come
        return answer

    provider.replies[RoleName.BACKEND] = time_out_once
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.approve(engine.approve(engine.start(engine.create_job("x", repo).id).id).id)

    backend = [e for e in job.data.invocation_log if e["role"] == "backend"]
    assert backend and backend[0]["attempts"] == 2
    assert backend[0]["unreported_attempts"] == 1

    costs = job_cost(job, profile=seed)
    assert costs.timed_out_calls == 1
    # and it stays out of the money, because the amount is unknown rather than nought
    by_role = {r.key: r for r in costs.by_role}
    assert by_role["backend"].timed_out_calls == 1


def test_one_model_call_gets_long_enough_that_a_timeout_means_something_is_wrong() -> None:
    """Ten minutes was the expensive choice.

    A call still running at ten minutes is not hung, it is writing, and the vendor bills
    those tokens whether the answer is read or thrown away. Giving up paid in full for
    nothing and then sent the whole prompt again -- a Mobile Developer asked for
    thirty-one files hit it twice and produced neither answer. The budget is now long
    enough that reaching it really does mean something is wrong.
    """
    from slipwright.config import Settings, build_engine
    from slipwright.invoke import DEFAULT_TIMEOUT_S

    assert DEFAULT_TIMEOUT_S >= 1800

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = {"SLIPWRIGHT_STATE_DIR": tmp}
        assert Settings.from_env(base).model_timeout_s is None
        eng = build_engine(Settings.from_env(base))
        assert eng.timeout_s == DEFAULT_TIMEOUT_S
        eng.store.close()

        # and an installation whose vendor is slower, or whose phases are larger, says so
        slower = Settings.from_env({**base, "SLIPWRIGHT_MODEL_TIMEOUT_S": "3600"})
        assert slower.model_timeout_s == 3600.0
        eng = build_engine(slower)
        assert eng.timeout_s == 3600.0
        eng.store.close()


def test_the_architect_is_told_a_phase_has_to_fit_in_one_answer() -> None:
    """The other half of the same bill. A phase is written by one model call, so a phase
    naming thirty-one files does not come back slowly -- it does not come back, and every
    attempt at it is charged for. Splitting is the Product Owner's job, and the Architect
    is the one who can see that it is needed."""
    from slipwright.roles.architect import INSTRUCTIONS

    assert "one model call" in INSTRUCTIONS
    assert "handful of files" in INSTRUCTIONS
