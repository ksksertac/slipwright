"""Standards review (T9.5): after a phase passes the build gate, QA reads the phase's
diff against the standards its specialist was given and lists violations.

The reviewer sees exactly what the specialist saw — the same retrieved sections — so a
violation always names a section that was in the prompt. It is QA in a second capacity:
the same role, model and permissions, different instructions and a different output
(``violations`` instead of test cases).
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, project_facts
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
You are QA acting as the standards reviewer. `phase_diff` is what the specialist changed
for `current_phase`; `standards.retrieved` are the sections that specialist was told to
follow and `standards.core` the rules that always apply. Check the diff against them and
return `violations`: one entry per breach with the section heading, the file, the line
in the new file where it is visible (when there is one), `severity` and a concrete `fix`.
`blocking` is for a breach of a rule the section states as a must (secrets, data loss,
missing migrations, unsafe retries, missing tests the section demands); `advisory` is for
style, naming and structure. Do not invent rules that are not in the sections, do not
report the same breach twice, and return an empty list when the change is clean. Leave
`test_cases` and `changes` empty. `summary` is one paragraph on the overall quality."""


def run(
    job: Job,
    profile: Profile,
    *,
    phase: dict[str, Any],
    phase_number: int,
    phase_diff: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    context = base_context(job, instructions=INSTRUCTIONS, jira=jira, standards=standards)
    context["project"] = project_facts(profile)
    context["current_phase"] = {"number": phase_number, **phase}
    context["phase_diff"] = phase_diff
    context["review_round"] = job.data.review_rounds
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.QA, profile, context, provider=provider, **kwargs)


__all__ = ["INSTRUCTIONS", "run"]
