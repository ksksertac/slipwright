"""DevOps: how the project is deployed, and the pull request that carries it.

Two things in two stages. First (T11.6) it reads the architecture and proposes how this
project gets deployed — AWS or Azure, which services, which scripts — for a person to
approve or change; then it writes those scripts into the project's ``deployment/``
folder. Afterwards it writes the pull request: everything mechanical (push, open PR,
poll CI, hand failures to the Developer) is the engine's job, and the DevOps model turns
the deterministic draft below into a title and body a reviewer would want to read.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, plan_outline, project_facts
from slipwright.roles.results import DeployPlan, DeveloperResult
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Write the pull request for this branch. `draft` is a factual description assembled from
the approved plan and the job history; `branch_diff` is what changed. Produce a concise
`pr_title` (imperative, under 70 characters) and a `pr_body` in Markdown that explains
what changed and why, lists the phases, and mentions how it was tested. Do not invent
anything that is not in the draft or the diff. If a `jira` section is present, comment
the outcome on the stories listed there (the PR link is added by the engine).
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""


DEPLOY_FOLDER = "deployment"

PLAN_INSTRUCTIONS = """\
Read the architecture and propose how this project is deployed. Pick the `target` the
project already points at — its existing infrastructure files, SDKs and services decide
it, not your preference — and only when nothing points either way choose the one its
stack fits best: `aws` or `azure`. Answer `none`, with no scripts, when this project is
not deployed to a cloud at all (a library, a command-line tool) or when the folder
already holds everything this change needs.

`services` names the target's services this will use. `scripts` is the list of files you
will write, each with its path under `{folder}/` and one line saying what it does: the
infrastructure definition, the build and push, the deploy itself, the parameters, and a
README a person can follow. Prefer the target's own declarative format (CloudFormation
or Terraform for AWS, Bicep or Terraform for Azure) with one shell script to run it, and
keep it to what this project actually needs — five to eight files is plenty. `notes` is
what the person must supply themselves: accounts, secrets, domains, quotas.

A person reads this and can change it before a single file is written, so say what you
mean in `summary`: what will be deployed where, and what it will cost them to run."""

WRITE_INSTRUCTIONS = """\
Write the deployment files that were approved in `deploy`, exactly those paths and
nothing else, each as full file contents. They must work as they stand: no placeholders
a person cannot fill in, every parameter named and documented, secrets read from the
target's secret store or the environment and never written into a file. Take the build,
test and run commands from `project`, and the region, service names and sizing from the
approved plan. Include the README the plan names, written for someone deploying this for
the first time: what to install, what to set, what to run, in order. If a file in
`existing` is already right, return it unchanged rather than inventing a second one."""


def plan_deploy(
    job: Job,
    profile: Profile,
    *,
    existing: dict[str, str] | None = None,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    """Stage one: propose how this project is deployed, for a person to approve."""
    context = base_context(
        job,
        instructions=PLAN_INSTRUCTIONS.format(folder=DEPLOY_FOLDER),
        feedback=job.data.feedback,
        jira=jira,
        standards=standards,
    )
    context["plan"] = plan_outline(job.data.plan)
    context["project"] = project_facts(profile)
    context["deployment_folder"] = DEPLOY_FOLDER
    context["existing"] = sorted(existing or {})
    context["previous_proposal"] = job.data.deploy
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        RoleName.DEVOPS, profile, context, provider=provider, output_schema_cls=DeployPlan, **kwargs
    )


def write_deployment(
    job: Job,
    profile: Profile,
    *,
    existing: dict[str, str] | None = None,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    """Stage two: write the approved scripts into the project's deployment folder."""
    context = base_context(job, instructions=WRITE_INSTRUCTIONS, jira=jira, standards=standards)
    context["deploy"] = job.data.deploy
    context["plan"] = plan_outline(job.data.plan)
    context["project"] = project_facts(profile)
    context["deployment_folder"] = DEPLOY_FOLDER
    context["existing"] = existing or {}
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        RoleName.DEVOPS,
        profile,
        context,
        provider=provider,
        output_schema_cls=DeveloperResult,
        **kwargs,
    )


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
    deploy = job.data.deploy or {}
    if deploy.get("target") and deploy.get("target") != "none" and job.data.deploy_written:
        lines += ["## Deployment", "", f"Target: {deploy['target']}", ""]
        lines += [f"- `{path}`" for path in job.data.deploy_written]
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


__all__ = [
    "DEPLOY_FOLDER",
    "INSTRUCTIONS",
    "PLAN_INSTRUCTIONS",
    "WRITE_INSTRUCTIONS",
    "draft_description",
    "plan_deploy",
    "run",
    "write_deployment",
]
