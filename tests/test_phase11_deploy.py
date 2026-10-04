"""T11.5-T11.6: the stack the Architect proposes, and the deployment DevOps writes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine, InvalidEdit
from slipwright.pipeline import StepStatus, lane_for
from slipwright.providers.scripted import ScriptedProvider
from slipwright.roles.devops import DEPLOY_FOLDER
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.steps import step_detail
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

AWS_PLAN: dict[str, Any] = {
    "summary": "Two containers on ECS behind an ALB.",
    "target": "aws",
    "services": ["ECS Fargate", "RDS PostgreSQL"],
    "scripts": [
        {"path": "deployment/main.tf", "purpose": "the cluster, the service and the database"},
        {"path": "deployment/deploy.sh", "purpose": "build, push and roll out"},
        {"path": "deployment/README.md", "purpose": "how to run it the first time"},
    ],
    "notes": ["An AWS account with an ECR repository", "A domain for the load balancer"],
}

WRITTEN: dict[str, Any] = {
    "summary": "wrote the terraform, the script and the readme",
    "changes": [
        {"path": "deployment/main.tf", "content": 'resource "aws_ecs_service" "app" {}\n'},
        {"path": "deployment/deploy.sh", "content": "#!/bin/sh\nterraform apply\n"},
        {"path": "deployment/README.md", "content": "# Deployment\n\nRun deploy.sh.\n"},
    ],
}


def _provider(seed: Profile, deploy: dict[str, Any] | None = None) -> ScriptedProvider:
    provider = full_provider(seed, phases=1)
    if deploy is not None:
        provider.discovery["deploy"] = deploy
        provider.discovery["deploy_write"] = WRITTEN
    return provider


@pytest.fixture
def seeded(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, _provider(seed, AWS_PLAN))


@pytest.fixture
def client(seeded: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(seeded, resume_on_startup=False, require_auth=False)) as c:
        yield c


def _to_deploy_gate(engine: Engine, repo: Path) -> Job:
    """Run a development up to the deployment gate."""
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("add a health endpoint", project_id=project.id).id)
    job = engine.approve(job.id)  # backlog -> architecture
    job = engine.approve(job.id)  # plan -> phases -> qa stage 1
    job = engine.approve(job.id)  # test cases -> tests written
    job = engine.approve(job.id)  # written tests -> devops proposes the deployment
    return job


# --- T11.5 the stack ------------------------------------------------------------------


def test_the_architects_stack_reaches_the_plan_and_can_be_edited(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    from slipwright.schemas.profile import RoleName

    provider = full_provider(seed, phases=1)
    plan = dict(provider.replies[RoleName.ARCHITECT])  # type: ignore[arg-type]
    plan["stack"] = [
        {"domain": "backend", "language": "Python", "framework": "FastAPI", "why": "it is there"},
        {"domain": "web", "language": "TypeScript", "framework": "React", "why": "for the page"},
    ]
    provider.replies[RoleName.ARCHITECT] = plan
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.approve(engine.start(engine.create_job("x", project_id=project.id).id).id)

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert [c["domain"] for c in job.data.plan["stack"]] == ["backend", "web"]

    # the person changes the web front-end before anything is written
    edited = dict(job.data.plan)
    edited["stack"] = [
        job.data.plan["stack"][0],
        {"domain": "web", "language": "TypeScript", "framework": "Vue", "why": "we know Vue"},
    ]
    job = engine.set_plan(job.id, edited)
    assert job.data.plan["stack"][1]["framework"] == "Vue"

    with pytest.raises(InvalidEdit):
        engine.set_plan(job.id, {**edited, "stack": [{"domain": "moon", "language": "x"}]})


def test_the_specialists_are_told_the_stack(
    store: JobStore, worktrees_root: Path, seed: Profile
) -> None:
    from slipwright.roles.common import plan_outline

    outline = plan_outline(
        {
            "summary": "s",
            "stack": [{"domain": "web", "language": "TypeScript", "framework": "React"}],
            "decisions": [],
            "phases": [{"goal": "g", "domain": "web"}],
        }
    )
    assert outline is not None
    assert outline["stack"][0]["framework"] == "React"


# --- T11.6 the deployment gate --------------------------------------------------------


def test_devops_proposes_a_deployment_and_waits(seeded: Engine, repo: Path) -> None:
    job = _to_deploy_gate(seeded, repo)

    assert job.state is JobState.AWAITING_DEPLOY_APPROVAL
    assert job.data.deploy is not None and job.data.deploy["target"] == "aws"
    assert [s["path"] for s in job.data.deploy["scripts"]] == [
        "deployment/main.tf",
        "deployment/deploy.sh",
        "deployment/README.md",
    ]
    assert "3 deployment script(s) proposed for aws" in (job.history[-1].note or "")
    assert job.data.pr_url is None  # nothing is pushed before the person has seen it
    assert job.worktree_path is not None
    assert not (job.worktree_path / DEPLOY_FOLDER).exists()  # nor written

    lane = lane_for(job)
    gate = next(c for c in lane.steps if c.key == "deploy_gate")
    assert gate.status is StepStatus.WAITING and gate.editable
    assert lane.pending_approval == "deployment"

    detail = step_detail(job, "deploy_gate")
    assert detail is not None
    groups = {g.key: g for g in detail.groups}
    assert [i.title for i in groups["scripts"].items] == [
        "deployment/main.tf",
        "deployment/deploy.sh",
        "deployment/README.md",
    ]
    assert groups["deployment"].items[0].detail == "aws"


def test_approving_writes_the_scripts_into_the_deployment_folder(
    seeded: Engine, repo: Path
) -> None:
    job = seeded.approve(_to_deploy_gate(seeded, repo).id)

    assert job.state is JobState.DONE
    assert job.data.deploy_written == [
        "deployment/main.tf",
        "deployment/deploy.sh",
        "deployment/README.md",
    ]
    assert job.worktree_path is not None
    folder = job.worktree_path / DEPLOY_FOLDER
    assert (folder / "deploy.sh").read_text(encoding="utf-8").startswith("#!/bin/sh")
    assert (folder / "README.md").exists()
    notes = [t.note or "" for t in job.history]
    assert any("3 deployment file(s) written" in n for n in notes)
    assert any(n.startswith("approved 3 deployment script(s) for aws") for n in notes)
    assert job.data.pr_url == "https://example.test/pr/1"


def _as_the_feed_reads(note: str) -> str | None:
    """What the activity feed shows for an engine note: the first rule in
    web/src/i18n/notes.ts that matches it, the way `noteText` walks them. None when no
    rule does, which the feed shows as the note itself."""
    import re

    source = Path("web/src/i18n/notes.ts").read_text(encoding="utf-8")
    rules = re.findall(r're:\s*/((?:\\/|[^/\n])+)/,\s*out:\s*"([^"]*)"', source)
    for pattern, out in rules:
        if re.search(pattern.replace("\\/", "/"), note):
            return out
    return None


def test_a_deployment_that_was_written_does_not_read_as_a_failure(
    seeded: Engine, repo: Path
) -> None:
    """Every note DevOps leaves starts "devops: ", and the feed's rule for "devops: ..."
    was written for the ones that end a development -- no token, a push refused. The
    proposal and the written files matched it too, so a deployment written, pushed and
    merged read in History as "DevOps could not finish: 4 deployment file(s) written"."""
    job = seeded.approve(_to_deploy_gate(seeded, repo).id)
    assert job.state is JobState.DONE

    said = [t.note for t in job.history if (t.note or "").startswith("devops:")]
    assert any("proposed" in n for n in said) and any("written" in n for n in said)
    for note in said:
        shown = _as_the_feed_reads(note)
        assert shown is not None and "could not finish" not in shown, (note, shown)
    # and the failures still say so
    failure = _as_the_feed_reads("devops: no token for GitHub")
    assert failure is not None and "could not finish" in failure


def test_what_came_out_is_read_again_when_the_development_moves() -> None:
    """The result card asked every twenty seconds while the development ran and stopped
    asking when it finished. The deployment is written, pushed and the development done
    within a second, so the last answer was the branch before DevOps: the finished page
    listed five files and offered a merge of the branch the pull request had nine on."""
    web = Path("web/src")
    card = (web / "components" / "ResultCard.tsx").read_text(encoding="utf-8")
    assert "job.history.length" in card, "each recorded step must be a new question"
    hooks = (web / "api" / "hooks.ts").read_text(encoding="utf-8")
    hook = hooks[hooks.index("export function useJobResult") :][:600]
    assert "step" in hook and "queryKey: [...keys.jobResult(id), step]" in hook


def test_the_person_can_edit_the_proposal_before_approving(
    seeded: Engine, client: TestClient, repo: Path
) -> None:
    job = _to_deploy_gate(seeded, repo)
    edited = {
        "target": "azure",
        "services": ["Container Apps"],
        "scripts": [{"path": "deployment/main.bicep", "purpose": "the whole thing"}],
        "notes": [],
    }
    resp = client.put(f"/api/jobs/{job.id}/deploy", json=edited)
    assert resp.status_code == 200
    assert resp.json()["data"]["deploy"]["target"] == "azure"

    # a script outside the deployment folder is refused
    bad = {**edited, "scripts": [{"path": "src/deploy.sh", "purpose": "no"}]}
    assert client.put(f"/api/jobs/{job.id}/deploy", json=bad).status_code == 400

    job = seeded.store.get(job.id)
    assert [s["path"] for s in job.data.deploy["scripts"]] == ["deployment/main.bicep"]


def test_rejecting_sends_it_back_for_another_proposal(seeded: Engine, repo: Path) -> None:
    job = _to_deploy_gate(seeded, repo)
    seeded.provider.discovery["deploy"] = {
        **AWS_PLAN,
        "summary": "smaller",
        "scripts": [{"path": "deployment/main.tf", "purpose": "just the cluster"}],
    }
    job = seeded.reject(job.id, "too much for a health endpoint")

    assert job.state is JobState.AWAITING_DEPLOY_APPROVAL
    assert len(job.data.deploy["scripts"]) == 1
    assert job.data.devops_stage == 1


def test_a_project_with_nothing_to_deploy_never_stops(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = full_engine(store, worktrees_root, seed, _provider(seed))  # canned: target none
    job = _to_deploy_gate(engine, repo)

    assert job.state is JobState.DONE
    assert job.data.deploy is not None and job.data.deploy["target"] == "none"
    assert job.data.deploy_written == []
    assert [c.key for c in lane_for(job).steps if c.key.startswith("deploy")] == ["deploy"]
    assert any("nothing to deploy" in (t.note or "") for t in job.history)


def test_the_build_pipeline_is_written_where_its_host_looks_for_it(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    """The one file DevOps may write outside the deployment folder.

    Without it the engine polled a pull request for checks that nothing had created:
    every development went green on "no checks reported" and the CI-red-goes-back-to-the-
    developer loop could never run. The path belongs to the project's own host, so it is
    resolved from the project rather than assumed to be GitHub's.
    """
    workflow = ".github/workflows/ci.yml"
    provider = _provider(seed, {**AWS_PLAN, "scripts": [{"path": workflow, "purpose": "build"}]})
    provider.discovery["deploy_write"] = {
        "summary": "wrote the pipeline",
        "changes": [{"path": workflow, "content": "name: ci\non: [push, pull_request]\n"}],
    }
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.approve(_to_deploy_gate(engine, repo).id)

    assert job.state is JobState.DONE, job.history[-1].note
    assert job.data.deploy_written == [workflow]
    assert job.worktree_path is not None
    assert (job.worktree_path / workflow).read_text(encoding="utf-8").startswith("name: ci")


def test_the_pipeline_path_follows_the_projects_own_host(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    """A Bitbucket project gets Bitbucket's file; GitHub's would simply never run."""
    from slipwright.roles.devops import ci_path

    assert ci_path("github") == ".github/workflows/"
    assert ci_path("bitbucket") == "bitbucket-pipelines.yml"
    assert ci_path("whatever") == ""

    plan = {**AWS_PLAN, "scripts": [{"path": "bitbucket-pipelines.yml", "purpose": "build"}]}
    provider = _provider(seed, plan)
    provider.discovery["deploy_write"] = {
        "summary": "the wrong host's file",
        "changes": [{"path": ".github/workflows/ci.yml", "content": "name: ci\n"}],
    }
    engine = full_engine(store, worktrees_root, seed, provider)
    project = engine.create_project(
        Project(name="theirs", repo_path=repo, source="bitbucket", github_repo="acme/demo")
    )
    job = engine.start(engine.create_job("add a health endpoint", project_id=project.id).id)
    for _ in range(4):
        job = engine.approve(job.id)
    job = engine.approve(job.id)

    assert job.state is JobState.FAILED
    assert "bitbucket-pipelines.yml" in (job.history[-1].note or "")


def test_deployment_files_outside_the_folder_fail_the_job(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    provider = _provider(seed, AWS_PLAN)
    provider.discovery["deploy_write"] = {
        "summary": "sneaking into the product",
        "changes": [{"path": "src/app.py", "content": "# hello\n"}],
    }
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.approve(_to_deploy_gate(engine, repo).id)

    assert job.state is JobState.FAILED
    assert "wrote outside deployment/" in (job.history[-1].note or "")


def test_devops_is_told_the_pipeline_file_by_name(seeded: Engine, repo: Path) -> None:
    """GitHub's convention is a folder; DevOps is handed a file.

    Handed the folder as ``pipeline_file``, a model announced that the path "is changed to
    ci.yml in the real configuration" -- no configuration does that -- and planned around
    it. A repository that already has a workflow keeps the one it has.
    """
    from slipwright.roles.devops import pipeline_file

    _to_deploy_gate(seeded, repo)
    asked = next(r for r in seeded.provider.requests if "propose how this project" in r.prompt)
    assert ".github/workflows/ci.yml" in asked.prompt

    assert pipeline_file("github", repo) == ".github/workflows/ci.yml"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "build.yaml").write_text("name: b\n", encoding="utf-8")
    assert pipeline_file("github", repo) == ".github/workflows/build.yaml"
    assert pipeline_file("bitbucket", repo) == "bitbucket-pipelines.yml"


ROOT_README = {
    **AWS_PLAN,
    "scripts": [*AWS_PLAN["scripts"], {"path": "README.md", "purpose": "the project readme"}],
}


def test_a_proposal_naming_the_projects_readme_is_sent_back_before_the_gate(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    """A path DevOps may not write was caught only at the write, after the person had
    approved it -- and every retry wrote the same approved plan into the same refusal."""
    provider = _provider(seed)
    provider.discovery["deploy_write"] = WRITTEN
    provider.discovery["deploy"] = lambda r: (
        AWS_PLAN if "previous_answer_problem" in r.prompt else ROOT_README
    )
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _to_deploy_gate(engine, repo)

    assert job.state is JobState.AWAITING_DEPLOY_APPROVAL
    assert "README.md" not in [s["path"] for s in job.data.deploy["scripts"]]
    assert any("may not write (README.md)" in (t.note or "") for t in job.history)
    assert engine.approve(job.id).state is JobState.DONE


def test_a_proposal_that_keeps_naming_it_reaches_the_gate_without_it(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    engine = full_engine(store, worktrees_root, seed, _provider(seed, ROOT_README))
    job = _to_deploy_gate(engine, repo)

    assert job.state is JobState.AWAITING_DEPLOY_APPROVAL
    assert [s["path"] for s in job.data.deploy["scripts"]] == [
        "deployment/main.tf",
        "deployment/deploy.sh",
        "deployment/README.md",
    ]
    assert any("README.md" in n for n in job.data.deploy["notes"])  # the person sees it went


def test_an_approved_plan_naming_a_file_devops_may_not_write_is_proposed_again(
    store: JobStore, seeded: Engine, repo: Path
) -> None:
    """A plan approved before proposals were checked would fail at the write on every
    retry; it goes back to DevOps instead, told why."""
    job = _to_deploy_gate(seeded, repo)
    job.data.deploy["scripts"].append({"path": "README.md", "purpose": "the project readme"})
    store.save(job)

    job = seeded.approve(job.id)

    assert job.state is JobState.AWAITING_DEPLOY_APPROVAL
    assert job.worktree_path is not None
    assert not (job.worktree_path / DEPLOY_FOLDER).exists()  # nothing written from it
    again = [r for r in seeded.provider.requests if "propose how this project" in r.prompt][-1]
    assert "The approved plan names README.md" in again.prompt


def test_the_pull_request_mentions_the_deployment(seeded: Engine, repo: Path) -> None:
    from slipwright.roles.devops import draft_description

    job = seeded.approve(_to_deploy_gate(seeded, repo).id)
    draft = draft_description(job)
    assert "## Deployment" in draft
    assert "Target: aws" in draft
    assert "`deployment/deploy.sh`" in draft


def test_the_deployment_can_be_skipped_and_the_pull_request_still_opens(
    seeded: Engine, repo: Path
) -> None:
    """Somebody who deploys by hand, or not at all, has no proposal they would accept;
    rejecting only pays DevOps to propose again. Skipping writes nothing and delivers
    the code on its own."""
    job = _to_deploy_gate(seeded, repo)
    job = seeded.skip_deployment(job.id)

    assert job.state is JobState.DONE
    assert job.data.deploy_skipped is True
    assert job.data.deploy_written == []
    assert job.worktree_path is not None
    assert not (job.worktree_path / DEPLOY_FOLDER).exists(), "nothing was to be written"
    assert job.data.pr_url == "https://example.test/pr/1"
    assert any("skipped the deployment: 3 script(s)" in (t.note or "") for t in job.history)
    # the proposal stays on the record; the pull request does not claim a deployment
    assert (job.data.deploy or {}).get("target") == "aws"
    from slipwright.roles.devops import draft_description

    assert "## Deployment" not in draft_description(job)


def test_skip_deployment_endpoint(client: TestClient, seeded: Engine, repo: Path) -> None:
    job = _to_deploy_gate(seeded, repo)
    resp = client.post(f"/api/jobs/{job.id}/skip-deployment")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["deploy_skipped"] is True
    # it is an answer to this gate only: asking again, or of a job not there, is a 409
    assert client.post(f"/api/jobs/{job.id}/skip-deployment").status_code == 409
    assert client.post("/api/jobs/nope/skip-deployment").status_code == 404


def test_the_deployment_gate_can_be_answered() -> None:
    """The deployment gate had no approve and no reject anywhere.

    `pendingApproval` did not know the state, so the buttons on the development page
    returned nothing; in the pipeline drawer the gate is marked editable, which hid the
    plain buttons on the assumption that an editor would carry its own -- and the
    deployment's editor carries only a save. So the one gate that decides where a thing
    is deployed could not be answered at all.
    """
    from pathlib import Path

    web = Path("web/src")
    actions = (web / "components" / "GateActions.tsx").read_text(encoding="utf-8")
    assert '"awaiting_deploy_approval"' in actions, "the gate must have a name to wait at"

    drawer = (web / "pages" / "PipelineTab.tsx").read_text(encoding="utf-8")
    assert "DeploymentGate" in drawer, "the scripts belong in the drawer that approves them"
    # what the editor carries is not what the server means by "the material is editable"
    assert "EDITOR_APPROVES" in drawer and "!step.editable && (" not in drawer


def test_the_deployment_is_written_in_parts_when_one_answer_will_not_hold_it(
    store: JobStore, worktrees_root: Path, seed: Profile, repo: Path
) -> None:
    """An approved plan can name seven files -- a Dockerfile, two templates, three shell
    scripts and a README. Asked for all of them at once the answer hits the output limit
    and is thrown away, and DevOps was the one role with no way to answer in parts: it
    simply failed, and retrying failed identically."""
    import inspect

    from slipwright.roles import devops

    # the same door the developer and QA have
    params = inspect.signature(devops.write_deployment).parameters
    assert "truncated" in params and "continuation" in params

    engine_src = Path("slipwright/engine.py").read_text(encoding="utf-8")
    write = engine_src[engine_src.index("def _write_deployment") :][:7000]
    assert "continuation=continuation" in write, "the second call must know what is written"
    assert "phase_complete" in write, "and must stop when DevOps says it is done"


def test_a_finished_development_teaches_the_project_brief(seeded: Engine, repo: Path) -> None:
    """A development leaves its work on its own branch and nothing merges it, so the
    project's brief stayed blank however much was built -- and every later development
    then planned knowing nothing about what was already there. The Architect reads what
    now exists and proposes the brief; a person still approves it."""
    from slipwright.schemas.brief import BriefState

    job = seeded.approve(_to_deploy_gate(seeded, repo).id)
    assert job.state is JobState.DONE
    assert job.project_id is not None

    brief = seeded.brief(job.project_id)
    assert brief.items, "nothing was learned from a whole development"
    assert brief.state is BriefState.PROPOSED, "it is proposed, never approved behind your back"
    assert all(i.source == "analysis" for i in brief.items)


def test_what_a_person_has_written_in_the_brief_is_not_overwritten(
    seeded: Engine, repo: Path
) -> None:
    """Once the brief holds items they are somebody's: corrected, deleted, approved.
    A development finishing must not quietly replace them."""
    from slipwright.schemas.brief import BriefItem, BriefState

    project = seeded.create_project(Project(name="demo", repo_path=repo))
    brief = seeded.store.get_brief(project.id)
    brief.items = [BriefItem(title="we deploy on Fridays", source="human")]
    brief.state = BriefState.READY
    seeded.store.save_brief(brief)

    job = seeded.start(seeded.create_job("add a health endpoint", project_id=project.id).id)
    for _ in range(5):  # backlog, plan, test cases, written tests, deployment
        job = seeded.approve(job.id)
    assert job.state is JobState.DONE

    kept = seeded.brief(project.id)
    assert [i.title for i in kept.items] == ["we deploy on Fridays"]
    assert kept.state is BriefState.READY
