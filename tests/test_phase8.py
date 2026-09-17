from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
OPENAPI = ROOT / "schemas" / "openapi.json"
CLIENT = WEB / "src" / "api" / "schema.d.ts"

# --- T8.1 React app skeleton --------------------------------------------------------------


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    return full_engine(store, worktrees_root, seed, full_provider(seed))


def test_web_scaffold_is_wired_for_the_python_package() -> None:
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    for script in ("dev", "build", "lint", "typecheck", "gen:api", "check:api", "format:check"):
        assert script in package["scripts"], script
    for dep in ("react", "react-dom", "react-router-dom", "@tanstack/react-query"):
        assert dep in package["dependencies"], dep
    for dep in ("vite", "typescript", "eslint", "prettier", "openapi-typescript"):
        assert dep in package["devDependencies"], dep
    vite = (WEB / "vite.config.ts").read_text(encoding="utf-8")
    assert "slipwright/api/static" in vite  # build lands inside the package
    assert '"/api"' in vite and "8500" in vite  # dev proxy to the Python server
    tsconfig = json.loads((WEB / "tsconfig.app.json").read_text(encoding="utf-8"))
    assert tsconfig["compilerOptions"]["strict"] is True
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "slipwright/api/static/" in gitignore and "web/node_modules/" in gitignore


def test_generated_api_client_matches_the_committed_openapi() -> None:
    """The header of schema.d.ts names the OpenAPI file it was generated from."""
    assert CLIENT.is_file(), "web/src/api/schema.d.ts is missing; run `npm run gen:api` in web/"
    head = CLIENT.read_text(encoding="utf-8")[:400]
    match = re.search(r"openapi-sha256: ([0-9a-f]{64})", head)
    assert match, "schema.d.ts has no openapi-sha256 header; regenerate with `npm run gen:api`"
    current = hashlib.sha256(OPENAPI.read_bytes()).hexdigest()
    assert match.group(1) == current, (
        "web/src/api/schema.d.ts is stale; run `npm run gen:api` in web/ "
        "(after `uv run python scripts/export_schema.py`)"
    )


def test_spa_is_served_with_fallback(engine: Engine, tmp_path: Path) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Slipwright</title>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (static / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    app = create_app(engine, resume_on_startup=False, require_auth=False, static_dir=static)
    with TestClient(app) as client:
        assert "<title>Slipwright</title>" in client.get("/").text
        assert "<title>Slipwright</title>" in client.get("/projects/abc/board").text  # fallback
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/favicon.svg").text == "<svg/>"
        assert client.get("/api/nope").status_code == 404  # never falls back to the shell
        assert client.get("/api/projects").status_code == 200
        assert client.get("/docs").status_code == 200  # interactive API docs stay public
        assert client.get("/../secret.txt").status_code in (200, 404)  # no traversal


def test_shell_is_public_but_api_is_not(engine: Engine, tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    engine.store.create_user("ada", "pw")
    app = create_app(engine, resume_on_startup=False, static_dir=static)  # auth on
    with TestClient(app) as client:
        assert client.get("/").status_code == 200  # the app shows its own login page
        assert client.get("/projects").status_code == 200
        assert client.get("/api/projects").status_code == 401
        assert client.get("/api/settings/github").status_code == 401
        assert client.get("/healthz").status_code == 200


def test_without_a_build_the_root_explains_how_to_build(engine: Engine, tmp_path: Path) -> None:
    app = create_app(engine, resume_on_startup=False, require_auth=False, static_dir=tmp_path)
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 503
        assert "npm run build" in resp.text
        assert client.get("/api/projects").status_code == 200


# --- T8.2 login and projects list ---------------------------------------------------------


def _src(name: str) -> str:
    return (WEB / "src" / name).read_text(encoding="utf-8")


def test_login_and_projects_pages_use_the_api() -> None:
    login = _src("pages/LoginPage.tsx")
    assert "slipwright user add" in login  # empty state explains how to create the first user
    assert "useAuth" in login and "Navigate" in login  # redirect back after login
    auth = _src("auth/AuthProvider.tsx")
    assert "/api/auth/login" in auth and "/api/auth/logout" in auth and "/api/auth/me" in auth
    assert "RequireAuth" in auth and '"/login"' in auth
    projects = _src("pages/ProjectsPage.tsx")
    for expected in ("useProjects", "useProgress", "pending_approvals", "jobs_running", "Empty"):
        assert expected in projects, expected
    new_project = _src("pages/NewProjectPage.tsx")
    for expected in ("useGitHubRepos", "repo_path", "github_repo", "jira_project_key"):
        assert expected in new_project, expected
    hooks = _src("api/hooks.ts")
    for path in ("/api/projects", "/api/settings/github/repos", "/api/projects/${id}/progress"):
        assert path in hooks, path


# --- T8.3 project page --------------------------------------------------------------------


def test_project_page_has_the_six_tabs_and_lives_on_events() -> None:
    page = _src("pages/ProjectPage.tsx")
    assert '["pipeline", "overview", "board", "developments", "tests", "activity"]' in page
    for expected in (
        "useBoard",
        "useProgress",
        "useActivity",
        "useStartJob",
        "GateActions",  # approve / reject inline on the overview
        "JiraLink",  # jira key on board rows
        "#phase-",  # task rows link to the phase diff on the job page
        "ActivityRow",  # activity items expand to their detail (components/ActivityRow.tsx)
    ):
        assert expected in page, expected
    assert "useTransition" in _src("components/ActivityRow.tsx")
    events = _src("api/events.ts")
    assert "EventSource" in events and "/api/events" in events
    assert "invalidateQueries" in events
    layout = _src("components/Layout.tsx")
    assert "useLiveEvents" in layout  # every page updates live
    detail = _src("components/Detail.tsx")
    assert "Diff" in detail and "looksLikeDiff" in detail


# --- T8.4 job page ------------------------------------------------------------------------


def test_profile_can_be_edited_while_awaiting_approval(engine: Engine, repo: Path) -> None:
    from slipwright.schemas.job import JobState

    job = engine.start(engine.create_job("x", repo).id)
    assert job.state is JobState.AWAITING_BACKLOG_APPROVAL
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        seed = job.profile or engine.seed_for(job)
        assert (
            client.put(f"/api/jobs/{job.id}/profile", json=seed.model_dump(mode="json")).status_code
            == 409
        )
        client.post(f"/api/jobs/{job.id}/approve")  # backlog -> the architect proposes a profile
        job = engine.store.get(job.id)
        assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
        assert job.profile is not None
        edited = job.profile.model_dump(mode="json")
        edited["test_cmd"] = "make test"
        resp = client.put(f"/api/jobs/{job.id}/profile", json=edited)
        assert resp.status_code == 200, resp.text
        assert resp.json()["profile"]["test_cmd"] == "make test"
        edited["roles"].pop("qa")
        assert client.put(f"/api/jobs/{job.id}/profile", json=edited).status_code == 422
        client.post(f"/api/jobs/{job.id}/approve")
        assert (
            client.put(
                f"/api/jobs/{job.id}/profile", json=job.profile.model_dump(mode="json")
            ).status_code
            == 409
        )
        assert engine.store.get(job.id).profile is not None
        assert engine.store.get(job.id).profile.test_cmd == "make test"  # type: ignore[union-attr]


def test_job_page_covers_every_gate_and_the_parity_list() -> None:
    page = _src("pages/JobPage.tsx")
    for expected in (
        "Stepper",
        "ProfileGate",
        "/api/jobs/${job.id}/profile",
        "BacklogGate",
        "ArchitectureGate",
        "BreakdownTree",
        "TestCasesGate",
        "useSetTestCases",
        "WrittenTestsGate",
        "Phases",
        "phase-${g.number}",
        "build gate",
        "Steering",
        "useSendMessage",
        "consumed_by",
        "History",
    ):
        assert expected in page, expected
    assert "Diff" in _src("components/Diff.tsx")
    parity = (WEB / "PARITY.md").read_text(encoding="utf-8")
    rows = [line for line in parity.splitlines() if line.startswith("| ") and "[" in line]
    assert len(rows) >= 12
    assert all("[x]" in r for r in rows), [r for r in rows if "[x]" not in r]


# --- T8.5 test results page ---------------------------------------------------------------


def test_tests_tab_lists_runs_and_scrolls_to_the_failure() -> None:
    tab = _src("pages/TestsTab.tsx")
    for expected in (
        "useTestRuns",
        "useStartTestRun",
        "on the main checkout",  # run target: main checkout or a job's worktree
        "worktree_path",
        "build gate",  # gate runs are listed alongside manual ones
        "any status",  # filters
        "any job",
        "useTestRunOutput",
        "scrollIntoView",  # failing section scrolled into view
        "still running",
    ):
        assert expected in tab, expected
    hooks = _src("api/hooks.ts")
    assert "/api/projects/${projectId}/test-runs" in hooks
    assert "/api/test-runs/${id}/output" in hooks
    events = _src("api/events.ts")
    assert "test_run.state" in events  # rows flip via SSE


# --- T8.6 settings pages ------------------------------------------------------------------


def test_settings_pages_cover_github_jira_agents_and_users() -> None:
    github = _src("pages/settings/GitHubSettingsPage.tsx")
    for expected in ('type="password"', "token_hint", "Test connection", "useTestGitHub", "login"):
        assert expected in github, expected
    jira = _src("pages/settings/JiraSettingsPage.tsx")
    for expected in ("site_url", "issue_types", "useTestJira", "clear_token", "display_name"):
        assert expected in jira, expected
    agents = _src("components/JiraAgentSetup.tsx") + _src("pages/AgentDetailPage.tsx")
    for expected in (
        "agent_email",
        "agent_token",
        "act through the human connection",  # warning when falling back to the human token
        "/api/settings/profile",  # engine default seed as the starting point
        "usePatchProject",  # written into the project's seed profile
        "jira_transitions",
        '"jira"',  # the jira permission toggle per role
    ):
        assert expected in agents, expected
    profile_form = _src("components/ProfileForm.tsx")
    for perm in ("read_files", "write_files", "run_commands", "network", "git_push", "jira"):
        assert f'"{perm}"' in profile_form, perm
    users = _src("pages/settings/UsersSettingsPage.tsx")
    for expected in (
        "useCreateUser",
        "useSetPassword",
        "useIssueToken",
        "useRevokeToken",
        "useDeleteUser",
    ):
        assert expected in users, expected
    job_page = _src("pages/JobPage.tsx")
    assert "jira_keys" in job_page  # jira actions / keys visible on the job page
    activity = _src("components/ActivityRow.tsx")
    assert "jira: {" in activity  # refused/executed agent actions show in the feed


def test_default_profile_endpoint(engine: Engine, seed: Profile) -> None:
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        assert client.get("/api/settings/profile").json() == seed.model_dump(mode="json")


# --- T8.7 retire the server-rendered dashboard --------------------------------------------


def test_legacy_dashboard_is_gone_and_readme_documents_the_flow() -> None:
    assert not (ROOT / "slipwright" / "api" / "ui.py").exists()
    api_src = (ROOT / "slipwright" / "api" / "__init__.py").read_text(encoding="utf-8")
    assert "legacy" not in api_src and "ui_router" not in api_src
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for expected in (
        "npm run build",
        "slipwright user add",
        "Settings → GitHub",
        "New project",
        "New development",
        "Approve the gates",
        "Tests",
        "PR link",
    ):
        assert expected in readme, expected


# --- dashboard and deletions --------------------------------------------------------------


def test_overview_and_job_deletion(engine: Engine, repo: Path) -> None:
    from slipwright.schemas.job import JobState

    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        assert client.get("/api/overview").json()["projects"] == 0
        project = client.post("/api/projects", json={"name": "demo", "repo_path": str(repo)}).json()
        job = client.post(f"/api/projects/{project['id']}/jobs", json={"request": "x"}).json()
        ov = client.get("/api/overview").json()
        assert (ov["projects"], ov["jobs_total"], ov["pending_approvals"]) == (1, 1, 1)
        assert ov["waiting"][0]["job_id"] == job["id"]
        assert ov["recent"][0]["project_id"] == project["id"]
        assert client.get("/api/activity?limit=1").json()[0]["job_id"] == job["id"]

        assert client.delete(f"/api/jobs/{job['id']}").status_code == 409  # still running
        engine.store.update_state(job["id"], JobState.FAILED, note="abandoned")
        worktree = Path(engine.store.get(job["id"]).worktree_path or "")
        assert worktree.is_dir()
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
        assert not worktree.exists()
        assert client.get(f"/api/jobs/{job['id']}").status_code == 404
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 404
        assert client.get("/api/overview").json()["jobs_total"] == 0
