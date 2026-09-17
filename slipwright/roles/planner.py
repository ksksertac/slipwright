"""Planner: turns the request into an ordered list of phases the Developer executes."""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, require_worktree, scan_worktree
from slipwright.roles.specialists import Domain
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Plan how to implement the request in this project. Split the work into small, ordered
phases; each phase must have one clear goal and list the files it will create or change.
A later phase may depend on an earlier one, never the reverse. Keep the plan as short as
the request allows.
Tag every phase with a `domain`: `backend` (services, APIs, data), `web` (web front-end),
`mobile` (mobile app), `infra` (CI, deployment, infrastructure), `docs`, or `general`
when none fits. Each phase is implemented by the specialist agent for its domain, so a
phase must not mix domains: split "add an endpoint and show it on the page" into a
backend phase and a web phase, backend first.
Also return a `breakdown`: the same work organised as epics, each with user stories, each
with tasks. Every task names exactly one phase by its 1-based number in `phase`, and
every phase must be covered by exactly one task. Use one epic per independent outcome
of the request, one story per user-visible capability, and one task per phase.
If `feedback` is present, a human rejected your previous plan (`previous_plan`); address
every point in it. If a `jira` section is present you may add sub-tasks you discover
through `jira_actions`; the breakdown itself is mirrored to Jira by the engine."""


def run(
    job: Job,
    profile: Profile,
    *,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    context = base_context(
        job, instructions=INSTRUCTIONS, feedback=job.data.feedback, jira=jira, standards=standards
    )
    context["project"] = _project_facts(profile)
    context["domains"] = [d.value for d in Domain]
    context["previous_plan"] = job.data.plan
    context["worktree"] = scan_worktree(require_worktree(job))
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.PLANNER, profile, context, provider=provider, **kwargs)


def _project_facts(profile: Profile) -> dict[str, str | int]:
    return {
        "language": profile.language,
        "package_manager": profile.package_manager,
        "build_cmd": profile.build_cmd,
        "test_cmd": profile.test_cmd,
        "run_cmd": profile.run_cmd,
        "port": profile.port,
    }


__all__ = ["INSTRUCTIONS", "run"]
