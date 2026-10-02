"""Writing to the agent on a step: asking it, telling it, and having the plan made again.

A person looking at phase 8 asks the mobile specialist what it is doing and reads its
answer; when the answer shows they want something done differently, they either tell the
specialist (read by its next call on that phase) or have the plan made again from there.
None of it may lose a word, move the development by itself, or spend a call the person
did not ask for.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from slipwright.engine import Engine, NothingToAsk
from slipwright.providers import ModelRequest
from slipwright.providers.scripted import ScriptedProvider
from slipwright.roles.specialists import DEVELOPER_ROLES
from slipwright.schemas.job import InboxMessage, Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider, full_seed, replan_aware

ASKED = "A person is following this development"


@pytest.fixture
def seed() -> Profile:
    return full_seed()


def _context(req: ModelRequest) -> dict[str, Any]:
    ctx = req.prompt.split("Context:\n", 1)[1].rsplit("\n\nRespond with", 1)[0]
    data: dict[str, Any] = json.loads(ctx)
    return data


def _answers(
    provider: ScriptedProvider,
    role: RoleName,
    answer: dict[str, Any],
    work: Callable[[ModelRequest], Any] | None = None,
) -> None:
    """``role`` answers a question with ``answer`` and does its own work as scripted."""
    own = provider.replies[role]

    def reply(req: ModelRequest) -> Any:
        if ASKED in req.prompt:
            return answer
        if work is not None:
            return work(req)
        return own(req) if callable(own) else own

    provider.replies[role] = reply


def _developing(engine: Engine, repo: Path) -> Job:
    """A development whose plan waits at its gate: nothing is built yet."""
    job = engine.create_job("count the visitors", repo)
    job = engine.start(job.id)
    if job.state is JobState.AWAITING_BACKLOG_APPROVAL:
        job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    return job


# --- what is said is never lost --------------------------------------------------------


def test_a_message_sent_while_a_phase_runs_is_not_lost(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The run saves the job from the copy it read when the step began. A message sent
    since then used to live in that same row and was saved over."""
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    job = _developing(engine, repo)
    held_by_the_run = store.get(job.id)

    engine.message(job.id, "keep the counter in memory")
    held_by_the_run.data.cost_usd = 0.5  # the run writes what it was doing anyway
    store.save(held_by_the_run)

    inbox = store.get(job.id).data.inbox
    assert [m.text for m in inbox] == ["keep the counter in memory"]
    assert inbox[0].pending
    assert store.get(job.id).data.cost_usd == 0.5


def test_an_instruction_for_one_agent_is_left_for_that_agent(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    engine.message(job.id, "name the test after the counter", role=RoleName.QA.value)

    engine.approve(job.id)  # the phase is built, then QA proposes its cases

    builder = [r for r in provider.requests if r.role in DEVELOPER_ROLES]
    assert builder and "messages_from_human" not in _context(builder[0])
    qa = [r for r in provider.requests if r.role is RoleName.QA]
    told = [r for r in qa if "messages_from_human" in _context(r)]
    assert [_context(r)["messages_from_human"] for r in told] == [
        ["name the test after the counter"]
    ]
    (read,) = store.get(job.id).data.inbox
    assert read.consumed_by == "qa"


def test_an_inbox_entry_from_before_the_table_still_reaches_the_next_agent(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """Code that adds to ``job.data.inbox`` and saves -- a rejection's feedback, a retry's
    -- keeps working: a save adds what the copy has."""
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    job.data.inbox.append(InboxMessage(text="the old way"))
    store.save(job)

    engine.approve(job.id)

    builder = [r for r in provider.requests if r.role in DEVELOPER_ROLES]
    assert _context(builder[0])["messages_from_human"] == ["the old way"]


# --- asking ---------------------------------------------------------------------------


def test_the_agent_on_a_step_answers_without_moving_the_development(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    _answers(
        provider,
        RoleName.ARCHITECT,
        {"answer": "One phase: the counter is small enough to build at once."},
    )
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    calls = len(store.get(job.id).data.invocation_log)

    asked = engine.ask(job.id, "architecture", "why only one phase?", by="ada")
    assert asked.status == "answering" and asked.role == "architect"
    answered = engine.answer(asked.id)

    assert answered is not None and answered.status == "answered"
    assert answered.answer == "One phase: the counter is small enough to build at once."
    assert answered.change is None
    question = provider.requests[-1]
    assert question.role is RoleName.ARCHITECT
    assert _context(question)["question"] == "why only one phase?"
    after = store.get(job.id)
    assert after.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    # what it cost is on the development's bill, as a call of its own
    assert len(after.data.invocation_log) == calls + 1
    assert after.data.invocation_log[-1]["summary"] == "answered a question"
    assert [m.kind for m in engine.talk(job.id, "architecture")] == ["question"]


def test_an_answer_that_hears_a_request_says_so_and_changes_nothing(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    _answers(
        provider,
        RoleName.ARCHITECT,
        {"answer": "I can split it.", "change": "Split the phase into model and screen."},
    )
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)

    answered = engine.answer(engine.ask(job.id, "architecture", "split it in two").id)

    assert answered is not None
    assert answered.change == "Split the phase into model and screen."
    assert store.get(job.id).data.inbox == []  # nothing is sent until the person says so


def test_the_next_question_on_a_step_is_asked_with_the_earlier_ones(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    _answers(provider, RoleName.ARCHITECT, {"answer": "Because it is small."})
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    engine.answer(engine.ask(job.id, "architecture", "why one phase?").id)

    engine.answer(engine.ask(job.id, "architecture", "and why that?").id)

    assert _context(provider.requests[-1])["earlier"] == [
        {"question": "why one phase?", "answer": "Because it is small."}
    ]


def test_a_gate_has_nobody_to_ask(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    job = _developing(engine, repo)
    with pytest.raises(NothingToAsk):
        engine.ask(job.id, "architecture_gate", "anyone there?")
    with pytest.raises(NothingToAsk):
        engine.ask(job.id, "no-such-step", "anyone there?")


def test_a_question_over_the_budget_is_not_put_to_the_model(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    job.data.tokens_used = 10_000
    store.save(job)
    engine.budget_for = lambda _job: type(  # type: ignore[method-assign]
        "Budget", (), {"max_invocations": None, "max_tokens": 100, "max_wall_clock_s": None}
    )()
    before = len(provider.requests)

    answered = engine.answer(engine.ask(job.id, "architecture", "how is it going?").id)

    assert answered is not None and answered.status == "failed"
    assert "limit 100" in (answered.error or "")
    assert len(provider.requests) == before


def test_a_question_left_unanswered_by_a_restart_says_so(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    job = _developing(engine, repo)
    asked = engine.ask(job.id, "architecture", "still there?")

    assert store.fail_unanswered("the server restarted") == 1

    left = store.get_message(asked.id)
    assert left is not None and left.status == "failed"
    assert left.error == "the server restarted"


# --- telling the agent on a running phase ------------------------------------------------


def test_an_instruction_sent_while_the_last_part_was_written_gets_one_more_part(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    """The specialist said the phase was done, but somebody wrote to it while it was
    writing: the phase is not built past what they said."""
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    builder = RoleName.BACKEND
    calls: list[ModelRequest] = []

    def work(req: ModelRequest) -> dict[str, Any]:
        calls.append(req)
        if len(calls) == 1:
            # the person writes while this answer is still being written
            engine.steer(job.id, "phase:1", "count unique visitors only", by="ada")
        # a second answer the same as the first would be stopped as a loop
        return {"summary": f"wrote part {len(calls)}", "phase_complete": True, "changes": []}

    _answers(provider, builder, {"answer": "-"}, work=work)
    engine.approve(job.id)

    assert len(calls) == 2
    second = _context(calls[1])
    assert second["messages_from_human"] == ["count unique visitors only"]
    assert second["continuation"]["new_instruction"] is True
    (read,) = store.get(job.id).data.inbox
    assert read.consumed_by == builder.value and read.phase == 1


def test_a_green_phase_is_held_back_for_an_instruction_sent_while_it_was_built(
    store: JobStore,
    repo: Path,
    worktrees_root: Path,
    seed: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    gate = engine._run_gate
    sent: list[bool] = []

    def run_gate(job_now: Job, platform: str | None = None) -> Any:
        if not sent:
            sent.append(True)
            engine.steer(job.id, "phase:1", "log every visit", by="ada")
        return gate(job_now, platform)

    monkeypatch.setattr(engine, "_run_gate", run_gate)
    written: list[int] = []

    def work(req: ModelRequest) -> dict[str, Any]:
        written.append(1)
        return {
            "summary": f"wrote it, time {len(written)}",
            "phase_complete": True,
            "changes": [{"path": "OK", "content": f"yes {len(written)}\n"}],
        }

    _answers(provider, RoleName.BACKEND, {"answer": "-"}, work=work)
    engine.approve(job.id)

    builder_calls = [r for r in provider.requests if r.role is RoleName.BACKEND]
    assert len(builder_calls) == 2
    assert _context(builder_calls[1])["messages_from_human"] == ["log every visit"]
    notes = [t.note or "" for t in store.get(job.id).history]
    held = [n for n in notes if "a person wrote about this phase" in n]
    assert held == [
        "backend phase 1/1: the build passed; a person wrote about this phase, so it is "
        "read before the phase is committed"
    ]
    # and it is committed once, after it has read it
    commits = [n for n in notes if n.startswith("build gate passed for phase 1/")]
    assert len(commits) == 1


def test_a_finished_step_takes_no_instruction(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    from slipwright.engine import NotAwaitingApproval

    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    job = _developing(engine, repo)
    with pytest.raises(NotAwaitingApproval):
        engine.steer(job.id, "backlog", "more epics please")


# --- planning it again from where it is --------------------------------------------------


def test_a_running_development_is_planned_again_from_the_phase_it_is_on(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=2)
    replan_aware(provider)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    asked: list[Job] = []

    def work(req: ModelRequest) -> dict[str, Any]:
        if '"this_phase":true' in req.prompt.replace(" ", "") and not asked:
            current = store.get(job.id)
            if current.data.phase_index == 1:
                # phase 2 is being written when the person asks for a new plan
                asked.append(engine.redirect(job.id, "use a database, not memory", by="ada"))
        return {"summary": "wrote OK", "phase_complete": True, "changes": []}

    _answers(provider, RoleName.BACKEND, {"answer": "-"}, work=work)
    architect_calls = len([r for r in provider.requests if r.role is RoleName.ARCHITECT])
    job = engine.approve(job.id)

    assert asked, "phase 2 was never reached"
    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    again = [r for r in provider.requests if r.role is RoleName.ARCHITECT][architect_calls:]
    assert len(again) == 1
    assert "use a database, not memory" in again[0].prompt
    after = store.get(job.id)
    assert after.data.phase_index == 1  # phase 1 is kept, built and committed
    notes = [t.note or "" for t in after.history]
    assert "re-plan from phase 2 by ada: use a database, not memory" in notes
    (replan,) = [m for m in store.list_messages(job.id) if m.kind == "replan"]
    assert replan.status == "applied"


def test_a_development_waiting_on_its_screens_is_planned_again_at_once(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1, domains=["web"])
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)
    job = engine.approve(job.id)
    assert job.state is JobState.AWAITING_DESIGN_APPROVAL

    job = engine.redirect(job.id, "a single page, no list", by="ada")

    assert job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
    (replan,) = [m for m in store.list_messages(job.id) if m.kind == "replan"]
    assert replan.status == "applied"


def test_only_a_development_being_built_can_be_planned_again_from_where_it_is(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    from slipwright.engine import NotAwaitingApproval

    engine = full_engine(store, worktrees_root, seed, full_provider(seed, phases=1))
    job = _developing(engine, repo)
    with pytest.raises(NotAwaitingApproval):
        engine.redirect(job.id, "something else")  # the plan itself is still at its gate


def test_a_stop_drops_a_replan_it_overtook(
    store: JobStore, repo: Path, worktrees_root: Path, seed: Profile
) -> None:
    provider = full_provider(seed, phases=1)
    engine = full_engine(store, worktrees_root, seed, provider)
    job = _developing(engine, repo)

    def work(req: ModelRequest) -> dict[str, Any]:
        engine.redirect(job.id, "plan it again", by="ada")
        engine.cancel(job.id, by="ada")
        return {"summary": "wrote OK", "phase_complete": True, "changes": []}

    _answers(provider, RoleName.BACKEND, {"answer": "-"}, work=work)
    job = engine.approve(job.id)

    assert job.state is JobState.CANCELLED
    (replan,) = [m for m in store.list_messages(job.id) if m.kind == "replan"]
    assert replan.status == "dropped"
