"""What a development cost, what it was expected to cost, and the gap between them.

Three things, all read from what is already stored — nothing here is estimated twice or
kept in a second place:

*Spent* comes from ``job.data.invocation_log``: one entry per model call, carrying the
role, the model, the vendor and the dollars that call cost. Calls whose model has no
stored price are counted separately and never guessed at, so "cost nothing" and "we do
not know" stay apart.

A call is priced when it is made, but the price table is fetched daily and a model the
table did not carry yet is written down unpriced — and that entry would stay unpriced
for ever, although the refresh that added the model arrived an hour later. Since the log
keeps the vendor, the model and both token counts, the price is applied again here, on
the way out: the figure written at the time always wins, and a call is reported unpriced
only while its model is genuinely unknown. Nothing is guessed either way.

*Expected* is arithmetic over history, not a model's opinion. For each role, what that
role has actually used per call in this installation, multiplied by how many calls the
plan implies. A role nobody has run yet has no basis and says so, rather than inventing a
number that would later look like a measurement.

*Variance* is the difference, and it is only shown where there was a basis to compare
against. An estimate with no history behind it is not a miss.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright import prices
from slipwright.roles.specialists import specialist_for
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleConfig, RoleName

# how a role's request is actually routed: the pin under Agents, else the default
# provider and its default model. A profile can name one vendor's model while the
# installation runs another, and it is the routed one that gets billed.
Router = Callable[[RoleConfig, RoleName], tuple[str, str]]

# calls a role makes for one unit of its work, counted from how the engine drives it
_CALLS_PER_PHASE = 1
_PLANNING_CALLS = 1  # the PO and the Architect are asked once each per development
_QA_CALLS = 2  # the cases, then the tests
_DEVOPS_CALLS = 1  # the pull request write-up


class Spend(BaseModel):
    """What was actually spent, by whatever the caller grouped on."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str = ""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    unpriced_calls: int = Field(
        default=0, description="Calls whose model had no stored price; not in ``usd``."
    )


class Expectation(BaseModel):
    """What one role was expected to cost, and what it is based on."""

    model_config = ConfigDict(extra="forbid")

    role: RoleName
    model: str = ""
    calls: int = 0
    usd: float | None = Field(
        default=None, description="None when there is no history to base it on."
    )
    basis_calls: int = Field(
        default=0, description="How many past calls the per-call average came from."
    )


class JobCost(BaseModel):
    """One development's money: spent, expected, and the gap."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    request: str
    state: JobState
    spent_usd: float = 0.0
    expected_usd: float | None = None
    variance_usd: float | None = Field(
        default=None, description="spent - expected; None without a basis to compare to."
    )
    calls: int = 0
    unpriced_calls: int = 0
    by_role: list[Spend] = Field(default_factory=list)
    by_model: list[Spend] = Field(default_factory=list)
    by_phase: list[Spend] = Field(default_factory=list)
    expectations: list[Expectation] = Field(default_factory=list)


class ProjectCosts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    jobs: list[JobCost]
    spent_usd: float = 0.0
    expected_usd: float | None = None
    unpriced_calls: int = 0
    priced_models: int = Field(default=0, description="Models with a stored price.")


Lookup = dict[tuple[str, str], dict[str, Any]]


def _entries(job: Job) -> list[dict[str, Any]]:
    return [e for e in job.data.invocation_log if isinstance(e, dict)]


def call_cost(entry: dict[str, Any], lookup: Lookup) -> float | None:
    """What one logged call cost, or ``None`` while its model has no price anywhere.

    The figure written when the call was made wins: it is what this installation was
    charged, at the rate of the day. Only when there is none — the model was not in the
    table yet — is the current price applied to the tokens the entry recorded, which is
    the same arithmetic the engine would have done had the table been a day fresher.
    """
    stored = entry.get("cost_usd")
    if stored is not None:
        return float(stored)
    provider, model = str(entry.get("provider") or ""), str(entry.get("model") or "")
    inp, out = entry.get("input_tokens"), entry.get("output_tokens")
    if not provider or not model or inp is None or out is None:
        return None
    price = prices.resolve(lookup, provider, model)
    return None if price is None else round(price.cost(int(inp), int(out)), 6)


def _add(row: Spend, entry: dict[str, Any], lookup: Lookup) -> None:
    row.calls += 1
    row.input_tokens += int(entry.get("input_tokens") or 0)
    row.output_tokens += int(entry.get("output_tokens") or 0)
    cost = call_cost(entry, lookup)
    if cost is None:
        row.unpriced_calls += 1
    else:
        row.usd = round(row.usd + cost, 6)


def _group(entries: list[dict[str, Any]], key: str, lookup: Lookup) -> list[Spend]:
    out: dict[str, Spend] = {}
    for entry in entries:
        name = str(entry.get(key) or "")
        if not name:
            continue
        _add(out.setdefault(name, Spend(key=name, label=name)), entry, lookup)
    return sorted(out.values(), key=lambda r: (-r.usd, r.key))


def _by_phase(entries: list[dict[str, Any]], lookup: Lookup) -> list[Spend]:
    """Phase number -> spend. Calls made outside a phase (planning, QA, DevOps) are
    grouped under the state they were made in, so nothing is silently dropped."""
    out: dict[str, Spend] = {}
    for entry in entries:
        phase = entry.get("phase")
        name = f"phase {phase}" if phase else str(entry.get("state") or "other")
        _add(out.setdefault(name, Spend(key=name, label=name)), entry, lookup)
    return sorted(out.values(), key=lambda r: (-r.usd, r.key))


def per_call_average(jobs: list[Job]) -> dict[str, tuple[float, float, int]]:
    """Per role: the average input and output tokens of one call, and how many calls that
    average came from. Only priced, successful calls count — a refused call that returned
    nothing would drag every estimate towards zero."""
    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for job in jobs:
        for entry in _entries(job):
            if not entry.get("ok"):
                continue
            inp, out = entry.get("input_tokens"), entry.get("output_tokens")
            if inp is None or out is None:
                continue
            row = totals[str(entry.get("role") or "")]
            row[0] += float(inp)
            row[1] += float(out)
            row[2] += 1
    return {
        role: (row[0] / row[2], row[1] / row[2], int(row[2]))
        for role, row in totals.items()
        if row[2]
    }


def planned_calls(job: Job) -> dict[RoleName, int]:
    """How many calls the approved plan implies, per role. Before there is a plan this is
    the planning roles only — which is honest: nothing else has been decided yet."""
    calls: dict[RoleName, int] = {RoleName.PO: _PLANNING_CALLS, RoleName.ARCHITECT: _PLANNING_CALLS}
    plan = job.data.plan or {}
    phases: list[dict[str, Any]] = plan.get("phases") or []
    if not phases:
        return calls
    ui = False
    for phase in phases:
        domain = str(phase.get("domain") or "general")
        role = specialist_for(domain)
        calls[role] = calls.get(role, 0) + _CALLS_PER_PHASE
        ui = ui or domain in ("web", "mobile")
    if ui:
        calls[RoleName.DESIGNER] = calls.get(RoleName.DESIGNER, 0) + 1
    calls[RoleName.QA] = calls.get(RoleName.QA, 0) + _QA_CALLS
    calls[RoleName.DEVOPS] = calls.get(RoleName.DEVOPS, 0) + _DEVOPS_CALLS
    return calls


def expectations(
    job: Job,
    profile: Profile | None,
    averages: dict[str, tuple[float, float, int]],
    lookup: Lookup,
    route: Router | None = None,
) -> list[Expectation]:
    """What each role is expected to cost on this development, at the model it will
    actually run on and the tokens its past calls have used.

    The model named in the profile is not always the one that answers: a role with no
    provider of its own follows the default provider and that provider's default model,
    so a profile carrying one vendor's names on an installation pointed at another would
    have this table quoting a price nobody is going to pay. ``route`` resolves it.
    """
    out: list[Expectation] = []
    for role, count in planned_calls(job).items():
        cfg = profile.roles.get(role) if profile else None
        model = (cfg.model if cfg else "") or ""
        provider = (cfg.provider if cfg else None) or ""
        if cfg is not None and route is not None:
            provider, model = route(cfg, role)
        price = prices.resolve(lookup, provider, model) if provider and model else None
        average = averages.get(role.value)
        usd: float | None = None
        if price is not None and average is not None:
            usd = round(price.cost(int(average[0]), int(average[1])) * count, 6)
        out.append(
            Expectation(
                role=role,
                model=model,
                calls=count,
                usd=usd,
                basis_calls=average[2] if average else 0,
            )
        )
    return sorted(out, key=lambda e: (-(e.usd or 0.0), e.role.value))


def job_cost(
    job: Job,
    *,
    profile: Profile | None = None,
    averages: dict[str, tuple[float, float, int]] | None = None,
    lookup: Lookup | None = None,
    route: Router | None = None,
) -> JobCost:
    index = lookup or {}
    entries = _entries(job)
    costs = [call_cost(e, index) for e in entries]
    unpriced = sum(1 for c in costs if c is None)
    wanted = expectations(job, profile, averages or {}, index, route)
    known = [e.usd for e in wanted if e.usd is not None]
    expected = round(sum(known), 6) if known else None
    # the log is the record; a development from before it was kept still has its total
    if entries:
        spent = round(sum(c for c in costs if c is not None), 6)
    else:
        spent = round(job.data.cost_usd, 6)
    return JobCost(
        job_id=job.id,
        request=job.request,
        state=job.state,
        spent_usd=spent,
        expected_usd=expected,
        # only where there was a basis: an estimate built on nothing is not a miss
        variance_usd=round(spent - expected, 6) if expected is not None else None,
        calls=len(entries),
        unpriced_calls=unpriced,
        by_role=_group(entries, "role", index),
        by_model=_group(entries, "model", index),
        by_phase=_by_phase(entries, index),
        expectations=wanted,
    )


def project_costs(
    project_id: str,
    jobs: list[Job],
    *,
    profile: Profile | None = None,
    stored_prices: list[dict[str, Any]] | None = None,
    history: list[Job] | None = None,
    route: Router | None = None,
) -> ProjectCosts:
    """Every development's money. ``history`` is what the averages are learned from —
    the project's own jobs by default, so an installation's estimates get better as it
    is used rather than staying at a number somebody typed once."""
    lookup = prices.index(stored_prices or [])
    averages = per_call_average(history if history is not None else jobs)
    rows = [
        job_cost(job, profile=job.profile or profile, averages=averages, lookup=lookup, route=route)
        for job in jobs
    ]
    known = [r.expected_usd for r in rows if r.expected_usd is not None]
    return ProjectCosts(
        project_id=project_id,
        jobs=rows,
        spent_usd=round(sum(r.spent_usd for r in rows), 6),
        expected_usd=round(sum(known), 6) if known else None,
        unpriced_calls=sum(r.unpriced_calls for r in rows),
        priced_models=len(stored_prices or []),
    )


__all__ = [
    "Expectation",
    "Lookup",
    "Router",
    "JobCost",
    "ProjectCosts",
    "Spend",
    "call_cost",
    "expectations",
    "job_cost",
    "per_call_average",
    "planned_calls",
    "project_costs",
]
