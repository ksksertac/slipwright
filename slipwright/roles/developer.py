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
    plan_outline,
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
realistic estimate) describing what you changed.
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""

REVIEW_FIX = """
If `standards_review` is present, your previous change for this phase passed the build
but the standards review found the listed `violations` (each names the section, the file
and a fix); the phase already committed, so return only the files that change to resolve
every violation, and set `phase_complete` to true."""

IN_PARTS = """
Work in parts. If `output_was_truncated` is present, your previous answer was cut off at
the output limit and was thrown away: return only the most important files now (a few
files, complete contents) and set `phase_complete` to false — you will be called again
for the rest. If `continuation` is present, the files listed in `files_so_far` are
already written from your earlier parts (do not repeat them unless they must change);
continue with the next files and set `phase_complete` to true only when the phase's goal
is fully met."""

FIX_INSTRUCTIONS = """\
The change set on this branch is complete but `ci_failure` shows the continuous
integration run failed. Read the log, fix the cause, and return the corrected files
(complete contents; paths relative to the project root). Set `phase_complete` to true.
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""


def run(
    job: Job,
    profile: Profile,
    *,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    ci_failure: str | None = None,
    jira: dict[str, Any] | None = None,
    as_role: RoleName = RoleName.BACKEND,
    standards: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    truncated: str | None = None,
    continuation: dict[str, Any] | None = None,
) -> RoleResult:
    """Run the generic developer or, with ``role``, one of the specialists."""
    from slipwright.roles.specialists import INSTRUCTIONS as SPECIALIST_INSTRUCTIONS

    plan = job.data.plan or {}
    phases: list[dict[str, Any]] = plan.get("phases", [])
    worktree = require_worktree(job)
    instructions = SPECIALIST_INSTRUCTIONS.get(as_role, INSTRUCTIONS)
    if review:
        instructions += REVIEW_FIX
    if truncated or continuation:
        instructions += IN_PARTS

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
        if review:
            context["standards_review"] = review
        wanted = list(phase.get("files", []))

    context["project"] = project_facts(profile)
    context["plan"] = plan_outline(plan)
    if truncated:
        context["output_was_truncated"] = truncated
    if continuation:
        context["continuation"] = continuation
    context["tree"] = list_tree(worktree)
    context["files"] = read_files(worktree, wanted)

    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(as_role, profile, context, provider=provider, **kwargs)


__all__ = ["FIX_INSTRUCTIONS", "INSTRUCTIONS", "run"]
