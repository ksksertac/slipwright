"""T9.10 — what each pipeline step produced, item by item.

The lane cards already say *that* a step ran. These tests pin what ``steps.step_detail``
adds: the list you get when you click one — the backlog tree with its Jira keys, the
architect's decisions and phases, a phase's files and build-gate record, the test cases,
the branch and pull request — each with when it happened and, at a gate, when and by whom
it was approved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from slipwright.api import create_app
from slipwright.engine import Engine
from slipwright.pipeline import StepStatus, lane_for
from slipwright.schemas.job import JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.schemas.project import Project
from slipwright.steps import ItemStatus, step_detail
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, past_design, set_plan


def _engine(store: JobStore, worktrees_root: Path, seed: Profile) -> Engine:
    provider = full_provider(seed, phases=2)
    set_plan(
        provider,
        seed,
        [
            {"goal": "add the endpoint", "files": ["OK"], "domain": "backend"},
            {"goal": "show it", "files": ["OK"], "domain": "web"},
        ],
    )
    return full_engine(store, worktrees_root, seed, provider)


def _run_to_end(engine: Engine, job: Any) -> Any:
    """Start the job and sign off every gate until it stops."""
    job = engine.start(job.id)
    while job.is_awaiting_approval:
        job = engine.approve(job.id)
    return job


def _groups(job: Any, key: str) -> dict[str, Any]:
    detail = step_detail(job, key)
    assert detail is not None, key
    return {g.key: g for g in detail.groups}


def test_backlog_step_lists_the_tree_it_wrote(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = engine.start(engine.create_job("health", repo).id)

    detail = step_detail(job, "backlog")
    assert detail is not None
    assert detail.role is RoleName.PO and detail.status is StepStatus.DONE
    assert detail.summary  # the PO's own paragraph, not the headline note
    groups = {g.key: g for g in detail.groups}
    tree = groups["breakdown"].items
    assert tree and tree[0].kind == "epic"
    stories = tree[0].children
    assert stories and stories[0].kind == "story"
    tasks = stories[0].children
    assert tasks and tasks[0].kind == "task" and tasks[0].title
    # nothing is built yet, and without a Jira project nothing was mirrored
    assert tasks[0].status is ItemStatus.TODO
    assert any(b.label == "not in Jira" for b in tasks[0].badges)
    assert groups["jira"].items[0].title == "Mirrored to Jira"


def test_architecture_step_lists_decisions_setup_and_phases(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = engine.approve(engine.start(engine.create_job("health", repo).id).id)

    groups = _groups(job, "architecture")
    assert [i.title for i in groups["phases"].items] == ["add the endpoint", "show it"]
    phase = groups["phases"].items[0]
    assert any(b.label == "phase" and b.value == "1" for b in phase.badges)
    assert any(b.value == "backend" for b in phase.badges)
    assert [c.title for c in phase.children] == ["OK"]  # the files the plan named
    facts = {i.title for i in groups["setup"].items}
    assert {"Build", "Tests", "Language"} <= facts


def test_a_gate_records_when_and_by_whom_it_was_approved(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = engine.start(engine.create_job("health", repo).id)

    waiting = step_detail(job, "backlog_gate")
    assert waiting is not None
    assert waiting.status is StepStatus.WAITING and waiting.approved_at is None
    assert {g.key for g in waiting.groups} == {"breakdown", "decision"}
    assert waiting.groups[-1].items == []  # nobody has decided yet

    job = engine.approve(job.id)
    signed = step_detail(job, "backlog_gate")
    assert signed is not None
    assert signed.status is StepStatus.DONE
    assert signed.approved_at is not None and signed.approved_by == "you"
    decision = {g.key: g for g in signed.groups}["decision"].items
    assert len(decision) == 1 and decision[0].status is ItemStatus.DONE
    assert decision[0].at == signed.approved_at


def test_a_phase_shows_its_task_its_files_and_its_build_gate(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = engine.create_job("health", repo)
    job = engine.approve(engine.approve(engine.start(job.id).id).id)  # both phases built

    groups = _groups(job, "phase:1")
    assignment = groups["assignment"].items[0]
    assert assignment.title == "add the endpoint"
    assert assignment.status is ItemStatus.DONE
    named = {i.title: i for i in groups["files"].items}
    assert "planned" in named and [c.title for c in named["planned"].children] == ["OK"]
    assert "changed" in named and named["changed"].children  # read out of the phase diff
    events = [i.title for i in groups["events"].items]
    assert any(e.startswith("backend phase 1/2") for e in events)
    assert any(e.startswith("build gate passed for phase 1/2") for e in events)
    assert all(i.at is not None for i in groups["events"].items)


def test_qa_steps_list_the_cases_then_the_files(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = engine.create_job("health", repo)
    # backlog, plan, then the screens the web phase waits for; the cases come after
    job = past_design(engine, engine.approve(engine.approve(engine.start(job.id).id).id))

    cases = _groups(job, "qa:1")["cases"].items
    assert cases and cases[0].kind == "case" and cases[0].title
    assert cases[0].status is ItemStatus.TODO  # not approved yet

    job = engine.approve(job.id)  # tests written
    assert _groups(job, "qa:1")["cases"].items[0].status is ItemStatus.DONE
    written = _groups(job, "qa:2")
    assert "test_files" in written and "run" in written


def test_devops_step_says_where_the_work_went(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    job = _run_to_end(engine, engine.create_job("health", repo))
    assert job.state is JobState.DONE

    delivery = {i.title: i for i in _groups(job, "devops")["delivery"].items}
    assert delivery["Branch"].detail == job.branch
    pr = delivery["Pull request"]
    assert pr.status is ItemStatus.DONE and pr.detail == job.data.pr_url
    assert any(b.label == "pushed" for b in pr.badges)


def test_every_lane_card_has_a_detail_and_an_unknown_key_has_none(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The panel is opened with the key the card carries, so every card must resolve."""
    engine = _engine(store, worktrees_root, seed)
    job = _run_to_end(engine, engine.create_job("health", repo))

    for card in lane_for(job).steps:
        detail = step_detail(job, card.key)
        assert detail is not None and detail.key == card.key
        assert detail.status is card.status
    assert step_detail(job, "no-such-step") is None


def test_the_endpoint_serves_one_step(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = _engine(store, worktrees_root, seed)
    project = engine.create_project(Project(name="demo", repo_path=repo))
    job = engine.start(engine.create_job("health", project_id=project.id).id)
    app = create_app(engine, resume_on_startup=False, require_auth=False)
    with TestClient(app) as client:
        ok = client.get(f"/api/jobs/{job.id}/steps/backlog")
        assert ok.status_code == 200
        body = ok.json()
        assert body["key"] == "backlog" and body["role"] == "po"
        assert body["groups"][0]["label"] == "Epics, stories and tasks"
        assert body["groups"][0]["items"][0]["children"][0]["children"][0]["kind"] == "task"

        assert client.get(f"/api/jobs/{job.id}/steps/nope").status_code == 404
        assert client.get("/api/jobs/missing/steps/backlog").status_code == 404


def test_the_test_cases_can_be_proposed_again_on_a_finished_development(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The "QA: test cases" card used to offer "run the tests again", which runs the test
    command and can never produce the scenarios that card is about. Re-running that step
    goes back to QA stage one, where the list is proposed."""
    engine = _engine(store, worktrees_root, seed)
    job = _run_to_end(engine, engine.create_job("health", repo))
    assert job.state is JobState.DONE

    job = engine.rerun(job.id, "test_cases", run=False)
    assert job.state is JobState.QA
    assert job.data.qa_stage == 1
    assert (job.history[-1].note or "").startswith("re-run by hand: test_cases")

    job = engine._run(job)  # QA proposes, and the gate waits for the person again
    assert job.state is JobState.AWAITING_TEST_APPROVAL
    assert job.data.test_cases
    cases = _groups(job, "qa:1")["cases"].items
    assert cases and cases[0].kind == "case"
