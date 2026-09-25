"""T11 — the Designer: screens decided once, built twice.

The Web and Mobile specialists used to each invent their own answer to "what is this
screen". These tests pin the step that decides it for both: when it runs, what it hands
each specialist, and that a development with no screen in it never sees it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slipwright.engine import Engine
from slipwright.pipeline import StepStatus, lane_for
from slipwright.roles import designer
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.steps import step_detail
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, set_plan


def _engine(
    store: JobStore, worktrees_root: Path, seed: Profile, domains: list[str]
) -> tuple[Engine, Any]:
    provider = full_provider(seed, phases=len(domains))
    set_plan(
        provider,
        seed,
        [{"goal": f"step {i + 1}", "files": ["OK"], "domain": d} for i, d in enumerate(domains)],
    )
    return full_engine(store, worktrees_root, seed, provider), provider


def test_a_plan_with_screens_goes_through_the_designer(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, ["backend", "web"])
    job = engine.start(engine.create_job("health", repo).id)
    job = engine.approve(job.id)  # backlog
    job = engine.approve(job.id)  # architecture -> the Designer

    # the approved plan went to the Designer, and on to the first phase
    assert any(t.to_state is JobState.DESIGN for t in job.history)
    assert job.data.design is not None
    assert [s["name"] for s in job.data.design["screens"]] == ["List"]
    assert job.data.design["principles"] == ["one column"]
    note = next(
        t.note or ""
        for t in job.history
        if t.from_state is JobState.DESIGN and t.to_state is JobState.DEVELOPING
    )
    assert note.startswith("designer: 1 screen(s) designed")


def test_a_backend_only_plan_never_sees_the_designer(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Asking for screens nobody will build wastes a call and invents requirements."""
    engine, _ = _engine(store, worktrees_root, seed, ["backend", "backend"])
    job = engine.start(engine.create_job("health", repo).id)
    job = engine.approve(job.id)  # backlog
    job = engine.approve(job.id)  # architecture -> the Designer

    assert not any(t.to_state is JobState.DESIGN for t in job.history)
    assert job.data.design is None
    assert "design" not in {c.key for c in lane_for(job).steps}


def test_each_specialist_is_handed_only_its_own_screens(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, ["web", "mobile"])
    job = engine.start(engine.create_job("health", repo).id)
    job = engine.approve(job.id)  # backlog
    job = engine.approve(job.id)  # architecture -> the Designer
    job.data.design = {
        "principles": ["one column"],
        "screens": [
            {"name": "W", "platform": "web", "purpose": "p", "layout": "l"},
            {"name": "M", "platform": "mobile", "purpose": "p", "layout": "l"},
            {"name": "B", "platform": "both", "purpose": "p", "layout": "l"},
        ],
    }
    phases = job.data.plan["phases"]

    web = designer.for_phase(job, phases[0])
    assert web is not None and [s["name"] for s in web["screens"]] == ["W", "B"]
    mobile = designer.for_phase(job, phases[1])
    assert mobile is not None and [s["name"] for s in mobile["screens"]] == ["M", "B"]
    # the principles travel with both: they are what makes the two halves one product
    assert web["principles"] == mobile["principles"] == ["one column"]
    # a backend phase has no screens, so it is handed nothing rather than an empty shell
    assert designer.for_phase(job, {"domain": "backend", "task_id": None}) is None


def test_the_designer_writes_no_files(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The design is a decision. A role that cannot write files cannot quietly become a
    second developer, so the permission is the guard rather than the prompt."""
    permissions = seed.roles[RoleName.DESIGNER].permissions
    assert "write_files" not in [p.value for p in permissions]
    assert "run_commands" not in [p.value for p in permissions]


def test_the_lane_shows_the_design_step_and_its_screens(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine, _ = _engine(store, worktrees_root, seed, ["web"])
    job = engine.start(engine.create_job("health", repo).id)
    job = engine.approve(job.id)  # backlog
    job = engine.approve(job.id)  # architecture -> the Designer

    cards = {c.key: c for c in lane_for(job).steps}
    assert "design" in cards
    card = cards["design"]
    assert card.role is RoleName.DESIGNER and card.status is StepStatus.DONE

    detail = step_detail(job, "design")
    assert detail is not None
    groups = {g.key: g for g in detail.groups}
    screen = groups["screens"].items[0]
    assert screen.title == "List" and screen.detail == "see the things"
    assert any(b.value == "both" for b in screen.badges)
    states = next(c for c in screen.children if c.title == "states")
    assert [s.title for s in states.children] == ["empty", "loading"]
    assert [p.title for p in groups["principles"].items] == ["one column"]


def test_the_designer_sits_on_the_edge_both_plan_gates_approve(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """A combined-gate project approves one work list at the architecture gate, and that
    is the same edge the Designer was put on. Both modes must route the same way, and the
    skip must hold for both: a backend-only plan goes straight to the first phase."""
    from slipwright.engine import approval_edges
    from slipwright.schemas.job import Job, JobData

    def where(plan_gate: str, domain: str) -> JobState:
        job = Job(
            request="x",
            repo_path=repo,
            state=JobState.AWAITING_ARCHITECTURE_APPROVAL,
            data=JobData(
                plan={"phases": [{"goal": "g", "domain": domain, "task_id": "t1"}]},
                plan_gate=plan_gate,
            ),
        )
        edges = approval_edges(job)
        assert edges is not None
        return edges[0]

    for plan_gate in ("separate", "combined"):
        assert where(plan_gate, "web") is JobState.DESIGN
        assert where(plan_gate, "mobile") is JobState.DESIGN
        assert where(plan_gate, "backend") is JobState.DEVELOPING


def test_a_rejected_plan_is_redesigned_rather_than_kept(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Rejecting the plan sends it back to the Architect, who rewrites it; the screens
    that follow must be for the plan that was finally approved. Carrying over the design
    drawn for a rejected plan is how a person approves one thing and gets another."""
    engine, provider = _engine(store, worktrees_root, seed, ["web"])
    job = engine.start(engine.create_job("health", repo).id)
    job = engine.approve(job.id)  # backlog
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL

    job = engine.reject(job.id, "split the screen in two")
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL  # the architect rewrote it
    assert job.data.design is None  # nothing was designed for the plan that was refused

    provider.replies[RoleName.DESIGNER] = {
        "summary": "redesigned",
        "principles": ["two columns"],
        "screens": [
            {
                "name": "Rewritten",
                "platform": "web",
                "purpose": "the plan changed",
                "layout": "a list",
                "states": ["empty"],
            }
        ],
    }
    job = engine.approve(job.id)  # the approved plan goes to the Designer

    assert job.data.design is not None
    assert [s["name"] for s in job.data.design["screens"]] == ["Rewritten"]
    assert job.data.design["principles"] == ["two columns"]


def test_the_design_is_not_drawn_twice_for_the_same_plan(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """A resumed job re-runs the state it stopped in, so this state can be entered twice
    for one plan. The second time it steps aside instead of paying for the same screens
    again — recognised by the plan's fingerprint, not by "is there a design"."""
    from slipwright.engine import plan_fingerprint

    engine, _ = _engine(store, worktrees_root, seed, ["web"])
    # stop the process the moment the job enters the state, as a restart would
    engine.handlers.pop(JobState.DESIGN)
    job = engine.start(engine.create_job("health", repo).id)
    job = engine.approve(job.id)  # backlog
    job = engine.approve(job.id)  # architecture
    assert job.state is JobState.DESIGN

    drawn = engine._design(store.get(job.id)).data.design
    assert drawn is not None and drawn["plan_fingerprint"] == plan_fingerprint(job)
    calls = sum(1 for e in store.get(job.id).data.invocation_log if e["role"] == "designer")
    assert calls == 1

    # the same state, entered again with the plan unchanged
    again = store.get(job.id).model_copy(update={"state": JobState.DESIGN})
    after = engine._design(again)

    assert after.data.design == drawn  # the same screens, not redrawn
    assert sum(1 for e in after.data.invocation_log if e["role"] == "designer") == calls
    # the reason is in the history, which is where the panel reads it from. The card
    # itself resolves to the latest visit to the state, so it shows this note only where
    # the state was entered again through a transition (the decision gate); re-running the
    # handler on a job already in the state, as here, leaves the first run's note on it.
    assert any("already match this plan" in (t.note or "") for t in after.history)
