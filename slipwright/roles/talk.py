"""An agent answering a person who wrote to it while it worked.

The pipeline never asks the agents anything a person typed: what they say reaches the
next call as an instruction (``messages_from_human``), and nothing comes back. This is
the other direction. A person looking at a phase asks the agent on it what it is doing,
or why, and gets an answer -- from the agent that holds the step, on that agent's model,
with what the step was asked to do, what has happened in it and what it has written so
far in front of it.

The answer is a side call. It does not move the development, does not take its turn,
and changes nothing: when the person was really asking for something to be done
differently the agent says so in ``change``, and it is the person who decides whether
that becomes an instruction for this step or a new plan.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import plan_outline, writing_rules
from slipwright.roles.results import AgentAnswer
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
A person is following this development and has written to you, the agent on the step in
`step`, while you work on it. `question` is what they wrote; `earlier` is what they asked
you on this step before and what you answered.

Answer them as the agent doing the work: plainly and briefly, about what you are doing,
why, and what is left. Work only from the context. `step` holds what this step was asked
to do and what has happened in it; `work_in_progress`, when present, is what is written
in the checkout so far. When the context does not tell you something, say that rather
than guessing.

If what they wrote asks for the work to be done differently -- something to do, avoid,
use or change, in this step or in the plan -- restate it in `change` as one instruction
you could act on. Leave `change` null for a question. Nothing is changed because you
wrote it there: the person decides what happens with it."""

#: How much of one step's record an answer is shown: the items of each list, and of each
#: item the start of its detail. A phase's history runs to dozens of lines and a build log
#: to thousands of characters; the question is about what is happening, not all of it.
ITEMS_KEPT = 30
DETAIL_KEPT = 400


def step_record(detail: Any) -> dict[str, Any]:
    """A step's detail as the answering agent reads it: the step, its own account and
    each list it produced, cut down to what a question about it needs."""
    groups: list[dict[str, Any]] = []
    for group in detail.groups:
        items: list[dict[str, Any]] = []
        for item in list(group.items)[-ITEMS_KEPT:]:
            entry: dict[str, Any] = {"what": item.title, "status": str(item.status)}
            if item.detail:
                entry["detail"] = item.detail[:DETAIL_KEPT]
            if item.children:
                entry["items"] = [c.title for c in item.children[:ITEMS_KEPT]]
            items.append(entry)
        groups.append({"list": group.label, "items": items})
    return {
        "name": detail.label,
        "status": str(detail.status),
        "summary": detail.summary or None,
        "record": groups,
    }


def run(
    job: Job,
    profile: Profile,
    *,
    role: RoleName,
    step: dict[str, Any],
    question: str,
    earlier: list[dict[str, str]],
    phase: int | None = None,
    work_in_progress: str | None = None,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
) -> RoleResult:
    context: dict[str, Any] = {
        "instructions": INSTRUCTIONS,
        "writing": writing_rules(job.data.language),
        "request": job.request,
        "plan": plan_outline(job.data.plan, None if phase is None else phase - 1),
        "step": step,
        "earlier": earlier,
        "question": question,
    }
    if work_in_progress:
        context["work_in_progress"] = work_in_progress
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        role,
        profile,
        context,
        provider=provider,
        output_schema_cls=AgentAnswer,
        **kwargs,
    )


__all__ = ["INSTRUCTIONS", "run", "step_record"]
