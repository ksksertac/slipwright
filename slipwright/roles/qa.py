"""QA in two stages.

Stage one proposes test cases for the change on the branch and stops for human review;
the human may add and remove cases. Stage two writes tests for the approved list only.
Both stages see the branch diff so they test what was actually built.
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

STAGE_ONE = """\
You are QA. Stage 1 of 2. Review `branch_diff` (what the specialists changed for
`request`, see `plan` for the backlog it implements) and propose the test cases that
would prove it works: name each case and describe precisely what it checks. Cover the
levels the change needs — unit cases for logic, integration cases for each real boundary
(database, HTTP, queue) and end-to-end cases that walk the user journey through the real
UI or API the way a user would. Do not write test code yet; return only `test_cases`.
If `feedback` is present, a human rejected your previous list; address every point in it.
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""

STAGE_TWO = """\
You are QA. Stage 2 of 2. Write automated tests for exactly the cases in
`approved_test_cases` — no more, no fewer — using the project's existing test layout and
frameworks (see `tree`, `existing_tests`, `project`). End-to-end cases use the project's
e2e runner (Playwright, Cypress, Detox, …) when one exists; otherwise drive the public
API in-process and say so in `summary`. Return the complete contents of each test file in
`changes`; paths are relative to the project root. If `build_failure` is present, your
previous tests did not pass the build gate: read the output and fix them.
If a `jira` section is present, open a Bug issue (parent: the story's key) for each defect
you find in the change, and close it with a comment once the fix passes.
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""


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
    stage = job.data.qa_stage
    worktree = require_worktree(job)
    instructions = STAGE_ONE if stage == 1 else STAGE_TWO
    context = base_context(
        job, instructions=instructions, feedback=job.data.feedback, jira=jira, standards=standards
    )
    context["stage"] = stage
    context["project"] = project_facts(profile)
    context["plan"] = plan_outline(job.data.plan)
    context["branch_diff"] = branch_diff
    if stage == 1:
        context["previous_test_cases"] = job.data.test_cases
    else:
        tree = list_tree(worktree)
        context["approved_test_cases"] = job.data.test_cases
        context["tree"] = tree
        context["existing_tests"] = read_files(worktree, _test_like(tree))
        if job.data.last_build_output:
            context["build_failure"] = job.data.last_build_output

    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.QA, profile, context, provider=provider, **kwargs)


def _test_like(tree: list[str], limit: int = 12) -> list[str]:
    hits = [
        p
        for p in tree
        if any(part in ("test", "tests", "spec", "__tests__") for part in p.split("/")[:-1])
        or p.rsplit("/", 1)[-1].startswith("test_")
        or ".test." in p
        or p.endswith("_test.py")
    ]
    return hits[:limit]


def normalise_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Human edits arrive as loose dicts; keep only name/description, drop empties."""
    out: list[dict[str, Any]] = []
    for case in cases:
        name = str(case.get("name", "")).strip()
        description = str(case.get("description", "")).strip()
        if name and description:
            out.append({"name": name, "description": description})
    return out


__all__ = ["STAGE_ONE", "STAGE_TWO", "normalise_cases", "run"]
