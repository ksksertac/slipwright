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
from slipwright.roles.developer import IN_PARTS
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

#: Where each host looks for its build pipeline. DevOps may write here as well as into
#: the deployment folder, and nowhere else.
#:
#: Without it the engine polls a pull request for checks that nothing ever created:
#: ``ci_status`` answered "no checks reported", the development went green, and the whole
#: CI-red-goes-back-to-the-developer loop was unreachable. A repository whose pipeline
#: Slipwright wrote is one where the next change is checked too, by whoever opens it.
CI_FILES: dict[str, str] = {
    "github": ".github/workflows/",
    "bitbucket": "bitbucket-pipelines.yml",
}


def ci_path(source: str) -> str:
    """The pipeline file this project's host runs, or "" for a host with no convention."""
    return CI_FILES.get(source, "")


PLAN_INSTRUCTIONS = """\
Read the architecture and propose how this project is deployed. Pick the `target` the
project already points at — its existing infrastructure files, SDKs and services decide
it, not your preference — and only when nothing points either way choose the one its
stack fits best: `aws` or `azure`. Answer `none` when this project is not deployed to a
cloud at all (a library, a command-line tool) or when the folder already holds everything
this change needs; `none` means no deployment files, not no pipeline.

Always include the build pipeline at `{ci}` in `scripts`, whatever the target is -- a
library and a command-line tool have nothing to deploy but are still built and tested on
every change. It runs the project's own build and test commands from `project`, on the
branch and on every pull request, and when the target deploys a container image it builds
that image too and pushes it with credentials read from the host's secret store. Name the
secrets it needs in `notes`; never write one into a file. This is the check the pull
request waits on, so a green run must mean the project really builds.

`services` names the target's services this will use. `scripts` is the list of files you
will write, each with its path under `{folder}/` -- except the pipeline, which goes at
`{ci}` -- and one line saying what it does. Prefer the target's own declarative format
(CloudFormation or Terraform for AWS, Bicep or Terraform for Azure) with one shell script
to run it.

Match the size of the project, not the size of the format. Somebody asked for a
single-page note-taker and got a container cluster, a managed database and a load
balancer, which costs them money every month to run and cost them tokens to write. Start
from the pipeline alone and add a file only when this project cannot be delivered without
it. A page with no server of its own is static hosting, not a cluster; a service with no
data is one container, not a data tier as well. If you cannot name what a file is for in
one line, it does not belong. `notes` is what the person must supply themselves:
accounts, secrets, domains, quotas.

A person reads this and can change it before a single file is written, so say what you
mean in `summary`: what will be deployed where, and what it will cost them to run --
in money per month, not in adjectives."""

WRITE_INSTRUCTIONS = """\
Write the deployment files that were approved in `deploy`, exactly those paths and
nothing else, each as full file contents. Everything lives under `deployment/` except the
build pipeline, which goes at `pipeline_file`: its host looks nowhere else for it, and
the engine refuses any other path. They must work as they stand: no placeholders
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
    source: str = "github",
) -> RoleResult:
    """Stage one: propose how this project is deployed, for a person to approve."""
    pipeline = ci_path(source) or DEPLOY_FOLDER + "/"
    context = base_context(
        job,
        instructions=PLAN_INSTRUCTIONS.format(folder=DEPLOY_FOLDER, ci=pipeline),
        feedback=job.data.feedback,
        jira=jira,
        standards=standards,
    )
    context["plan"] = plan_outline(job.data.plan)
    context["project"] = project_facts(profile)
    context["deployment_folder"] = DEPLOY_FOLDER
    context["pipeline_file"] = pipeline
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
    truncated: str | None = None,
    continuation: dict[str, Any] | None = None,
    source: str = "github",
) -> RoleResult:
    """Stage two: write the approved scripts into the project's deployment folder.

    An approved plan can name seven files -- a Dockerfile, templates, three shell scripts
    and a README -- and all of them in one answer is how this role hits the output limit.
    ``truncated`` and ``continuation`` are the same door the developer and QA have: the
    engine offers them when an answer is cut off, and the work arrives in parts instead
    of failing.
    """
    instructions = WRITE_INSTRUCTIONS
    if truncated or continuation:
        instructions += IN_PARTS
    context = base_context(job, instructions=instructions, jira=jira, standards=standards)
    if truncated:
        context["output_was_truncated"] = truncated
    if continuation:
        context["continuation"] = continuation
    context["deploy"] = job.data.deploy
    context["plan"] = plan_outline(job.data.plan)
    context["project"] = project_facts(profile)
    context["deployment_folder"] = DEPLOY_FOLDER
    context["pipeline_file"] = ci_path(source) or DEPLOY_FOLDER + "/"
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
