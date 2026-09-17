"""Product Owner: turns the request into a backlog of epics, stories and tasks.

The PO does not decide *how* anything is built — that is the Architect's job — but it
does read the repository lightly (tree, manifests, README) so the backlog fits the
product that exists. On approval the backlog is mirrored into Jira (T7.4) and becomes the
tree the board tracks.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, require_worktree, scan_worktree
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
You are the Product Owner. Turn `request` into a backlog: epics, each with user stories,
each with tasks. An epic is an outcome the requester will recognise; a story is one
user-visible capability written as "As a <who> I can <what> so that <why>"; a task is one
unit of engineering work a single specialist can finish and a tester can verify. Give
every task a short title and a one- or two-sentence description that says what done
looks like. Order tasks so that what others depend on comes first. Do not decide
technology, files or architecture — the Architect does that from your backlog. Keep the
backlog as small as the request allows: three to eight tasks is typical.
If `feedback` is present, a human rejected your previous backlog (`previous_backlog`);
address every point in it. If a `jira` section is present you may add Jira actions for
issues that already exist; the backlog itself is mirrored to Jira by the engine.
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""


def run(
    job: Job,
    profile: Profile,
    *,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    context = base_context(
        job, instructions=INSTRUCTIONS, feedback=job.data.feedback, jira=jira, standards=standards
    )
    context["previous_backlog"] = job.data.backlog
    scan = scan_worktree(require_worktree(job))
    context["repository"] = {"tree": scan["tree"][:120], "files": scan["files"]}
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.PO, profile, context, provider=provider, **kwargs)


__all__ = ["INSTRUCTIONS", "run"]
