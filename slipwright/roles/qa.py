"""QA in two stages, and one question asked outside them.

Stage one proposes test cases for the change on the branch and stops for human review;
the human may add and remove cases. Stage two writes tests for the approved list only.
Both stages see the branch diff so they test what was actually built.

``triage`` is the third job and belongs to no stage: when a build gate fails, QA reads the
failure before anyone starts fixing code and says which side was wrong. A test that
asserts something nobody agreed to is QA's own mistake to correct; anything else is the
code's fault, and QA hands the specialist a diagnosis instead of a patch.
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
UI or API the way a user would. Keep the list tight: at most 15 cases, each with a short
name and a description of one or two sentences — the list is for a person to approve, not
a test plan document. Do not write test code yet; return only `test_cases`.
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


GATE_TRIAGE = """\
You are QA. A build gate failed on this branch and `build_failure` holds the tail of the
run. Decide one thing only: was the failing test itself wrong, or was the code wrong?
The test is wrong when it asserts something nobody agreed to — it contradicts `plan`,
`current_phase` or `approved_test_cases`, it was written against an older shape of the
code, it fixes an incidental detail (wording, ordering, formatting) that was never part of
the contract, or it contradicts itself. The code is wrong in every other case, including
when the test is ugly, slow or awkward but the behaviour it asserts is the agreed one.
Never weaken, skip, delete or loosen a test to make it pass, and never change a test
merely because the code disagrees with it: if two sides of the project disagree about a
contract, the side the plan named is right and the other one is the defect.
Return `gate_verdict`. With `test_is_wrong`, also return the complete corrected contents
of the test files in `changes` — test files only, never production code — and say in
`summary`, in one or two sentences, what the test asserted, what the agreed behaviour is
and why the test was the side that was wrong. With `code_is_wrong`, return no `changes`
and say in `summary` exactly what the code must do differently and where; the specialist
who fixes it is given that sentence and nothing else of yours.
Return no `test_cases` and no `violations` here."""


def run(
    job: Job,
    profile: Profile,
    *,
    branch_diff: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
    truncated: str | None = None,
    problem: str | None = None,
) -> RoleResult:
    stage = job.data.qa_stage
    worktree = require_worktree(job)
    instructions = STAGE_ONE if stage == 1 else STAGE_TWO
    if truncated:
        instructions += (
            "\nYour previous answer was cut off at the output limit and discarded "
            "(`output_was_truncated`). "
            + (
                "Return at most 8 cases with one-sentence descriptions."
                if stage == 1
                else "Return only the one or two most important test files now, complete; "
                "keep each file short and skip the rest of the cases in this answer."
            )
        )
    context = base_context(
        job, instructions=instructions, feedback=job.data.feedback, jira=jira, standards=standards
    )
    context["stage"] = stage
    if truncated:
        context["output_was_truncated"] = truncated
    if problem:
        context["previous_answer_problem"] = problem
        instructions += (
            "\nYour previous answer was rejected (`previous_answer_problem`); answer again "
            "and fix exactly that."
        )
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


def triage(
    job: Job,
    profile: Profile,
    *,
    build_failure: str,
    phase: dict[str, Any],
    branch_diff: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    """Ask QA whose fault a failed build gate is, before a specialist spends a fix attempt."""
    worktree = require_worktree(job)
    tree = list_tree(worktree)
    context = base_context(job, instructions=GATE_TRIAGE, jira=jira, standards=standards)
    context["project"] = project_facts(profile)
    context["plan"] = plan_outline(job.data.plan)
    context["current_phase"] = phase
    context["build_failure"] = build_failure
    context["branch_diff"] = branch_diff
    context["tree"] = tree
    context["existing_tests"] = read_files(worktree, _test_like(tree))
    if job.data.test_cases:
        context["approved_test_cases"] = job.data.test_cases

    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.QA, profile, context, provider=provider, **kwargs)


def is_test_path(path: str) -> bool:
    """Whether a path is somewhere QA may write while triaging a gate.

    Deliberately narrow: a triage fix that lands anywhere else is refused, so "the test
    was wrong" can never become a licence to edit the code under test.
    """
    parts = path.replace("\\", "/").split("/")
    name = parts[-1]
    return (
        any(part in ("test", "tests", "spec", "specs", "__tests__", "e2e") for part in parts[:-1])
        or name.startswith("test_")
        or name.endswith(("_test.py", "_test.go", "_test.ts", "_test.tsx", "Test.kt", "Tests.kt"))
        or ".test." in name
        or ".spec." in name
    )


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


__all__ = [
    "GATE_TRIAGE",
    "STAGE_ONE",
    "STAGE_TWO",
    "is_test_path",
    "normalise_cases",
    "run",
    "triage",
]
