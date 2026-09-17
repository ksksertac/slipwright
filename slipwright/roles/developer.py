"""Developer: implements exactly one plan phase per invocation.

The Developer sees the whole plan for orientation but is told which phase is its own.
It returns full contents for every file it touches; the engine writes them into the
worktree and records the diff. When a build gate failed, the captured output is passed
back so the next invocation is a fix attempt on the same phase.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import (
    base_context,
    list_tree,
    project_facts,
    read_files,
    require_worktree,
)
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Implement the plan phase named in `current_phase` and nothing beyond it. Return the
complete new contents of every file you create or change (`content: null` deletes a
file); paths are relative to the project root. Keep changes minimal and consistent with
the existing code. Set `phase_complete` to true when the phase's goal is met.
If `build_failure` is present, the build or tests failed after your previous attempt on
this phase: read the output, fix the cause, and return the corrected files.
If a `jira` section is present you are expected to keep the tracker current: transition
`current_task_key` to in progress, and add a short comment on it (and `log_work` with a
realistic estimate) describing what you changed."""

FIX_INSTRUCTIONS = """\
The change set on this branch is complete but `ci_failure` shows the continuous
integration run failed. Read the log, fix the cause, and return the corrected files
(complete contents; paths relative to the project root). Set `phase_complete` to true."""


def run(
    job: Job,
    profile: Profile,
    *,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    ci_failure: str | None = None,
    jira: dict[str, Any] | None = None,
    as_role: RoleName = RoleName.DEVELOPER,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    """Run the generic developer or, with ``role``, one of the specialists."""
    from slipwright.roles.specialists import INSTRUCTIONS as SPECIALIST_INSTRUCTIONS

    plan = job.data.plan or {}
    phases: list[dict[str, Any]] = plan.get("phases", [])
    worktree = require_worktree(job)
    instructions = SPECIALIST_INSTRUCTIONS.get(as_role, INSTRUCTIONS)

    if ci_failure is not None:
        context = base_context(job, instructions=FIX_INSTRUCTIONS, jira=jira, standards=standards)
        context["ci_failure"] = ci_failure
        wanted = sorted({f for phase in phases for f in phase.get("files", [])})
    else:
        index = job.data.phase_index
        phase = phases[index] if index < len(phases) else {}
        context = base_context(job, instructions=instructions, jira=jira, standards=standards)
        context["current_phase"] = {"number": index + 1, "of": len(phases), **phase}
        if job.data.last_build_output:
            context["build_failure"] = job.data.last_build_output
        wanted = list(phase.get("files", []))

    context["project"] = project_facts(profile)
    context["plan"] = plan
    context["tree"] = list_tree(worktree)
    context["files"] = read_files(worktree, wanted)

    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(as_role, profile, context, provider=provider, **kwargs)


__all__ = ["FIX_INSTRUCTIONS", "INSTRUCTIONS", "run"]
