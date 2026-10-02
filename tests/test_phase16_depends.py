"""T16.2: the plan says what each phase needs, before anything is built side by side."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slipwright.roles import architect
from slipwright.roles.results import PlanPhase
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


def _phase(goal: str, files: list[str], needs: list[int] | None) -> PlanPhase:
    return PlanPhase(goal=goal, task_id="t1", files=files, depends_on=needs)


def test_a_phase_depends_only_on_earlier_ones() -> None:
    plan = [_phase("api", ["api.py"], []), _phase("ui", ["ui.tsx"], [2])]
    assert "does not come before it" in str(architect.dependency_problem(plan))
    plan = [_phase("api", ["api.py"], []), _phase("ui", ["ui.tsx"], [1])]
    assert architect.dependency_problem(plan) is None


def test_two_phases_on_one_file_are_never_independent() -> None:
    plan = [
        _phase("theme", ["App.tsx"], []),
        _phase("api", ["api.py"], []),
        _phase("screens", ["./App.tsx"], [2]),
    ]
    problem = architect.dependency_problem(plan)
    assert problem is not None and "phases 1 and 3 both change ./App.tsx" in problem
    # through another phase is enough: 3 needs 2, which needs 1
    plan[1] = _phase("api", ["api.py"], [1])
    assert architect.dependency_problem(plan) is None


def test_an_older_plan_without_dependencies_needs_every_earlier_phase() -> None:
    plan = [_phase("a", ["x"], None), _phase("b", ["x"], None)]
    assert architect.dependency_problem(plan) is None


def _context(request: Any) -> dict[str, Any]:
    text = request.prompt
    body = text[text.index("Context:\n") + len("Context:\n") : text.index("\n\nRespond with")]
    return dict(json.loads(body))


def test_a_plan_whose_dependencies_cannot_be_followed_is_asked_for_again(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=2)
    good = provider.replies[RoleName.ARCHITECT]
    assert isinstance(good, dict)
    bad = {
        **good,
        "phases": [
            {**good["phases"][0], "files": ["OK"], "depends_on": []},
            {**good["phases"][1], "files": ["OK"], "depends_on": []},  # same file, no order
        ],
    }
    answers = [bad, good]
    provider.replies[RoleName.ARCHITECT] = lambda _req: answers.pop(0)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = engine.approve(engine.start(engine.create_job("x", repo).id).id)

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    asked = [r for r in provider.requests if r.role is RoleName.ARCHITECT]
    assert len(asked) == 2
    assert "both change OK" in _context(asked[1])["previous_answer_problem"]


def test_moving_a_phase_last_keeps_what_its_neighbours_depend_on() -> None:
    from slipwright.engine import Engine

    phases = [
        {"goal": "ios app", "domain": "mobile", "platform": "ios", "depends_on": []},
        {"goal": "api", "domain": "backend", "depends_on": []},
        {"goal": "web", "domain": "web", "depends_on": [2]},
    ]

    class Fake:
        data = type("D", (), {"plan": {"phases": phases}, "phase_index": 0})()

    engine = Engine.__new__(Engine)
    engine._phase_buildable = lambda job, p: p.get("platform") is None  # type: ignore[method-assign]
    engine.store = type("S", (), {"save": staticmethod(lambda j: j)})()  # type: ignore[assignment]
    engine._record_gate_note = lambda *a, **k: None  # type: ignore[method-assign]
    job = engine._put_unbuildable_last(Fake())  # type: ignore[arg-type]  # noqa: SLF001
    moved = job.data.plan["phases"]
    assert [p["goal"] for p in moved] == ["api", "web", "ios app"]
    assert moved[1]["depends_on"] == [1]  # web still needs the api, now phase 1
