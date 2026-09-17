"""Analyst: looks at the worktree and proposes the project profile.

The Analyst decides how the project is built, tested and run. It does not choose models:
the ``roles`` map always comes from the seed profile the job was started with, so model
routing stays a human decision (invariant 1).
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, require_worktree, scan_worktree
from slipwright.roles.results import AnalystResult
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Inspect the project files below and produce its Slipwright profile: the language, the
package manager, and the exact shell commands to build, test and run it. `run_cmd` must
start the project listening on the port given by the literal placeholder `{port}`.
Keep the `roles` map exactly as given in `seed_profile`. If `feedback` is present, a human
rejected your previous profile; address every point in it."""


def run(
    job: Job,
    *,
    seed: Profile,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
) -> RoleResult:
    worktree = require_worktree(job)
    context = base_context(job, instructions=INSTRUCTIONS, feedback=job.data.feedback, jira=jira)
    context["seed_profile"] = seed.model_dump(mode="json")
    context["previous_profile"] = (
        None if job.profile is None else job.profile.model_dump(mode="json")
    )
    context["worktree"] = scan_worktree(worktree)

    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.ANALYST, seed, context, provider=provider, **kwargs)


def accepted_profile(result: AnalystResult, seed: Profile) -> Profile:
    """The profile the job will carry: the Analyst's project facts, the seed's roles."""
    return result.profile.model_copy(update={"roles": seed.roles})


__all__ = ["INSTRUCTIONS", "accepted_profile", "run"]
