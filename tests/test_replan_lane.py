"""A re-planned development's lane reads each phase from the plan it belongs to: a phase 2
of an earlier plan passing its gate says nothing about this plan's phase 2."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from slipwright.pipeline import StepStatus, lane_for
from slipwright.schemas.job import Job, JobState, Transition, utcnow


def _job(repo: Path, kept: int) -> Job:
    t0 = utcnow() - timedelta(hours=13)
    job = Job(request="x", repo_path=repo)
    job.state = JobState.DEVELOPING
    step = lambda h, a, b, note: Transition(  # noqa: E731
        from_state=a, to_state=b, at=t0 + timedelta(hours=h), note=note
    )
    D, B, A = JobState.DEVELOPING, JobState.BUILD_GATE, JobState.ARCHITECTURE
    job.history = [
        step(0, B, D, "build gate passed for phase 1/4"),
        step(1, B, D, "build gate passed for phase 2/4"),  # an earlier plan's phase 2
        step(2, D, A, "re-plan from phase 2"),
        step(3, A, JobState.AWAITING_ARCHITECTURE_APPROVAL, "architect: re-planned from phase 2"),
        step(4, JobState.AWAITING_ARCHITECTURE_APPROVAL, D, "approved"),
    ]
    job.data.plan = {
        "kept": kept,
        "phases": [
            {"goal": "one", "task_id": "t1", "depends_on": []},
            {"goal": "two, again", "task_id": "t2", "depends_on": [1]},
            {"goal": "three", "task_id": "t3", "depends_on": [1]},
        ],
    }
    job.data.phase_index = 1
    return job


def test_an_earlier_plans_phase_is_not_this_ones(repo: Path) -> None:
    cards = {c.phase: c for c in lane_for(_job(repo, kept=1)).steps if c.key.startswith("phase:")}
    assert cards[1].status is StepStatus.DONE  # kept: built before the re-plan, and still is
    assert cards[2].status is StepStatus.RUNNING  # this plan's phase 2, being built now
    assert cards[3].status is StepStatus.PENDING


def test_a_new_rounds_test_gate_is_the_one_waiting(repo: Path) -> None:
    """An earlier round approved its test cases and its written tests and went to DevOps;
    this round waits at its test cases. The lane says so, and nothing of the earlier
    round reads as done."""
    t0 = utcnow() - timedelta(hours=20)
    job = Job(request="x", repo_path=repo)
    job.state = JobState.AWAITING_TEST_APPROVAL
    job.data.qa_stage = 1
    job.data.phase_index = 1
    job.data.plan = {"phases": [{"goal": "one", "task_id": "t1", "depends_on": []}]}
    S = JobState
    hops = [
        (S.QA, S.AWAITING_TEST_APPROVAL, "qa: 3 test case(s) proposed"),
        (S.AWAITING_TEST_APPROVAL, S.QA, "approved test cases"),
        (S.QA, S.AWAITING_TEST_APPROVAL, "qa: tests written and green"),
        (S.AWAITING_TEST_APPROVAL, S.DEVOPS, "approved written tests"),
        (S.DEVOPS, S.AWAITING_DEPLOY_APPROVAL, "devops: deployment proposed"),
        (S.AWAITING_DEPLOY_APPROVAL, S.DEVOPS, "approved deployment"),
        (S.DEVOPS, S.ARCHITECTURE, "re-plan"),
        (S.ARCHITECTURE, S.AWAITING_ARCHITECTURE_APPROVAL, "architect: plan ready — 1 phases"),
        (S.AWAITING_ARCHITECTURE_APPROVAL, S.DEVELOPING, "approved"),
        (S.BUILD_GATE, S.QA, "build gate passed for phase 1/1"),
        (S.QA, S.AWAITING_TEST_APPROVAL, "qa: 15 test cases proposed"),
    ]
    job.history = [
        Transition(from_state=a, to_state=b, at=t0 + timedelta(hours=i), note=n)
        for i, (a, b, n) in enumerate(hops)
    ]
    cards = {c.key: c for c in lane_for(job).steps}
    assert cards["test_gate:1"].status is StepStatus.WAITING
    assert cards["qa:2"].status is StepStatus.PENDING
    assert cards["test_gate:2"].status is StepStatus.PENDING
    assert cards["devops"].status is StepStatus.PENDING
