"""DevOps: writes the pull request from the plan and the job's phase history.

Everything mechanical (push, open PR, poll CI, hand failures to the Developer) is the
engine's job. The DevOps model turns the deterministic draft below into a PR title and
body a reviewer would want to read.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Write the pull request for this branch. `draft` is a factual description assembled from
the approved plan and the job history; `branch_diff` is what changed. Produce a concise
`pr_title` (imperative, under 70 characters) and a `pr_body` in Markdown that explains
what changed and why, lists the phases, and mentions how it was tested. Do not invent
anything that is not in the draft or the diff. If a `jira` section is present, comment
the outcome on the stories listed there (the PR link is added by the engine)."""


def run(
    job: Job,
    profile: Profile,
    *,
    branch_diff: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    context = base_context(job, instructions=INSTRUCTIONS, jira=jira, standards=standards)
    context["draft"] = draft_description(job)
    context["branch_diff"] = branch_diff
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.DEVOPS, profile, context, provider=provider, **kwargs)


def draft_description(job: Job) -> str:
    """Deterministic PR description: request, plan phases, test cases, phase history."""
    lines = ["## Request", "", job.request, ""]
    plan = job.data.plan or {}
    phases = plan.get("phases", [])
    if phases:
        lines += ["## Plan", ""]
        if plan.get("summary"):
            lines += [str(plan["summary"]), ""]
        for i, phase in enumerate(phases, 1):
            files = ", ".join(f"`{f}`" for f in phase.get("files", []))
            lines.append(f"{i}. {phase.get('goal', '')}" + (f" — {files}" if files else ""))
        lines.append("")
    if job.data.test_cases:
        lines += ["## Test cases", ""]
        lines += [f"- **{c.get('name')}**: {c.get('description')}" for c in job.data.test_cases]
        lines.append("")
    steps = [
        t
        for t in job.history
        if t.to_state in (JobState.BUILD_GATE, JobState.DEVELOPING, JobState.QA) and t.note
    ]
    if steps:
        lines += ["## History", ""]
        lines += [f"- {t.at:%Y-%m-%d %H:%M} — {t.note}" for t in steps]
        lines.append("")
    lines.append(f"_Opened by Slipwright job `{job.id}`._")
    return "\n".join(lines)


__all__ = ["INSTRUCTIONS", "draft_description", "run"]
