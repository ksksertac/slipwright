"""What people did while a development was paused, read against its plan.

A development can be paused so people work on its branch by hand, and pulled back in
when it carries on. The plan does not know any of that happened: it would set the
specialists to build again what somebody already wrote. The Architect -- who wrote the
plan -- reads what was pushed and says, for each phase still to build, whether it is
done, partly done or untouched. The engine decides from that where to carry on, and a
person approves it before anything is passed over.

The Architect in a second capacity, as QA is the standards reviewer: the same role,
model and permissions, different instructions and a different output.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context
from slipwright.roles.results import ReconcileResult
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
You are the Software Architect. The development was paused and people worked on this
branch by hand; what they pushed has been pulled in. `commits` lists the commits since
the pause and `diff` is everything they changed -- together with any half-written work
an agent had left when it was paused. `remaining_phases` are the phases of your plan
that had not been built yet; `finished_phases` were built before the pause and are not
in question.
For every phase in `remaining_phases` return one entry in `phases` with its `number`:
`done` when everything its goal asks for is now in the code, `partial` when some of it
is, `untouched` when none of it is, and in `evidence` the files or commits that show it.
Judge by the code in `diff`, not by commit messages alone, and when in doubt say
`partial`: a phase called done is never built, while a partial one is finished by its
specialist over what is already there. `summary` says in a paragraph what the people
did, for the specialists who carry on after them. If `feedback` is present a person
disagreed with your last reading; address it. Leave `jira_actions` empty."""


def run(
    job: Job,
    profile: Profile,
    *,
    finished: list[dict[str, Any]],
    remaining: list[dict[str, Any]],
    commits: list[tuple[str, str]],
    diff: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    # neither Jira nor the standards are asked about here: this is a reading of what is
    # there, not something to build against them
    context = base_context(
        job, instructions=INSTRUCTIONS, feedback=job.data.feedback, jira=None, standards=None
    )
    context["finished_phases"] = finished
    context["remaining_phases"] = remaining
    context["commits"] = [{"sha": sha, "subject": subject} for sha, subject in commits]
    context["diff"] = diff
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        RoleName.ARCHITECT,
        profile,
        context,
        provider=provider,
        output_schema_cls=ReconcileResult,
        **kwargs,
    )


__all__ = ["INSTRUCTIONS", "run"]
