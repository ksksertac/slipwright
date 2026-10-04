"""DevOps: how the project is deployed, and the pull request that carries it.

Two things in two stages. First (T11.6) it reads the architecture and proposes how this
project gets deployed — AWS or Azure, which services, which scripts — for a person to
approve or change; then it writes those scripts into the project's ``deployment/``
folder. Afterwards it writes the pull request: everything mechanical (push, open PR,
poll CI, hand failures to the Developer) is the engine's job, and the DevOps model turns
the deterministic draft below into a title and body a reviewer would want to read.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import (
    MANIFEST_FILES,
    base_context,
    list_tree,
    plan_outline,
    project_facts,
    read_files,
    where_it_runs,
)
from slipwright.roles.developer import IN_PARTS
from slipwright.roles.results import DeployPlan, DeveloperResult
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Write the pull request for this branch. `draft` is a factual description assembled from
the approved plan and the job history; `changed_files` lists the files the branch changed
and by how many lines. Produce a concise `pr_title` (imperative, under 70 characters) and
a `pr_body` in Markdown that explains what changed and why, lists the phases, and mentions
how it was tested. Do not invent anything that is not in the draft or the file list. If
a `jira` section is present, comment the outcome on the stories listed there (the PR link
is added by the engine).
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
    """Where this project's host runs its pipeline from -- a file, or for GitHub the
    folder of workflows -- or "" for a host with no convention. This is what DevOps is
    *allowed* to write; :func:`pipeline_file` is the one file it is *told* to write."""
    return CI_FILES.get(source, "")


def pipeline_file(source: str, worktree: Path | None = None) -> str:
    """The one pipeline file DevOps writes, named as a file.

    GitHub's convention is a folder, and DevOps used to be handed the folder under the
    name ``pipeline_file``. A model told to write "the file" at a folder fills the gap
    itself -- it announced that the path "is changed to ci.yml in the real configuration",
    which no configuration does. A repository that already has a workflow keeps it
    (``ci.yml`` first); one that has none gets ``ci.yml``.
    """
    where = ci_path(source)
    if not where.endswith("/"):
        return where
    if worktree is not None and (worktree / where).is_dir():
        found = sorted(
            p.name for p in (worktree / where).iterdir() if p.suffix in (".yml", ".yaml")
        )
        for name in ("ci.yml", "ci.yaml", *found):
            if name in found:
                return where + name
    return where + "ci.yml"


def outside(paths: Iterable[str], source: str) -> list[str]:
    """The paths DevOps may not write: anything not under the deployment folder or the
    host's pipeline. The project's own README is among them -- it describes the product,
    and a deployment README lives at ``deployment/README.md``."""
    pipeline = ci_path(source)
    prefix = f"{DEPLOY_FOLDER}/"
    return sorted(
        path
        for path in paths
        if not path.removeprefix("./").startswith(prefix)
        and not (pipeline and path.removeprefix("./").startswith(pipeline))
    )


#: How many of the files the plan's phases name are sent along, and how much of each: the
#: package scripts, the checks and the tools the phases wrote are what a pipeline runs.
PHASE_FILES = 30
PHASE_FILE_BYTES = 6_000


def project_view(worktree: Path | None, plan: dict[str, Any] | None, source: str) -> dict[str, Any]:
    """What DevOps reads of the project before it plans or writes a pipeline: the tree,
    the manifests (``package.json``, ``pyproject.toml`` ...), the pipeline the host
    already runs, and the files the plan's phases wrote.

    It used to see only ``deployment/``. Asked for a pipeline that packages a desktop app
    for three platforms, it had no ``package.json`` to take the commands from and no
    existing workflow whose checks it must keep, said so five times over -- "the packaging
    commands, the archive paths and the current CI are not in the context" -- wrote
    nothing, and the development failed at DevOps.
    """
    if worktree is None or not worktree.is_dir():
        return {}
    ci = ci_path(source)
    pipelines: list[str] = []
    if ci.endswith("/") and (worktree / ci).is_dir():
        pipelines = sorted(
            f"{ci}{p.name}" for p in (worktree / ci).iterdir() if p.suffix in (".yml", ".yaml")
        )
    elif ci:
        pipelines = [ci]
    named = [
        str(f)
        for phase in (plan or {}).get("phases", [])
        for f in phase.get("files", []) or []
        if isinstance(f, str)
    ]
    wanted = [f for f in dict.fromkeys(named) if f not in MANIFEST_FILES][:PHASE_FILES]
    return {
        "tree": list_tree(worktree, first=wanted),
        "manifests": read_files(worktree, MANIFEST_FILES),
        "current_pipeline": read_files(worktree, pipelines),
        "phase_files": read_files(worktree, wanted, max_bytes=PHASE_FILE_BYTES),
    }


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
`{ci}` -- and one line saying what it does. Nothing else in the repository is yours to
write: not the project's own `README.md`, not its source, not another configuration file.
A README for whoever deploys this goes at `{folder}/README.md`, and the engine sends a plan
naming any other path straight back. Prefer the target's own declarative format
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
in money per month, not in adjectives.
`project_files` is the project as it stands: its `tree`, its `manifests` (the build and
package scripts are there), the `current_pipeline` and the files the phases wrote. Read
the commands from there."""

WRITE_INSTRUCTIONS = """\
Write the deployment files that were approved in `deploy`, exactly those paths and
nothing else, each as full file contents. Everything lives under `deployment/` except the
build pipeline, which goes at `pipeline_file`: its host looks nowhere else for it, and
the engine refuses any other path -- the project's own `README.md` included. They must
work as they stand: no placeholders a person cannot fill in, every parameter named and
documented, secrets read from the target's secret store or the environment and never
written into a file. Take the build, test and run commands from `project`, and the
region, service names and sizing from the approved plan. Include the README the plan
names, at `deployment/README.md`, written for someone deploying this for the first time:
what to install, what to set, what to run, in order. If a file in `existing` is already
right, return it unchanged rather than inventing a second one.
`project_files` holds what you need to write them: the `tree`, the `manifests` with the
project's own scripts (`package.json`'s `scripts`, `pyproject.toml`, the Makefile), the
`current_pipeline` -- keep every check it already runs when you rewrite it -- and the
`phase_files` the developers wrote, the packaging and verification tools among them.
Take every command from there or from `project`. Never answer that something is missing
from the context and write nothing: a pipeline that runs the project's own build and test
commands is always possible, and is the least this answer must contain. If a detail
really cannot be known -- a secret, an account -- read it from the host's secret store or
an input and say so in the deployment README."""


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
    problem: str | None = None,
) -> RoleResult:
    """Stage one: propose how this project is deployed, for a person to approve.

    ``problem`` is set when the last proposal named a path DevOps may not write; the
    engine asks once more rather than putting a plan in front of a person that cannot be
    carried out once they approve it."""
    pipeline = pipeline_file(source, job.worktree_path) or DEPLOY_FOLDER + "/"
    instructions = PLAN_INSTRUCTIONS.format(folder=DEPLOY_FOLDER, ci=pipeline)
    if problem:
        instructions += (
            "\nYour previous proposal was refused (`previous_answer_problem`); answer again "
            "with the whole proposal and fix exactly that."
        )
    context = base_context(
        job,
        instructions=instructions,
        feedback=job.data.feedback,
        jira=jira,
        standards=standards,
    )
    context["plan"] = plan_outline(job.data.plan)
    context["project"] = project_facts(profile)
    context["deployment_folder"] = DEPLOY_FOLDER
    context["where_it_runs"] = where_it_runs()
    context["pipeline_file"] = pipeline
    context["existing"] = sorted(existing or {})
    context["project_files"] = project_view(job.worktree_path, job.data.plan, source)
    context["previous_proposal"] = job.data.deploy
    if problem:
        context["previous_answer_problem"] = problem
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
    problem: str | None = None,
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
    if problem:
        instructions += (
            "\nYour previous answer was rejected (`previous_answer_problem`); answer again "
            "and fix exactly that."
        )
    context = base_context(job, instructions=instructions, jira=jira, standards=standards)
    context["where_it_runs"] = where_it_runs()
    if truncated:
        context["output_was_truncated"] = truncated
    if continuation:
        context["continuation"] = continuation
    if problem:
        context["previous_answer_problem"] = problem
    context["deploy"] = job.data.deploy
    context["plan"] = plan_outline(job.data.plan)
    context["project"] = project_facts(profile)
    context["deployment_folder"] = DEPLOY_FOLDER
    context["pipeline_file"] = pipeline_file(source, job.worktree_path) or DEPLOY_FOLDER + "/"
    context["existing"] = existing or {}
    context["project_files"] = project_view(job.worktree_path, job.data.plan, source)
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
    changed_files: str,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    # the files and their line counts, not the diff: the draft already says what was done
    # and why, and the whole branch's diff was the biggest prompt a development sent
    context = base_context(job, instructions=INSTRUCTIONS, jira=jira, standards=standards)
    context["draft"] = draft_description(job)
    context["changed_files"] = changed_files
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
    "ci_path",
    "draft_description",
    "outside",
    "pipeline_file",
    "plan_deploy",
    "run",
    "write_deployment",
]
