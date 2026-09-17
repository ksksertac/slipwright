from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.providers import ModelRequest
from slipwright.roles.results import PlanPhase
from slipwright.roles.specialists import DEVELOPER_ROLES, Domain, specialist_for
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, set_plan

# --- T9.1 specialist agents ---------------------------------------------------------------


def test_domains_map_to_specialists() -> None:
    assert specialist_for("backend") is RoleName.BACKEND
    assert specialist_for("web") is RoleName.WEB_UI
    assert specialist_for("mobile") is RoleName.MOBILE_UI
    assert specialist_for("infra") is RoleName.DEVOPS
    assert specialist_for("docs") is RoleName.DEVELOPER
    assert specialist_for(None) is RoleName.DEVELOPER
    assert specialist_for("bogus") is RoleName.DEVELOPER
    assert RoleName.DEVELOPER in DEVELOPER_ROLES and RoleName.QA not in DEVELOPER_ROLES
    assert [d.value for d in Domain] == ["backend", "web", "mobile", "infra", "docs", "general"]


def test_plan_phase_domain_is_validated() -> None:
    assert PlanPhase.model_validate({"goal": "g", "domain": "web"}).domain == "web"
    assert PlanPhase.model_validate({"goal": "g"}).domain == "general"
    with pytest.raises(ValueError):
        PlanPhase.model_validate({"goal": "g", "domain": "ios"})


def _three_domain_provider(seed: Profile) -> Any:
    provider = full_provider(seed, phases=3)
    set_plan(
        provider,
        seed,
        [
            {"goal": "add the endpoint", "files": ["OK"], "domain": "backend"},
            {"goal": "show it on the page", "files": ["OK"], "domain": "web"},
            {"goal": "show it in the app", "files": ["OK"], "domain": "mobile"},
        ],
    )
    for role in DEVELOPER_ROLES:
        provider.replies[role] = {
            "summary": f"done by {role.value}",
            "phase_complete": True,
            "changes": [{"path": "OK", "content": "yes\n"}],
        }
    return provider


def _requests(provider: Any, role: RoleName) -> list[ModelRequest]:
    return [r for r in provider.requests if r.role is role]


def test_each_phase_runs_on_its_specialist_with_the_profile_model(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    data = seed.model_dump(mode="json")
    data["roles"]["backend"]["model"] = "model-for-backend"
    data["roles"]["web_ui"]["model"] = "model-for-web"
    data["roles"]["mobile_ui"]["model"] = "model-for-mobile"
    data["roles"]["web_ui"]["provider"] = "openai"
    routed = Profile.model_validate(data)
    provider = _three_domain_provider(routed)
    engine = full_engine(store, worktrees_root, routed, provider)

    job = engine.start(engine.create_job("health everywhere", repo).id)
    job = engine.approve(job.id)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_TEST_APPROVAL

    for role, model in (
        (RoleName.BACKEND, "model-for-backend"),
        (RoleName.WEB_UI, "model-for-web"),
        (RoleName.MOBILE_UI, "model-for-mobile"),
    ):
        reqs = _requests(provider, role)
        assert len(reqs) == 1, role
        assert reqs[0].model == model
    assert _requests(provider, RoleName.WEB_UI)[0].provider == "openai"
    assert _requests(provider, RoleName.DEVELOPER) == []  # no general phase: never invoked
    assert "WEB UI specialist" in _requests(provider, RoleName.WEB_UI)[0].prompt
    assert "BACKEND specialist" in _requests(provider, RoleName.BACKEND)[0].prompt

    notes = [t.note or "" for t in job.history]
    assert any(n.startswith("backend phase 1/3") for n in notes)
    assert any(n.startswith("web_ui phase 2/3") for n in notes)
    assert any(n.startswith("mobile_ui phase 3/3") for n in notes)


def test_ci_fix_goes_to_the_specialist_of_the_last_phase(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    from slipwright.githost import CiState, CiStatus

    class RedOnceHost:
        def __init__(self) -> None:
            self.polls = 0

        def push(self, worktree: Path, branch: str) -> None:
            pass

        def open_pr(self, worktree: Path, branch: str, title: str, body: str) -> str:
            return "https://example.test/pr/1"

        def ci_status(self, worktree: Path, branch: str, pr_url: str) -> CiStatus:
            self.polls += 1
            if self.polls == 1:
                return CiStatus(CiState.FAILURE, log="boom", summary="ci: failure")
            return CiStatus(CiState.SUCCESS, summary="ci: success")

    provider = _three_domain_provider(seed)
    engine = full_engine(store, worktrees_root, seed, provider, git_host=RedOnceHost())
    job = engine.start(engine.create_job("x", repo).id)
    for _ in range(4):
        job = engine.approve(job.id)
    assert job.state is JobState.DONE
    mobile = _requests(provider, RoleName.MOBILE_UI)
    assert len(mobile) == 2  # the phase, then the CI fix
    assert "ci_failure" in mobile[1].prompt


def test_agents_endpoint_and_activity_filter(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, _three_domain_provider(seed))
    job = engine.start(engine.create_job("x", repo).id)
    job = engine.approve(job.id)
    engine.approve(job.id)
    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        agents = client.get("/api/agents").json()
        assert [a["role"] for a in agents] == [r.value for r in RoleName]
        by_role = {a["role"]: a for a in agents}
        assert by_role["backend"]["label"] == "Backend"
        assert by_role["backend"]["invocations"] == 1 and by_role["backend"]["last_used"]
        assert (
            by_role["developer"]["invocations"] == 0 and by_role["developer"]["last_used"] is None
        )
        assert by_role["qa"]["label"] == "QA" and by_role["qa"]["standards_domain"] == "testing"
        assert by_role["architect"]["standards_domain"] == "architecture"
        assert by_role["web_ui"]["model"] == seed.roles[RoleName.WEB_UI].model
        assert "jira" in by_role["backend"]["permissions"]

        mine = client.get("/api/activity?role=web_ui").json()
        assert [i["kind"] for i in mine] == ["role", "standards"]  # newest first
        assert mine[0]["title"].startswith("web_ui phase 2/3")
        assert mine[1]["title"].startswith("standards (web_ui phase 2):")
        assert client.get("/api/activity?role=nope").status_code == 422


def test_agents_ui_has_cards_and_detail_tabs() -> None:
    web = Path(__file__).resolve().parent.parent / "web" / "src"
    cards = (web / "pages" / "AgentsPage.tsx").read_text(encoding="utf-8")
    for expected in (
        "useAgents",
        "AgentCard",
        "/agents/${a.role}",
        "invocations",
        "JiraAgentAccount",
    ):
        assert expected in cards, expected
    detail = (web / "pages" / "AgentDetailPage.tsx").read_text(encoding="utf-8")
    for expected in (
        '["setup", "standards", "activity"]',
        "usePatchProject",
        "useActivity_all",
        "AgentStandardsTab",
    ):
        assert expected in detail, expected
    job_page = (web / "pages" / "JobPage.tsx").read_text(encoding="utf-8")
    assert "DomainBadge" in job_page
