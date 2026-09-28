"""Asking the bot where things stand, and starting work from the chat (T13).

The reading half must never let a chat message near the database, and the writing half
must never start work from a guess: a development spends the account's own money, so it
begins with a typed command and every answer after it is asked for one at a time.

The fakes and helpers are the notification suite's; only the questions are new here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from slipwright.engine import Engine
from slipwright.notify import ask
from slipwright.notify.core import Notifier
from slipwright.providers import ModelRequest, ModelResponse
from slipwright.schemas.job import JobState
from slipwright.store import JobStore
from tests.test_phase13_notify import (  # noqa: F401 - fixtures are used by name
    TG_TOKEN,
    FakeChat,
    _link_telegram,
    _owner_id,
    _quiet,
    _set,
    _start,
    chat,
    eng,
    owner,
)

TG_USER = 4242


class Canned:
    """A provider that answers whatever it is told to, and counts the asking."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        text = self.replies.pop(0) if self.replies else '{"intent": "unknown", "project": ""}'
        return ModelResponse(text=text, model=request.model, provider=request.provider or "test")


@pytest.fixture
def bot(eng: Engine, owner: TestClient, store: JobStore, repo: Path) -> Notifier:  # noqa: F811
    """A notifier with Telegram set up and one person linked to the owner's account."""
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, TG_USER)
    return notifier


def _asked(notifier: Notifier, store: JobStore, text: str) -> str | None:
    return ask.ask(notifier, user_id=_owner_id(store), text=text)


# --- reading ------------------------------------------------------------------------------


def test_a_command_is_answered_without_asking_a_model(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """``/projeler`` is not a sentence anybody has to interpret, so nothing is spent on it."""
    _start(owner, repo)
    canned = Canned()
    bot.engine._provider = canned  # noqa: SLF001 - the model under test is the one not called

    answer = _asked(bot, store, "/projeler")
    assert answer is not None and "Note app" in answer
    assert canned.requests == [], "a typed command must cost nothing"


def test_a_sentence_is_routed_to_one_of_the_questions(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    _start(owner, repo)
    canned = Canned(
        '{"intent": "projects", "project": ""}',  # which question
        '{"text": "Tek projen var: Note app."}',  # the sentence written from the rows
    )
    bot.engine._provider = canned  # noqa: SLF001

    answer = _asked(bot, store, "hangi projelerim var")
    assert answer == "Tek projen var: Note app."
    # the rows reached the writer; the message never reached a query
    written = canned.requests[-1].prompt
    assert "Note app" in written
    assert "SELECT" not in written.upper()


def test_a_question_it_does_not_know_is_a_shrug(
    bot: Notifier, store: JobStore
) -> None:
    bot.engine._provider = Canned('{"intent": "unknown", "project": ""}')  # noqa: SLF001
    answer = _asked(bot, store, "bugün hava nasıl")
    assert answer is not None and "bilmiyorum" in answer.lower()


def test_nobody_reads_another_account_through_the_bot(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path, eng: Engine  # noqa: F811
) -> None:
    """The one place a stranger's sentence gets near the data: it is scoped, not trusted."""
    from slipwright.schemas.project import Project

    eng.create_project(Project(name="somebody else's", repo_path=repo, owner_id="bob"))
    _start(owner, repo)
    bot.engine._provider = Canned()  # noqa: SLF001

    answer = _asked(bot, store, "/projeler")
    assert answer is not None
    assert "Note app" in answer
    assert "somebody else" not in answer


def test_too_many_questions_are_refused(bot: Notifier, store: JobStore) -> None:
    bot.engine._provider = Canned()  # noqa: SLF001
    seen = {_asked(bot, store, "/projeler") for _ in range(ask.ASK_LIMIT + 2)}
    assert any(a and "çok fazla" in a.lower() for a in seen)


# --- starting a development ----------------------------------------------------------------


def test_a_development_is_started_one_question_at_a_time(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """``/yeni`` asks which project, then what to build, and only then starts anything."""
    _start(owner, repo)  # the account has exactly one project
    started: list[str] = []
    bot.resume = started.append
    bot.engine._provider = Canned()  # noqa: SLF001

    first = _asked(bot, store, "/yeni")
    assert first is not None and "ne yapılsın" in first.lower()
    assert started == [], "nothing runs until the request has been given"

    done = _asked(bot, store, "login ekle")
    assert done is not None and "başladı" in done.lower()
    assert len(started) == 1

    job = bot.engine.store.get(started[0])
    assert job.request == "login ekle"
    assert job.state is JobState.CREATED


def test_the_project_is_asked_for_when_there_is_more_than_one(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    _start(owner, repo)
    second = owner.post("/api/projects", json={"name": "Other", "repo_path": str(repo)})
    assert second.status_code == 201
    bot.resume = lambda job_id: None
    bot.engine._provider = Canned()  # noqa: SLF001

    asked = _asked(bot, store, "/yeni")
    assert asked is not None and "Note app" in asked and "Other" in asked

    # a number picks from the list, and the answer after it is the request, not a question
    assert "ne yapılsın" in (_asked(bot, store, "2") or "").lower()
    done = _asked(bot, store, "arama kutusu")
    assert done is not None and "Other" in done


def test_a_half_finished_conversation_can_be_dropped(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    _start(owner, repo)
    bot.engine._provider = Canned()  # noqa: SLF001
    _asked(bot, store, "/yeni")
    assert "vazgeçtim" in (_asked(bot, store, "/iptal") or "").lower()
    # and the next sentence is a question again, not the answer to a dead conversation
    bot.engine._provider = Canned('{"intent": "unknown", "project": ""}')  # noqa: SLF001
    assert "bilmiyorum" in (_asked(bot, store, "ne oldu") or "").lower()


def test_the_demo_project_cannot_be_worked_on_from_the_chat(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path, eng: Engine  # noqa: F811
) -> None:
    """It has no checkout, so a development on it would fail deeper in."""
    from slipwright.demo import seed_demo_project

    seed_demo_project(eng.store, _owner_id(store))
    bot.engine._provider = Canned()  # noqa: SLF001
    asked = _asked(bot, store, "/yeni")
    assert asked is not None
    assert "henüz projen yok" in asked.lower(), "the demo is not something to build on"


def test_a_member_may_not_start_work_from_the_chat(
    bot: Notifier, eng: Engine, store: JobStore, owner: TestClient, repo: Path  # noqa: F811
) -> None:
    """Somebody invited onto an agent decides at their gates; starting is the owner's."""
    from tests.test_phase12_teams import _accept, _invite

    _start(owner, repo)
    _invite(owner, role="backend", email="dev@acme.com")
    _accept(owner, store, "dev@acme.com")
    joined = store.find_by_email("dev@acme.com")
    assert joined is not None
    member = joined.id
    answer = ask.ask(bot, user_id=member, text="/yeni")
    assert answer is not None and "sahibine ait" in answer.lower()


# --- defining a project --------------------------------------------------------------------


def test_a_project_is_defined_one_question_at_a_time(
    bot: Notifier, store: JobStore, repo: Path
) -> None:
    made: list[Any] = []
    bot.engine._provider = Canned()  # noqa: SLF001

    first = _asked(bot, store, "/proje")
    assert first is not None and "adı" in first.lower()
    second = _asked(bot, store, "Kayıtlar")
    assert second is not None and "depo" in second.lower()

    # the clone runs behind, so the chat is answered at once and told the outcome after
    answer = _asked(bot, store, str(repo))
    assert answer is not None and "kuruyorum" in answer.lower()

    for _ in range(200):  # the background thread is given a moment
        made = bot.engine.store.list_projects(bot.owner_key or None)
        if made:
            break
        import time

        time.sleep(0.02)
    assert [p.name for p in made] == ["Kayıtlar"]
