from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.board import job_epics
from slipwright.engine import Engine
from slipwright.jira import JiraClient, JiraError, adf
from slipwright.jirasync import JiraSync
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.store import JobStore
from tests.fakes import FakeJira
from tests.pipeline import BREAKDOWN, FALSE, full_engine, full_provider

HUMAN = "ada@example.com"

# --- T7.4 Jira connection and issue sync --------------------------------------------------


def _fake() -> FakeJira:
    jira = FakeJira(email="bot@example.com")
    jira.accounts[HUMAN] = "Ada"
    return jira


def _connect(engine: Engine, jira: FakeJira) -> None:
    engine.http_transport = jira.transport
    engine.update_jira_settings(
        site_url="https://acme.atlassian.net/", email=HUMAN, token="jira_secret"
    )


def test_jira_client_against_fake() -> None:
    jira = _fake()
    client = JiraClient(
        "https://acme.atlassian.net", HUMAN, "jira_secret", transport=jira.transport
    )
    assert client.myself().display_name == "Ada"
    assert [p.key for p in client.list_projects()] == ["DEM"]

    epic = client.create_issue("DEM", "Epic", "Health", "why\nbecause")
    story = client.create_issue("DEM", "Story", "Probe", parent_key=epic)
    assert (epic, story) == ("DEM-1", "DEM-2")
    assert jira.issues[story]["parent"] == epic
    assert jira.issues[epic]["description"] == adf("why\nbecause")
    assert [t.name for t in client.transitions(epic)] == ["To Do", "In Progress", "Done"]
    assert client.transition(epic, "in progress") is True  # case-insensitive
    assert client.get_status(epic) == "In Progress"
    assert client.transition(epic, "Blocked") is False  # unknown: reported, not raised
    client.comment(epic, "hello")
    client.log_work(epic, 30, "worked")
    client.link(story, epic, "Blocks")
    assert jira.comments[epic] == ["hello"]
    assert jira.worklogs[epic] == [{"seconds": 1800, "note": "worked"}]
    assert jira.links == [{"type": "Blocks", "inward": story, "outward": epic}]

    with pytest.raises(JiraError, match="401"):
        JiraClient("https://acme.atlassian.net", HUMAN, "wrong", transport=jira.transport).myself()
    with pytest.raises(JiraError, match="project"):
        client.create_issue("OTHER", "Task", "x")
    with pytest.raises(JiraError, match="not configured"):
        JiraClient("", "", "")
    jira.down = True
    with pytest.raises(JiraError, match="request failed"):
        client.myself()


def _project(engine: Engine, repo: Path, **kw: object) -> Project:
    return engine.create_project(Project(name="demo", repo_path=repo, jira_project_key="DEM", **kw))


def test_backlog_approval_mirrors_the_breakdown_and_tracks_status(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    engine = full_engine(
        store, worktrees_root, seed, full_provider(seed, phases=4, breakdown=BREAKDOWN)
    )
    _connect(engine, jira)
    project = _project(engine, repo)
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    assert jira.issues == {}  # nothing until the backlog is approved
    job = engine.approve(job.id)  # backlog approved: the tree is mirrored, all To Do
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    assert len(jira.issues) == 9 and set(jira.statuses.values()) == {"To Do"}
    job = engine.approve(job.id)  # architecture -> development -> qa gate
    assert job.state is JobState.AWAITING_TEST_APPROVAL

    # hierarchy: 2 epics, 3 stories, 4 tasks with parents set
    kinds = {k: v["type"] for k, v in jira.issues.items()}
    assert (
        sorted(kinds.values())
        == ["Epic", "Epic", "Story", "Story", "Story", "Subtask"] + ["Subtask"] * 3
    )
    keys = job.data.jira_keys
    assert keys["e1"] == "DEM-1" and keys["s1"] == "DEM-2" and keys["t1"] == "DEM-3"
    assert jira.issues[keys["s1"]]["parent"] == keys["e1"]
    assert jira.issues[keys["t1"]]["parent"] == keys["s1"]
    assert jira.issues[keys["t2"]]["parent"] == keys["s1"]
    assert jira.issues[keys["s3"]]["parent"] == keys["e2"]
    assert "Created by Slipwright job" in _text(jira.issues[keys["t1"]]["description"])

    # every task, story and epic ended up Done; the board shows the keys
    assert all(jira.statuses[keys[i]] == "Done" for i in ("t1", "t2", "t3", "t4", "s1", "e1"))
    board = job_epics(job)
    assert board[0].jira_key == "DEM-1" and board[0].stories[0].tasks[0].jira_key == "DEM-3"
    notes = [t.note for t in job.history if (t.note or "").startswith("jira:")]
    assert notes and all(n.endswith("update(s)") for n in notes)
    details = "\n".join(t.detail or "" for t in job.history if (t.note or "").startswith("jira:"))
    assert "created DEM-1 (epic) Health endpoint" in details
    assert "DEM-3 -> In Progress" in details

    calls_before = len(jira.calls)
    job = engine.approve(job.id)  # tests written
    job = engine.approve(job.id)  # devops -> done
    assert job.state is JobState.DONE
    pr = "https://example.test/pr/1"
    assert all(pr in "".join(jira.comments.get(k, [])) for k in keys.values())
    assert "pr" in job.data.jira_marks
    assert len(jira.calls) > calls_before

    # idempotent: reconciling again does nothing
    calls_before = len(jira.calls)
    engine._jira_reconcile(job)
    assert len(jira.calls) == calls_before
    assert len(jira.issues) == 9


def test_failure_comments_on_the_failing_task(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    broken = seed.model_copy(update={"test_cmd": FALSE})
    engine = full_engine(store, worktrees_root, broken, full_provider(broken, phases=2))
    _connect(engine, jira)
    project = _project(engine, repo, jira_transitions={"failed": "Blocked"})
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert job.state is JobState.FAILED
    task_key = job.data.jira_keys[_task_ids(job)[0]]
    assert any("failed here" in c for c in jira.comments[task_key])
    assert any("exit 1" in c for c in jira.comments[task_key])  # build output attached
    assert jira.statuses[task_key] == "In Progress"  # 'Blocked' is unknown: logged, not fatal
    detail = "\n".join(t.detail or "" for t in job.history if (t.note or "").startswith("jira:"))
    assert "no transition named 'Blocked'" in detail
    assert f"fail:{_task_ids(job)[0]}" in job.data.jira_marks
    assert jira.comments.get(job.data.jira_keys[_task_ids(job)[1]], []) == []


def test_jira_outage_never_blocks_the_job_and_is_retried(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    jira.down = True
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    _connect(engine, jira)
    project = _project(engine, repo)
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert job.state is JobState.DONE  # Jira down the whole time
    assert job.data.jira_last_error is not None and "down" in job.data.jira_last_error
    assert job.data.jira_keys == {}
    assert any((t.note or "") == "jira: sync failed, will retry" for t in job.history)

    jira.down = False
    job = engine.resume(job.id)  # any later transition/resume retries the sync
    assert job.data.jira_last_error is None
    assert len(job.data.jira_keys) == 3
    assert all(s == "Done" for s in jira.statuses.values())
    assert "pr" in job.data.jira_marks


def test_sync_is_skipped_without_a_key_or_a_connection(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    engine.http_transport = jira.transport
    unlinked = engine.create_project(Project(name="plain", repo_path=repo))
    job = engine.start(engine.create_job("x", project_id=unlinked.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert jira.calls == [] and job.data.jira_keys == {}
    linked = _project(engine, repo)  # key but no connection configured
    job = engine.start(engine.create_job("x", project_id=linked.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert jira.calls == [] and job.data.jira_keys == {}
    assert not any((t.note or "").startswith("jira") for t in job.history)


def test_jira_sync_unit_reconcile_is_idempotent(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    jira = _fake()
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    project = _project(engine, repo)
    job = engine.start(engine.create_job("x", project_id=project.id).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    client = JiraClient(
        "https://acme.atlassian.net", HUMAN, "jira_secret", transport=jira.transport
    )
    sync = JiraSync(client, project, {"epic": "Epic", "story": "Story", "task": "Subtask"})
    first = sync.reconcile(job)
    assert first.changed and first.error is None and len(first.notes) == 6
    second = sync.reconcile(job)
    assert not second.changed and second.notes == []


def _text(description: object) -> str:
    from tests.fakes import _adf_text

    return _adf_text(description)


def _task_ids(job: object) -> list[str]:
    from slipwright.schemas.job import Job

    assert isinstance(job, Job)
    return [t.id for e in job_epics(job) for s in e.stories for t in s.tasks]


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as c:
        yield c


def test_jira_settings_endpoints(client: TestClient, engine: Engine) -> None:
    jira = _fake()
    engine.http_transport = jira.transport
    initial = client.get("/api/settings/jira").json()
    assert initial["token_set"] is False and initial["issue_types"]["task"] == "Subtask"
    assert client.post("/api/settings/jira/test").status_code == 400
    assert client.get("/api/settings/jira/projects").status_code == 400

    resp = client.put(
        "/api/settings/jira",
        json={
            "site_url": "https://acme.atlassian.net/",
            "email": HUMAN,
            "token": "jira_secret",
            "issue_types": {"task": "Sub-task", "bogus": "x"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_url"] == "https://acme.atlassian.net"
    assert body["token_set"] and body["token_hint"] == "…cret" and "token" not in body
    assert body["issue_types"] == {
        "epic": "Epic",
        "story": "Story",
        "task": "Sub-task",
        "bug": "Bug",
    }
    assert body["agent_token_set"] is False

    tested = client.post("/api/settings/jira/test").json()
    assert tested["account"]["display_name"] == "Ada"
    assert tested["agent_account"] is None
    assert [p["key"] for p in tested["projects"]] == ["DEM"]
    assert [p["key"] for p in client.get("/api/settings/jira/projects").json()] == ["DEM"]

    resp = client.put(
        "/api/settings/jira", json={"agent_email": "bot@example.com", "agent_token": "jira_secret"}
    )
    assert resp.json()["agent_token_set"] is True and resp.json()["token_set"] is True
    tested = client.post("/api/settings/jira/test").json()
    assert tested["agent_account"]["display_name"] == "Slipwright Bot"

    client.put("/api/settings/jira", json={"token": "bad"})
    assert client.post("/api/settings/jira/test").status_code == 502
    resp = client.put("/api/settings/jira", json={"clear_token": True, "clear_agent_token": True})
    assert resp.json()["token_set"] is False and resp.json()["agent_token_set"] is False
