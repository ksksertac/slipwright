"""The supervisor (T9.8): an agent that reads what the human would read at a gate and
recommends approve or reject.

It never bypasses the state machine. In *assisted* mode its recommendation is shown next
to the gate; in *auto* mode the engine turns a confident, low-risk approval into an
ordinary ``approve`` call recorded as such. Rejections are never automatic.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
You are the supervisor. A development waits at a human gate (`gate`) and you read exactly
what the human would: `material` holds the proposal (a backlog, an architecture with its
profile and phases, a standards review, a list of test cases, or the written tests as a
diff) and `history` the job so far. Decide whether a careful engineering lead would
approve it as is. Return `decision` (approve or reject), `confidence` (0-1: how sure you
are that the decision is right), `risk` (low: routine and reversible; medium: touches
data, auth, money or infrastructure; high: could lose data, expose secrets, break
production or is far larger than the request), `reasons` (short, concrete, at most five)
and, when rejecting, `feedback` the agent can act on. Reject when the proposal drifts
from `request`, breaks a core rule or a retrieved standard, or leaves the request
unfinished. Prefer approve with medium risk over inventing objections.
When `material.failed_build_gate` is present there is no gate to approve: a phase failed
the build and you choose what happens next — `decision` is one of `fix` (the same
specialist tries again with the build output; the usual answer for a test failure or a
typo), `replan` (the failure shows the plan was wrong, e.g. a missing dependency or a
phase far larger than its goal) or `ask_human` (secrets, data loss, or the same failure
repeating). Give the reason in `reasons`."""

GATE_LABELS = {
    JobState.AWAITING_BACKLOG_APPROVAL: "backlog",
    JobState.AWAITING_ARCHITECTURE_APPROVAL: "architecture",
    JobState.AWAITING_REVIEW_APPROVAL: "review",
    JobState.AWAITING_TEST_APPROVAL: "tests",
    JobState.AWAITING_DEPLOY_APPROVAL: "deployment",
}


def gate_name(job: Job) -> str:
    """The gate the job waits at, as the human sees it."""
    if job.state is JobState.AWAITING_TEST_APPROVAL:
        return "test cases" if job.data.qa_stage == 1 else "written tests"
    return GATE_LABELS.get(job.state, job.state.value)


def material(job: Job, *, written_tests: str | None = None) -> dict[str, Any]:
    """What the human sees at this gate, nothing more."""
    if job.state is JobState.AWAITING_BACKLOG_APPROVAL:
        return {"backlog": job.data.backlog}
    if job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL:
        return {
            "profile": job.profile.model_dump(mode="json") if job.profile else None,
            "plan": job.data.plan,
        }
    if job.state is JobState.AWAITING_REVIEW_APPROVAL:
        return {"review": job.data.reviews[-1] if job.data.reviews else None}
    if job.state is JobState.AWAITING_TEST_APPROVAL:
        if job.data.qa_stage == 1:
            return {
                "test_cases": job.data.test_cases,
                "plan_summary": (job.data.plan or {}).get("summary"),
            }
        return {"test_cases": job.data.test_cases, "written_tests": written_tests or ""}
    if job.state is JobState.AWAITING_DEPLOY_APPROVAL:
        return {"deployment": job.data.deploy, "stack": (job.data.plan or {}).get("stack", [])}
    return {}


def run(
    job: Job,
    profile: Profile,
    *,
    gate_material: dict[str, Any],
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    context = base_context(job, instructions=INSTRUCTIONS, jira=None, standards=standards)
    context["gate"] = gate_name(job)
    context["material"] = gate_material
    context["history"] = [
        {"to": t.to_state.value, "note": t.note}
        for t in job.history
        if t.from_state is not t.to_state and t.note
    ][-30:]
    _ = jira  # the supervisor never acts in Jira
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.SUPERVISOR, profile, context, provider=provider, **kwargs)


__all__ = ["INSTRUCTIONS", "gate_name", "material", "run"]
