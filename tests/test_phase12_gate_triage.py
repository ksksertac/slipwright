"""The tester reads a failed build gate before anyone starts fixing code.

A red gate says only that two sides of the project disagree; it never says which of them
was wrong. These tests pin that question on QA. A test asserting something nobody agreed
to is QA's own mistake to correct, and the gate runs again without a specialist spending a
fix attempt on it. Anything else is the code's fault, and QA hands the specialist its
reading of the failure instead of a patch. Either way the reason goes into the history, so
the record says which side was wrong and why, not only that something failed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from slipwright.providers import ModelRequest
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName, load_profile
from slipwright.store import JobStore
from tests.pipeline import EXAMPLE, TRUE, full_engine, full_provider

PY = sys.executable
# the gate is green only when the test file says yes: the same one sentence both the
# specialist and QA can be made to disagree about
GATE = (
    f'"{PY}" -c '
    "\"import sys; sys.exit(0 if open('tests/t.txt').read().strip() == 'yes' else 1)\""
)

WRONG_TEST = {
    "summary": "wrote the feature and a test for it",
    "phase_complete": True,
    "changes": [
        {"path": "OK", "content": "yes\n"},
        {"path": "tests/t.txt", "content": "no\n"},
    ],
}


@pytest.fixture
def seed() -> Profile:
    return load_profile(EXAMPLE).model_copy(update={"build_cmd": TRUE, "test_cmd": GATE})


def notes(job: Any) -> list[str]:
    return [t.note or "" for t in job.history]


TRIAGE_NOTES = ("qa: phase ",)


def qa_notes(job: Any) -> list[str]:
    """What the tester said about a failed gate. Each note names its phase, so the Phases
    tab groups it with the gate it is about, and QA's ordinary notes stay out of it."""
    return [n for n in notes(job) if n.startswith(TRIAGE_NOTES)]


def specialist_calls(provider: Any) -> list[ModelRequest]:
    return [r for r in provider.requests if r.role is RoleName.BACKEND]


def _run(engine: Any, repo: Path) -> Any:
    job = engine.start(engine.create_job("x", repo).id)
    return engine.approve(engine.approve(job.id).id)


def test_a_wrong_test_is_the_testers_own_to_correct(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    provider.replies[RoleName.BACKEND] = WRONG_TEST
    provider.discovery["gate_triage"] = {
        "summary": "the test asserts no; the phase's goal and the plan both say yes",
        "gate_verdict": "test_is_wrong",
        "changes": [{"path": "tests/t.txt", "content": "yes\n"}],
    }
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _run(engine, repo)

    # the gate went green on the corrected test, so the phase moved on as if it had passed
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert job.data.build_attempts == 0
    # and the specialist was never called back: a wrong test costs it no fix attempt
    assert len(specialist_calls(provider)) == 1
    assert not [n for n in notes(job) if n.startswith("build gate failed")]

    assert qa_notes(job) == [
        "qa: phase 1: the test was wrong, corrected (1 files) — "
        "the test asserts no; the phase's goal and the plan both say yes"
    ]
    # the correction is on the branch, committed with the phase it belongs to
    assert (Path(job.worktree_path) / "tests" / "t.txt").read_text().strip() == "yes"


def test_when_the_code_is_wrong_the_specialist_is_handed_the_reading_not_a_patch(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    tries: list[int] = []

    def specialist(_req: ModelRequest) -> Any:
        tries.append(1)
        said = "no" if len(tries) == 1 else "yes"
        return {
            "summary": f"try {len(tries)}",
            "phase_complete": True,
            "changes": [
                {"path": "OK", "content": "yes\n"},
                {"path": "tests/t.txt", "content": f"{said}\n"},
            ],
        }

    provider.replies[RoleName.BACKEND] = specialist
    diagnosis = "the test is right: the feature must write yes into tests/t.txt, not no"
    provider.discovery["gate_triage"] = {
        "summary": diagnosis,
        "gate_verdict": "code_is_wrong",
    }
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _run(engine, repo)

    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert qa_notes(job) == [f"qa: phase 1: the code is wrong, not the test — {diagnosis}"]
    # the gate failed the ordinary way and the specialist paid for it
    assert "build gate failed on phase 1 (attempt 1/3)" in notes(job)

    calls = specialist_calls(provider)
    assert len(calls) == 2
    assert "qa_diagnosis" not in calls[0].prompt  # nothing to read before the gate ran
    assert diagnosis in calls[1].prompt  # the fix attempt starts from the tester's reading


def test_a_correction_that_reaches_outside_the_tests_is_refused(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """"The test was wrong" is never a licence to edit the code under test."""
    provider = full_provider(seed, phases=1)
    provider.replies[RoleName.BACKEND] = WRONG_TEST
    provider.discovery["gate_triage"] = {
        "summary": "the feature file is the problem",
        "gate_verdict": "test_is_wrong",
        "changes": [{"path": "OK", "content": "rewritten by qa\n"}],
    }
    engine = full_engine(store, worktrees_root, seed, provider, max_build_attempts=1)
    job = _run(engine, repo)

    assert job.state is JobState.FAILED
    assert qa_notes(job) == [
        "qa: phase 1: test fix refused, it changed OK — not a test file",
        "qa: phase 1: the code is wrong, not the test — the feature file is the problem",
    ]
    # the production file is still the specialist's, untouched
    assert (Path(job.worktree_path) / "OK").read_text().strip() == "yes"


def test_the_tester_cannot_rewrite_the_same_phases_tests_forever(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    tries: list[int] = []
    fixes: list[int] = []

    def specialist(_req: ModelRequest) -> Any:
        tries.append(1)
        return {
            "summary": f"try {len(tries)}",
            "phase_complete": True,
            "changes": [
                {"path": "OK", "content": f"try {len(tries)}\n"},
                {"path": "tests/t.txt", "content": "no\n"},
            ],
        }

    def triage(_req: ModelRequest) -> Any:
        fixes.append(1)
        return {
            "summary": f"rewrite {len(fixes)}",
            "gate_verdict": "test_is_wrong",
            "changes": [{"path": "tests/t.txt", "content": f"still no {len(fixes)}\n"}],
        }

    provider.replies[RoleName.BACKEND] = specialist
    provider.discovery["gate_triage"] = triage
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _run(engine, repo)

    # two rewrites is the whole allowance for this phase; after that the gate fails the
    # ordinary way and the specialist's own three attempts run out
    assert len(fixes) == 2
    assert job.state is JobState.FAILED
    assert job.history[-1].note == "build gate failed 3 times on phase 1"
    assert qa_notes(job) == [
        "qa: phase 1: the test was wrong, corrected (1 files) — rewrite 1",
        "qa: phase 1: the test was wrong, corrected (1 files) — rewrite 2",
    ]
