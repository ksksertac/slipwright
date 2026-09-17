from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from slipwright.engine import Engine
from slipwright.jiraactions import ActionRunner, jira_context
from slipwright.providers import ModelRequest
from slipwright.roles.results import JiraAction, PlannerResult
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Permission, Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.fakes import FakeJira
from tests.pipeline import BREAKDOWN, full_engine, full_provider

HUMAN = "ada@example.com"
BOT = "bot@example.com"

# --- T7.5 agents act in Jira --------------------------------------------------------------


def _fake() -> FakeJira:
    jira = FakeJira(email=BOT)
    jira.accounts[HUMAN] = "Ada"
    return jira


def _connect(engine: Engine, jira: FakeJira, *, agent: bool = True) -> None:
    engine.http_transport = jira.transport
    engine.update_jira_settings(
        site_url="https://acme.atlassian.net", email=HUMAN, token="jira_secret"
    )
    if agent:
        engine.update_jira_settings(agent_email=BOT, agent_token="jira_secret")


def _context(req: ModelRequest) -> dict[str, Any]:
    ctx = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    data: dict[str, Any] = json.loads(ctx)
    return data


def _requests(engine: Engine, role: RoleName) -> list[ModelRequest]:
    provider: Any = engine.provider
    return [r for r in provider.requests if r.role is role]


def test_jira_action_schema() -> None:
    JiraAction(action="comment", issue="DEM-1", body="hi")
    JiraAction(action="create_issue", issue_type="Bug", summary="broken")
    with pytest.raises(ValueError, match="needs issue, to"):
        JiraAction(action="transition")
    with pytest.raises(ValueError, match="needs minutes"):
        JiraAction(action="log_work", issue="DEM-1")
    schema = PlannerResult.model_json_schema()
    assert "jira_actions" in schema["properties"]
    assert Permission.JIRA.value == "jira"


def test_example_profile_grants_jira_to_the_right_roles(seed: Profile) -> None:
    granted = {r for r in RoleName if Permission.JIRA in seed.roles[r].permissions}
    assert granted == {
        RoleName.PLANNER,
        RoleName.DEVELOPER,
        RoleName.BACKEND,
        RoleName.WEB_UI,
        RoleName.MOBILE_UI,
        RoleName.QA,
        RoleName.DEVOPS,
    }


def _agentic_provider(seed: Profile) -> Any:
    """Each role returns Jira actions the way its instructions describe."""
    provider = full_provider(seed, phases=2, breakdown=None)
    base_dev = provider.replies[RoleName.DEVELOPER]
    base_analyst = provider.replies[RoleName.ANALYST]

    def developer(req: ModelRequest) -> dict[str, Any]:
        ctx = _context(req)
        reply = dict(base_dev)  # type: ignore[arg-type]
        key = ctx["jira"]["current_task_key"]
        reply["jira_actions"] = [
            {"action": "transition", "issue": key, "to": "In Progress"},
            {
                "action": "comment",
                "issue": key,
                "body": f"wrote OK for phase {ctx['current_phase']['number']}",
            },
            {"action": "log_work", "issue": key, "minutes": 15, "note": "implementation"},
        ]
        return reply

    def qa(req: ModelRequest) -> dict[str, Any]:
        ctx = _context(req)
        story = ctx["jira"]["issues"][1]["key"]  # the only story
        if ctx["stage"] == 1:
            return {
                "summary": "cases",
                "test_cases": [{"name": "smoke", "description": "OK is yes"}],
                "jira_actions": [
                    {
                        "action": "create_issue",
                        "issue_type": "Bug",
                        "summary": "OK file lacks trailing newline",
                        "parent": story,
                    }
                ],
            }
        return {
            "summary": "tests",
            "changes": [{"path": "tests/t.txt", "content": "ok\n"}],
            "jira_actions": [
                {"action": "comment", "issue": "DEM-5", "body": "fixed and covered by tests"},
                {"action": "transition", "issue": "DEM-5", "to": "Done"},
            ],
        }

    def devops(req: ModelRequest) -> dict[str, Any]:
        ctx = _context(req)
        story = ctx["jira"]["issues"][1]["key"]
        return {
            "summary": "scripted devops",
            "pr_title": "Slipwright change",
            "pr_body": "Automated change.",
            "jira_actions": [
                {"action": "comment", "issue": story, "body": "PR opened, CI green"},
                {
                    "action": "link_issues",
                    "issue": story,
                    "target": "DEM-5",
                    "link_type": "Relates",
                },
            ],
        }

    def planner(req: ModelRequest) -> dict[str, Any]:
        assert "jira" in _context(req) and _context(req)["jira"]["issues"] == []  # nothing yet
        return {
            "summary": "2 phases",
            "phases": [{"goal": "step 1", "files": ["OK"]}, {"goal": "step 2", "files": ["OK"]}],
            "jira_actions": [{"action": "comment", "issue": "OTHER-1", "body": "outside"}],
        }

    def analyst(req: ModelRequest) -> dict[str, Any]:
        assert "jira" not in _context(req)  # no permission: no Jira section
        reply = dict(base_analyst)  # type: ignore[arg-type]
        reply["jira_actions"] = [{"action": "comment", "issue": "DEM-1", "body": "sneaky"}]
        return reply

    provider.replies[RoleName.ANALYST] = analyst
    provider.replies[RoleName.PLANNER] = planner
    provider.replies[RoleName.DEVELOPER] = developer
    provider.replies[RoleName.QA] = qa
    provider.replies[RoleName.DEVOPS] = devops
    return provider


def test_agents_act_in_jira_through_the_engine(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    engine = full_engine(store, worktrees_root, seed, _agentic_provider(seed))
    _connect(engine, jira)
    project = engine.create_project(Project(name="demo", repo_path=repo, jira_project_key="DEM"))
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    job = engine.approve(job.id)  # profile: analyst's sneaky action is refused
    refused = [t for t in job.history if (t.note or "").startswith("jira (analyst)")]
    assert len(refused) == 1 and "1 refused" in (refused[0].note or "")
    assert "lacks the jira permission" in (refused[0].detail or "")
    assert jira.calls == []  # nothing executed

    # planner: allowed, but OTHER-1 is outside the project
    refused = [t for t in job.history if (t.note or "").startswith("jira (planner)")]
    assert len(refused) == 1 and "outside project DEM" in (refused[0].detail or "")

    job = engine.approve(job.id)  # plan: engine mirrors DEM-1..5, developer runs twice
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    keys = job.data.jira_keys
    t1, t2 = (keys[t.id] for t in _tasks(job))
    assert jira.comments[t1] == ["wrote OK for phase 1"]
    assert jira.comments[t2] == ["wrote OK for phase 2"]
    assert jira.worklogs[t1] == [{"seconds": 900, "note": "implementation"}]
    dev_notes = [t.note for t in job.history if (t.note or "").startswith("jira (developer)")]
    assert dev_notes == ["jira (developer): 3 done"] * 2
    # the developer saw its own task key and the transitions it may use
    dev_ctx = _context(_requests(engine, RoleName.DEVELOPER)[0])["jira"]
    assert dev_ctx["current_task_key"] == t1 and dev_ctx["project_key"] == "DEM"
    assert dev_ctx["transitions"] == {"todo": "To Do", "in_progress": "In Progress", "done": "Done"}
    assert [i["kind"] for i in dev_ctx["issues"]] == ["epic", "story", "task", "task"]

    # qa stage 1 opened a bug under the story
    assert (
        jira.issues["DEM-5"]["type"] == "Bug"
        and jira.issues["DEM-5"]["parent"] == keys[_story_id(job)]
    )
    job = engine.approve(job.id)  # qa stage 2 closes the bug
    assert jira.statuses["DEM-5"] == "Done"
    assert jira.comments["DEM-5"] == ["fixed and covered by tests"]
    job = engine.approve(job.id)  # devops
    assert job.state is JobState.DONE
    story_key = keys[_story_id(job)]
    assert "PR opened, CI green" in jira.comments[story_key]
    assert jira.links == [{"type": "Relates", "inward": story_key, "outward": "DEM-5"}]

    # everything the agents did went through the bot account
    from base64 import b64encode

    assert all(
        c.startswith(
            ("POST /rest/api/3/issue", "GET /rest/api/3/issue", "POST /rest/api/3/issueLink")
        )
        for c in jira.calls
    )
    assert b64encode(f"{BOT}:jira_secret".encode()).decode()  # (auth checked by the fake)
    assert len(job.data.jira_done) == 3 + 3 + 1 + 2 + 2


def test_actions_are_idempotent_and_queued_during_outages(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1, breakdown=None))
    _connect(engine, jira)
    project = engine.create_project(Project(name="demo", repo_path=repo, jira_project_key="DEM"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)  # mirrored; developer returned no actions
    runner = ActionRunner(engine.jira_client(agent=True), project)
    key = job.data.jira_keys[_tasks(job)[0].id]
    actions = [JiraAction(action="comment", issue=key, body="same thing")]

    first = runner.run(job, RoleName.DEVELOPER, seed, actions)
    second = runner.run(job, RoleName.DEVELOPER, seed, actions)  # a restart replays the result
    assert [o.status for o in first] == ["done"]
    assert [o.status for o in second] == ["skipped"]
    assert jira.comments[key] == ["same thing"]

    jira.down = True
    outage = runner.run(
        job, RoleName.DEVELOPER, seed, [JiraAction(action="comment", issue=key, body="later")]
    )
    assert [o.status for o in outage] == ["queued"]
    assert len(job.data.jira_queue) == 1
    engine.store.save(job)
    jira.down = False
    job = engine._jira_reconcile(engine.store.get(job.id))  # the next transition retries
    assert job.data.jira_queue == []
    assert jira.comments[key] == ["same thing", "later"]
    retry = [t for t in job.history if (t.note or "") == "jira (retry): 1 done"]
    assert len(retry) == 1

    # a role without the permission is refused even if Jira is fine
    denied = runner.run(
        job, RoleName.ANALYST, seed, [JiraAction(action="comment", issue=key, body="no")]
    )
    assert denied[0].status == "refused" and "lacks the jira permission" in denied[0].detail
    assert jira.comments[key] == ["same thing", "later"]


def test_agent_falls_back_to_the_human_connection(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    _connect(engine, jira, agent=False)
    assert engine.jira_client(agent=True).email == HUMAN
    engine.update_jira_settings(agent_email=BOT, agent_token="jira_secret")
    assert engine.jira_client(agent=True).email == BOT
    assert engine.jira_client().email == HUMAN


def test_jira_context_is_only_built_for_permitted_roles(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(
        store, worktrees_root, seed, full_provider(seed, phases=4, breakdown=BREAKDOWN)
    )
    project = engine.create_project(Project(name="demo", repo_path=repo, jira_project_key="DEM"))
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    assert jira_context(job, RoleName.ANALYST, seed, project) is None
    unlinked = Project(name="plain", repo_path=repo)
    assert jira_context(job, RoleName.DEVELOPER, seed, unlinked) is None
    ctx = jira_context(job, RoleName.DEVELOPER, seed, project)
    assert ctx is not None and ctx["issues"] == [] and ctx["current_task_key"] is None


def _tasks(job: Any) -> list[Any]:
    from slipwright.board import job_epics

    return [t for e in job_epics(job) for s in e.stories for t in s.tasks]


def _story_id(job: Any) -> str:
    from slipwright.board import job_epics

    return job_epics(job)[0].stories[0].id
