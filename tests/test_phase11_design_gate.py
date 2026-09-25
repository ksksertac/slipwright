"""T11 — the design gate: the screens are agreed before anything is built against them.

The Designer draws the screens; this is the step where a person says yes to them. Two
things make it its own gate rather than another line in the architecture approval. It is
per screen — eight of nine can be right, and sending one back must not cost the other
eight — and it stops only what actually needs it: a development builds its backend phases
while the screens are still being looked at, and waits at the first web or mobile phase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import EmptyApproval, Engine
from slipwright.pipeline import StepStatus, lane_for
from slipwright.roles import designer
from slipwright.roles.results import ScreenDesign
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, set_plan

MOCK = "<!doctype html><style>body{margin:0}</style><h1>List</h1>"
WEB_MOCK = "<!doctype html><style>.w{width:960px}</style><div class=w><h1>List</h1></div>"
PHONE_MOCK = "<!doctype html><style>.p{width:360px}</style><div class=p><h1>List</h1></div>"


def _screen(screen_id: str, name: str, platform: str = "both") -> dict[str, Any]:
    return {
        "id": screen_id,
        "name": name,
        "platform": platform,
        "purpose": f"do {name}",
        "layout": "a list under a title",
        "states": ["empty"],
        "mock": MOCK,
    }


def _engine(
    store: JobStore,
    worktrees_root: Path,
    seed: Profile,
    domains: list[str],
    screens: list[dict[str, Any]] | None = None,
) -> tuple[Engine, Any]:
    provider = full_provider(seed, phases=len(domains))
    set_plan(
        provider,
        seed,
        [{"goal": f"step {i + 1}", "files": ["OK"], "domain": d} for i, d in enumerate(domains)],
    )
    if screens is not None:
        provider.replies[RoleName.DESIGNER] = lambda _req: {
            "summary": "screens",
            "principles": ["one column"],
            "screens": screens,
        }
    return full_engine(store, worktrees_root, seed, provider), provider


def _to_the_gate(engine: Engine, repo: Path) -> Any:
    job = engine.start(engine.create_job("health", repo).id)
    job = engine.approve(job.id)  # backlog
    return engine.approve(job.id)  # architecture -> the Designer, then the first phase


def test_the_backend_phase_is_built_while_the_screens_wait(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The wait is put where it costs nothing: the backend phase does not need a screen."""
    engine, provider = _engine(store, worktrees_root, seed, ["backend", "web"])
    job = _to_the_gate(engine, repo)

    assert job.state is JobState.AWAITING_DESIGN_APPROVAL
    assert job.data.phase_index == 1  # the backend phase is behind us
    assert any((t.note or "").startswith("backend phase 1/2") for t in job.history)
    # and the web specialist has not been asked to guess anything
    assert [r for r in provider.requests if r.role is RoleName.WEB_UI] == []
    assert lane_for(job).pending_approval == "design"


def test_a_backend_only_plan_never_stops_for_screens(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, ["backend", "backend"])
    job = _to_the_gate(engine, repo)
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert not any(t.to_state is JobState.AWAITING_DESIGN_APPROVAL for t in job.history)


def test_approving_the_last_screen_carries_the_development_on(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    screens = [_screen("s1", "List"), _screen("s2", "Detail")]
    engine, provider = _engine(store, worktrees_root, seed, ["backend", "web"], screens)
    job = _to_the_gate(engine, repo)

    job = engine.review_screen(job.id, "s1", ok=True)
    assert job.state is JobState.AWAITING_DESIGN_APPROVAL  # one still waiting
    assert designer.approved_ids(job) == {"s1"}

    job = engine.review_screen(job.id, "s2", ok=True)
    assert job.state is JobState.AWAITING_TEST_APPROVAL  # the web phase ran
    assert [r for r in provider.requests if r.role is RoleName.WEB_UI]


def test_a_screen_sent_back_is_drawn_again_and_the_others_keep_their_yes(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Rejecting one screen must not spend the agreement already reached on the rest."""
    screens = [_screen("s1", "List"), _screen("s2", "Detail")]
    engine, provider = _engine(store, worktrees_root, seed, ["backend", "web"], screens)
    job = _to_the_gate(engine, repo)

    job = engine.review_screen(job.id, "s1", ok=True)
    job = engine.review_screen(job.id, "s2", ok=False, feedback="the list is too dense")

    # the Designer ran again, and was told which screen and why
    calls = [r for r in provider.requests if r.role is RoleName.DESIGNER]
    assert len(calls) == 2
    assert "the list is too dense" in calls[1].prompt
    # the screen that was never sent back keeps its yes; the redrawn one is waiting again
    assert designer.approved_ids(job) == {"s1"}
    assert [s["id"] for s in designer.pending_screens(job)] == ["s2"]
    assert job.state is JobState.AWAITING_DESIGN_APPROVAL
    assert job.data.design_feedback == {}  # spent on the redraw, not carried forward

    job = engine.review_screen(job.id, "s2", ok=True)
    assert job.state is JobState.AWAITING_TEST_APPROVAL


def test_sending_a_screen_back_needs_a_reason(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, ["backend", "web"], [_screen("s1", "List")])
    job = _to_the_gate(engine, repo)
    with pytest.raises(EmptyApproval, match="what should be different"):
        engine.review_screen(job.id, "s1", ok=False, feedback="   ")


def test_the_gate_card_sits_in_front_of_the_phase_that_waits(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, ["backend", "web"])
    job = _to_the_gate(engine, repo)
    keys = [c.key for c in lane_for(job).steps]
    first = keys.index("phase:1")
    assert keys[first : first + 3] == ["phase:1", "design_gate", "phase:2"]
    gate = {c.key: c for c in lane_for(job).steps}["design_gate"]
    assert gate.gate and gate.status is StepStatus.WAITING and gate.pending == "design"


def test_the_mock_is_served_as_its_own_locked_down_document(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """A mock is written by a model, so it is served with nothing allowed: the frame it is
    drawn in is sandboxed and the response says the same, which is what keeps model output
    from reaching the session it is shown inside."""
    engine, _ = _engine(store, worktrees_root, seed, ["backend", "web"], [_screen("s1", "List")])
    job = _to_the_gate(engine, repo)

    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        review = client.get(f"/api/jobs/{job.id}/design").json()
        assert review["waiting"] is True
        assert [(s["id"], s["approved"], s["has_mock"]) for s in review["screens"]] == [
            ("s1", False, True)
        ]

        page = client.get(f"/api/jobs/{job.id}/design/s1/mock")
        assert page.status_code == 200 and page.text == MOCK
        csp = page.headers["content-security-policy"]
        assert "default-src 'none'" in csp and "sandbox" in csp
        assert "script" not in page.text

        assert client.get(f"/api/jobs/{job.id}/design/nope/mock").status_code == 404
        assert client.post(f"/api/jobs/{job.id}/design/nope", json={"ok": True}).status_code == 404

        sent_back = client.post(
            f"/api/jobs/{job.id}/design/s1", json={"ok": False, "feedback": "too dense"}
        )
        assert sent_back.status_code == 200
        assert client.get(f"/api/jobs/{job.id}/design").json()["screens"][0]["approved"] is False


def test_a_screen_on_both_platforms_is_drawn_once_per_surface(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Web and mobile are looked at one at a time, so each is a document of its own.

    A screen drawn before surfaces existed has a single `mock` and no surfaces, and is
    served whatever it is asked for -- the panel then shows it with no tabs, as it did.
    """
    both = _screen("s1", "List") | {"mock": "", "mocks": {"web": WEB_MOCK, "mobile": PHONE_MOCK}}
    engine, _ = _engine(
        store, worktrees_root, seed, ["backend", "web"], [both, _screen("s2", "Settings")]
    )
    job = _to_the_gate(engine, repo)

    with TestClient(create_app(engine, resume_on_startup=False, require_auth=False)) as client:
        screens = {s["id"]: s for s in client.get(f"/api/jobs/{job.id}/design").json()["screens"]}
        assert screens["s1"]["surfaces"] == ["web", "mobile"]
        assert screens["s1"]["has_mock"] is True
        assert screens["s2"]["surfaces"] == []  # one drawing, so the panel shows no tabs

        at = f"/api/jobs/{job.id}/design/s1/mock"
        assert client.get(at, params={"surface": "web"}).text == WEB_MOCK
        assert client.get(at, params={"surface": "mobile"}).text == PHONE_MOCK
        # asked for nothing in particular, or for a surface it was not drawn for
        assert client.get(at).text == WEB_MOCK
        assert client.get(at, params={"surface": "watch"}).text == WEB_MOCK
        # the single-drawing screen answers the same however it is asked for
        one = f"/api/jobs/{job.id}/design/s2/mock"
        assert client.get(one).text == MOCK
        assert client.get(one, params={"surface": "mobile"}).text == MOCK


def test_a_drawing_that_is_not_a_document_is_dropped_per_surface() -> None:
    """The screen keeps its words and loses only the picture that was not one."""
    screen = ScreenDesign(
        name="List",
        purpose="see the list",
        layout="a list under a title",
        mocks={"web": WEB_MOCK, "mobile": "sorry, I cannot draw that"},
    )
    assert sorted(screen.mocks) == ["web"]


def test_the_design_gate_ui_is_wired_up() -> None:
    from tests.test_phase9_review import WEB

    text = {p.name: p.read_text(encoding="utf-8") for p in (WEB / "src").rglob("*.tsx")}
    assert "DesignGate" in text["PipelineTab.tsx"] and "DesignGate" in text["JobPage.tsx"]
    gate = text["DesignGate.tsx"]
    assert 'sandbox=""' in gate  # the frame a model-written page is drawn in
    assert "design/" in gate and "mock" in gate
    assert '"awaiting_design_approval"' in text["GateActions.tsx"]
