"""Software Architect: from the approved backlog and the repository, decide how.

Produces three things in one go: the project profile (how it is built, tested and run),
architecture decisions worth writing down, and the ordered, domain-tagged phases — one
per backlog task — that the specialists will implement. Model routing (``roles``) always
comes from the seed profile; the Architect never chooses models (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, require_worktree, scan_worktree
from slipwright.roles.results import ArchitectResult, PlanPhase
from slipwright.roles.specialists import Domain
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
You are the Software Architect. Read the repository (`worktree`) and the approved
`backlog`, then return:
1. `profile` — the project's language, package manager and the exact shell commands to
   build, test and run it. `run_cmd` must start the project listening on the literal
   placeholder `{port}`. Prefer the commands the repository's CI already runs. Keep the
   `roles` map exactly as given in `seed_profile`.
2. `stack` — one entry for each part of the product this project needs (`backend`,
   `web`, `mobile`, `infra`), naming the language and the framework it is written in and
   one sentence of why. For a repository that already holds code, report what is there
   rather than what you would have chosen; propose something new only for a part that
   does not exist yet. Leave out a part the project does not have. The person reads this
   at the approval gate and may change it before anything is written.
3. `decisions` — the architecture decisions this work needs (components touched, data
   model changes, contracts between backend and front-ends, error handling, anything a
   reviewer must know). One sentence each; omit the obvious.
4. `phases` — ordered implementation phases. Every phase implements exactly one backlog
   task (`task_id`), names its `domain` (`backend`, `web`, `mobile`, `infra`, `docs`,
   `general`) so the right specialist gets it, and lists the files it will create or
   change. Backend contracts come before the front-ends that use them. A phase must not
   mix domains; if a task needs two domains, say so in `summary` so the Product Owner can
   split it.
If `feedback` is present, a human rejected your previous plan (`previous_plan`); address
every point in it. If a `jira` section is present you may add Jira actions for existing
issues. If a `standards` section is present its sections are binding unless they
contradict the core rules."""


def run(
    job: Job,
    *,
    seed: Profile,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    worktree = require_worktree(job)
    context = base_context(
        job, instructions=INSTRUCTIONS, feedback=job.data.feedback, jira=jira, standards=standards
    )
    context["seed_profile"] = seed.model_dump(mode="json")
    context["backlog"] = job.data.backlog
    context["domains"] = [d.value for d in Domain]
    context["previous_plan"] = job.data.plan
    context["previous_profile"] = (
        None if job.profile is None else job.profile.model_dump(mode="json")
    )
    context["worktree"] = scan_worktree(worktree)
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.ARCHITECT, seed, context, provider=provider, **kwargs)


def accepted_profile(result: ArchitectResult, seed: Profile) -> Profile:
    """The profile the job will carry: the Architect's project facts, the seed's roles."""
    return result.profile.model_copy(update={"roles": seed.roles})


def phase_task_map(phases: Sequence[PlanPhase], task_ids: list[str]) -> dict[str, int] | str:
    """Map task id -> 1-based phase number, or a readable reason the plan is invalid."""
    mapping: dict[str, int] = {}
    known = set(task_ids)
    for number, phase in enumerate(phases, start=1):
        if phase.task_id not in known:
            return f"phase {number} names unknown task {phase.task_id!r}"
        if phase.task_id in mapping:
            first = mapping[phase.task_id]
            return f"task {phase.task_id!r} has more than one phase ({first}, {number})"
        mapping[phase.task_id] = number
    missing = [t for t in task_ids if t not in mapping]
    if missing:
        return f"no phase implements task(s) {missing}"
    return mapping


__all__ = ["INSTRUCTIONS", "accepted_profile", "phase_task_map", "run"]
