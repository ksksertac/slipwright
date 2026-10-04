"""A red build gate after QA's tests is read before anyone is asked to fix it.

The whole project is built and tested for the first time with every phase in it once QA
has written its tests, so what fails there is as often the code as the tests. It used to
go back to QA every time: QA said its tests were fine -- or had written none -- the same
red came back three times, and the development stopped with nobody having looked at the
code ("qa tests failed the build gate 3 times").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from slipwright.engine import Engine
from slipwright.gates import GateResult
from slipwright.providers import ModelRequest
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.test_phase4 import CASES, _engine, _provider, _requests, _to_test_gate

RED = "$ pytest\nFAILED tests/test_total.py::test_total - AssertionError: 3 != 4\n[test: exit 1]"


def _provider_with(seed: Profile, *, writes: bool, verdict: str = "", reading: str = "") -> Any:
    """QA proposing, then writing tests or none; ``verdict`` is how it reads a red gate."""

    def reply(req: ModelRequest) -> dict[str, Any]:
        if '"stage":1' in req.prompt:
            return {"summary": "proposed", "test_cases": CASES}
        changes = [{"path": "tests/test_total.txt", "content": "total is 4\n"}]
        return {
            "summary": "written" if writes else "the approved cases are already covered",
            "changes": changes if writes else [],
        }

    provider = _provider(seed, reply)
    provider.discovery["gate_triage"] = {"summary": reading, "gate_verdict": verdict}
    return provider


def _red_once(engine: Engine) -> list[int]:
    """The final gate fails the first time, as it would on code no phase's gate tested."""
    real = engine._final_gate
    calls: list[int] = []

    def gate(job: Job) -> GateResult:
        calls.append(1)
        return GateResult(ok=False, output=RED) if len(calls) == 1 else real(job)

    engine._final_gate = gate  # type: ignore[method-assign]
    return calls


def _fixes(provider: Any) -> list[ModelRequest]:
    return [r for r in _requests(provider, RoleName.BACKEND) if '"ci_failure":' in r.prompt]


def test_a_red_gate_with_no_tests_written_goes_to_the_specialist_not_back_to_qa(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider_with(seed, writes=False)
    engine = _engine(store, worktrees_root, seed, provider)
    _red_once(engine)

    job = engine.approve(_to_test_gate(engine, repo).id)

    assert job.state is JobState.AWAITING_TEST_APPROVAL, job.history[-1].note
    (fix,) = _fixes(provider)
    assert "QA wrote no tests this round" in fix.prompt and "3 != 4" in fix.prompt
    assert len(_requests(provider, RoleName.QA)) == 2  # proposed and wrote: never asked again
    notes = [t.note or "" for t in job.history]
    assert any("the build gate is red — QA wrote no tests" in n for n in notes)
    assert any(n.startswith("backend: fixed what the tests found") for n in notes)
    assert "1 fix(es) to the code" in notes[-1]


def test_code_qa_finds_wrong_goes_to_the_specialist_with_qa_reading(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    reading = "total() must add the delivery fee before the discount"
    provider = _provider_with(seed, writes=True, verdict="code_is_wrong", reading=reading)
    engine = _engine(store, worktrees_root, seed, provider)
    _red_once(engine)

    job = engine.approve(_to_test_gate(engine, repo).id)

    assert job.state is JobState.AWAITING_TEST_APPROVAL, job.history[-1].note
    (fix,) = _fixes(provider)
    assert reading in fix.prompt
    assert any(
        f"the code is wrong, not the test — {reading}" in (t.note or "") for t in job.history
    )


def test_a_test_qa_finds_wrong_is_written_again_by_qa(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider_with(
        seed, writes=True, verdict="test_is_wrong", reading="it asserted the old wording"
    )
    engine = _engine(store, worktrees_root, seed, provider)
    _red_once(engine)

    job = engine.approve(_to_test_gate(engine, repo).id)

    assert job.state is JobState.AWAITING_TEST_APPROVAL, job.history[-1].note
    assert _fixes(provider) == []  # nobody touched the code
    writes = [r for r in _requests(provider, RoleName.QA) if '"stage":2' in r.prompt]
    assert len(writes) == 2 and "3 != 4" in writes[1].prompt  # the second one saw the red


def test_a_gate_that_stays_red_still_stops_after_three_attempts(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = _provider_with(seed, writes=False)
    engine = _engine(store, worktrees_root, seed, provider)
    engine._final_gate = lambda job: GateResult(ok=False, output=RED)  # type: ignore[method-assign]
    # a specialist whose every fix is different, so no loop check stops it first
    fixes = iter(range(10))
    provider.replies[RoleName.BACKEND] = lambda req: {
        "summary": "fixed",
        "phase_complete": True,
        "changes": [{"path": "OK", "content": f"yes {next(fixes)}\n"}],
    }

    job = engine.approve(_to_test_gate(engine, repo).id)

    assert job.state is JobState.FAILED
    assert job.history[-1].note == "qa tests failed the build gate 3 times"
    assert len(_fixes(provider)) == 2  # one fix after each of the first two reds
