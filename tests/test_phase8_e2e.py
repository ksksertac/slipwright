"""Definition of done for Phases 6–8, driven the way the browser drives the API.

No CLI, no direct engine calls after setup: log in, connect GitHub and Jira, create a
project from a (fake) GitHub repository, start a development, approve the profile and
plan, watch the board fill in task by task, run the tests, read the results and see the
PR link — with Jira mirroring the tree and the agents acting under the bot account.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.providers import ModelRequest
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.fakes import FakeGitHub, FakeJira
from tests.pipeline import BREAKDOWN, full_engine, full_provider

HUMAN = "ada@example.com"
BOT = "bot@example.com"


class Session:
    """A browser: a cookie jar and JSON calls, asserting success like the app's client."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def call(self, method: str, path: str, body: Any = None) -> Any:
        resp = self.client.request(method, path, json=body)
        assert resp.status_code < 400, f"{method} {path}: {resp.status_code} {resp.text}"
        return resp.json() if resp.content else None


class MixedTransport:
    """Routes GitHub and Jira traffic to their fakes by host."""

    def __init__(self, github: FakeGitHub, jira: FakeJira) -> None:
        self.github = github
        self.jira = jira

    def transport(self) -> Any:
        import httpx

        def handler(request: httpx.Request) -> httpx.Response:
            if "github" in request.url.host:
                return self.github.handler(request)
            return self.jira.handler(request)

        return httpx.MockTransport(handler)


def _agentic(seed: Profile) -> Any:
    provider = full_provider(seed, phases=4, breakdown=BREAKDOWN)
    base_dev = provider.replies[RoleName.BACKEND]

    def developer(req: ModelRequest) -> dict[str, Any]:
        import json

        ctx = json.loads(req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0])
        reply = dict(base_dev)  # type: ignore[arg-type]
        key = ctx.get("jira", {}).get("current_task_key")
        if key:
            reply["jira_actions"] = [
                {"action": "comment", "issue": key, "body": "implemented by the developer agent"}
            ]
        return reply

    provider.replies[RoleName.BACKEND] = developer
    return provider


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, _agentic(seed))


@pytest.fixture
def browser(engine: Engine) -> Iterator[Session]:
    engine.store.create_user("ada", "pw")  # `slipwright user add ada` on the server
    with TestClient(create_app(engine, resume_on_startup=False)) as client:  # auth on
        yield Session(client)


def test_a_new_user_ships_a_change_from_the_browser_alone(
    browser: Session, engine: Engine, repo: Path
) -> None:
    github, jira = FakeGitHub(), FakeJira(email=BOT)
    jira.accounts[HUMAN] = "Ada"
    engine.http_transport = MixedTransport(github, jira).transport()
    bare = repo.parent / "octocat-demo.git"
    subprocess.run(["git", "clone", "--bare", "-q", str(repo), str(bare)], check=True)

    # log in
    assert browser.client.get("/api/auth/me").status_code == 401
    me = browser.call("POST", "/api/auth/login", {"username": "ada", "password": "pw"})
    assert me["is_admin"] is True

    # connect GitHub and Jira, with a separate agent account
    browser.call("PUT", "/api/settings/github", {"token": "ghp_secret", "owner": "octocat"})
    assert browser.call("POST", "/api/settings/github/test")["login"] == "octocat"
    browser.call(
        "PUT",
        "/api/settings/jira",
        {
            "site_url": "https://acme.atlassian.net",
            "email": HUMAN,
            "token": "jira_secret",
            "agent_email": BOT,
            "agent_token": "jira_secret",
        },
    )
    jira_test = browser.call("POST", "/api/settings/jira/test")
    assert jira_test["agent_account"]["display_name"] == "Slipwright Bot"

    # create a project from a GitHub repository (cloned through the token) linked to Jira
    repos = browser.call("GET", "/api/settings/github/repos")
    assert repos[0]["full_name"] == "octocat/demo"
    project = browser.call(
        "POST",
        "/api/projects",
        {
            "name": "demo",
            "github_repo": "octocat/demo",
            "clone_url": str(bare),  # the fake GitHub has no git server: clone locally
            "jira_project_key": browser.call("GET", "/api/settings/jira/projects")[0]["key"],
        },
    )
    assert Path(project["repo_path"]).is_dir()
    assert browser.call("GET", "/api/projects")[0]["id"] == project["id"]

    # start a development: the PO's backlog waits for approval, the board is still empty
    job = browser.call("POST", f"/api/projects/{project['id']}/jobs", {"request": "health"})
    job = browser.call("GET", f"/api/jobs/{job['id']}")
    assert job["state"] == "awaiting_backlog_approval"
    assert browser.call("GET", f"/api/projects/{project['id']}/board")["epics"] == []
    browser.call("POST", f"/api/jobs/{job['id']}/approve")  # backlog -> architecture
    job = browser.call("GET", f"/api/jobs/{job['id']}")
    assert job["state"] == "awaiting_architecture_approval"
    board = browser.call("GET", f"/api/projects/{project['id']}/board")
    assert board["tasks_total"] == 4 and board["tasks_done"] == 0  # mirrored, nothing built
    profile = job["profile"]  # the architect's proposal; edit it (a no-op here) and approve
    browser.call("PUT", f"/api/jobs/{job['id']}/profile", profile)

    # approve the plan: the board fills in task by task (observed through the event stream)
    seen: list[str] = []

    def watch() -> None:
        with browser.client.stream(
            "GET", f"/api/events?project_id={project['id']}&limit=40&keepalive_s=0.2"
        ) as resp:
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    seen.append(line[7:])

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    browser.call("POST", f"/api/jobs/{job['id']}/approve")
    watcher.join(timeout=30)
    assert "job.state" in seen and "activity" in seen and "test_run.state" in seen
    board = browser.call("GET", f"/api/projects/{project['id']}/board")
    assert (board["tasks_done"], board["tasks_total"]) == (4, 4)
    assert [e["title"] for e in board["epics"]] == ["Health endpoint", "Documentation"]
    assert all(t["jira_key"] for e in board["epics"] for s in e["stories"] for t in s["tasks"])
    progress = browser.call("GET", f"/api/projects/{project['id']}/progress")
    assert progress["pending_approvals"] == 1  # test cases

    # run the tests on demand and read the result
    run = browser.call("POST", f"/api/projects/{project['id']}/test-runs", {"job_id": job["id"]})
    runs = browser.call("GET", f"/api/projects/{project['id']}/test-runs")
    mine = next(r for r in runs if r["id"] == run["id"])
    assert mine["status"] == "passed" and mine["source"] == "manual"
    assert any(r["source"] == "gate" for r in runs)
    output = browser.client.get(f"/api/test-runs/{run['id']}/output").text
    assert output.startswith("$ ")

    # approve the test cases and the written tests; see the PR link
    browser.call("POST", f"/api/jobs/{job['id']}/approve")
    browser.call("POST", f"/api/jobs/{job['id']}/approve")
    job = browser.call("GET", f"/api/jobs/{job['id']}")
    assert job["state"] == "done"
    assert job["data"]["pr_url"] == "https://example.test/pr/1"
    feed = browser.call("GET", f"/api/projects/{project['id']}/activity")
    assert feed[0]["kind"] == "done" or feed[1]["kind"] == "done"

    # Jira: the tree exists, everything is Done, the PR is commented, and the agents'
    # comments went in under the bot account (the fake authenticates it separately)
    kinds = sorted(v["type"] for v in jira.issues.values())
    assert kinds == [
        "Epic",
        "Epic",
        "Story",
        "Story",
        "Story",
        "Subtask",
        "Subtask",
        "Subtask",
        "Subtask",
    ]
    assert all(s == "Done" for s in jira.statuses.values())
    task_keys = [t["jira_key"] for e in board["epics"] for s in e["stories"] for t in s["tasks"]]
    for key in task_keys:
        comments = jira.comments.get(key, [])
        assert "implemented by the developer agent" in comments
        assert any("Pull request" in c for c in comments)
    dev_notes = [
        t["note"] for t in job["history"] if (t["note"] or "").startswith("jira (backend)")
    ]
    assert dev_notes == ["jira (backend): 1 done"] * 4

    # logout ends the session
    browser.client.post("/api/auth/logout")
    assert browser.client.get("/api/auth/me").status_code == 401


def test_two_developments_run_concurrently_and_share_the_board(
    browser: Session, engine: Engine, repo: Path
) -> None:
    browser.call("POST", "/api/auth/login", {"username": "ada", "password": "pw"})
    project = browser.call("POST", "/api/projects", {"name": "demo", "repo_path": str(repo)})
    ids = [
        browser.call("POST", f"/api/projects/{project['id']}/jobs", {"request": r})["id"]
        for r in ("first", "second")
    ]
    for job_id in ids:  # both wait at the profile gate
        browser.call("POST", f"/api/jobs/{job_id}/approve")

    # approve both plans at once; TestClient runs each background task to completion, so the
    # engine itself runs the two jobs back to back — the concurrency guarantee (separate
    # worktrees, ports and locks) is proven in tests/test_phase5.py; here the board merges them
    threads = [
        threading.Thread(target=lambda j=job_id: browser.call("POST", f"/api/jobs/{j}/approve"))
        for job_id in ids
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    board = browser.call("GET", f"/api/projects/{project['id']}/board")
    assert {e["job_id"] for e in board["epics"]} == set(ids)
    assert (board["tasks_done"], board["tasks_total"]) == (8, 8)
    jobs = browser.call("GET", f"/api/projects/{project['id']}/jobs")
    assert {j["state"] for j in jobs} == {"awaiting_test_approval"}
    assert len({j["worktree_path"] for j in jobs}) == 2 and len({j["port"] for j in jobs}) == 2
