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
        text = self.replies.pop(0) if self.replies else '{"intent": "unknown", "subject": ""}'
        return ModelResponse(text=text, model=request.model, provider=request.provider or "test")


@pytest.fixture
def bot(eng: Engine, owner: TestClient, store: JobStore, repo: Path) -> Notifier:  # noqa: F811
    """A notifier with Telegram set up and one person linked to the owner's account."""
    _set(owner, "telegram", secrets={"token": TG_TOKEN})
    notifier = _quiet(eng, _owner_id(store))
    _link_telegram(owner, notifier, TG_USER)
    return notifier


def _said(notifier: Notifier, store: JobStore, text: str) -> ask.Answer | None:
    return ask.ask(notifier, user_id=_owner_id(store), text=text)


def _asked(notifier: Notifier, store: JobStore, text: str) -> str | None:
    """What the bot says back, without the buttons: most of these are about the words."""
    answer = _said(notifier, store, text)
    return answer.text if answer else None


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
        '{"intent": "projects", "subject": ""}',  # which question
        '{"text": "Tek projen var: Note app."}',  # the sentence written from the rows
    )
    bot.engine._provider = canned  # noqa: SLF001

    answer = _asked(bot, store, "hangi projelerim var")
    assert answer == "Tek projen var: Note app."
    # the rows reached the writer; the message never reached a query
    written = canned.requests[-1].prompt
    assert "Note app" in written
    assert "SELECT" not in written.upper()


def test_a_development_is_found_by_the_words_the_person_used_for_it(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """People name the work, not the project it sits in.

    Asked about "the maths question one", the first version answered `no_such_project`:
    it only ever matched project names. It also handed the writer three booleans -- not
    finished, not waiting -- and got back a sentence that read out three booleans.
    """
    _start(owner, repo, request="tek ekran matematik sorusu, 15 saniyede cevapla")
    bot.engine._provider = Canned(  # noqa: SLF001
        '{"intent": "status", "subject": "matematik sorusu"}',
        '{"text": "Matematik sorusu geliştirmesi planlama adımında."}',
    )

    answer = _asked(bot, store, "matematik sorusu geliştirmesi ne durumda")
    assert answer is not None and "bulamadım" not in answer.lower()

    # and what the writer was given is the material a good answer needs
    given = bot.engine._provider.requests[-1].prompt  # noqa: SLF001
    assert "steps_done" in given and "steps_total" in given
    assert "last_thing_that_happened" in given
    assert "matematik" in given.lower(), "the person's own words come back to them"


def test_a_short_name_finds_a_long_request_suffixes_and_all() -> None:
    """Nobody types the whole request back.

    They say "the maths one", and in Turkish they say it with a suffix on it, which moves
    the last consonant: ``matematik`` is written ``matematiğin``. Matching on the first
    few letters is before the join, so both spellings land on the same development --
    while a phrase that is about none of them still finds none of them.
    """
    from dataclasses import dataclass
    from datetime import UTC, datetime

    from slipwright.notify.ask import _wanted

    @dataclass
    class Fake:
        request: str
        created_at: datetime
        project_id: str = "p1"
        title: str = ""

    maths = Fake(
        "tek ekran matematik sorusu random 100 taneden sırayla çözsün, "
        "15 saniyede bitince puan kazansın",
        datetime(2026, 9, 29, tzinfo=UTC),
    )
    notes = Fake("notlarımı yazacağım app olsun", datetime(2026, 9, 28, tzinfo=UTC))
    jobs = [maths, notes]

    for words in (
        "matematik",
        "matematik geliştirmesi",
        "matematiğin durumu",
        # typed on a phone with the Turkish letters left off, which is half the time
        "matematik gelistirmesi",
        "matematigin durumu",
        "puan kazanma",
    ):
        found = _wanted(jobs, [], words)  # type: ignore[arg-type]
        assert found and found[0] is maths, words
    assert _wanted(jobs, [], "notlar")[0] is notes  # type: ignore[arg-type]
    assert _wanted(jobs, [], "bir yazılım") == []  # type: ignore[arg-type]


def test_a_project_is_found_however_its_name_is_typed() -> None:
    """``NoteApp`` is answered to ``noteapp``, and ``İşler`` to ``isler``.

    Capital İ does not lower-case to the same letter as capital I, which is the one case
    where a plain ``casefold`` quietly fails a Turkish name.
    """
    from dataclasses import dataclass

    from slipwright.notify.ask import _match

    @dataclass
    class Fake:
        id: str
        name: str

    projects = [Fake("p1", "NoteApp"), Fake("p2", "İşler")]
    for typed in ("noteapp", "NOTEAPP", "NoteApp", "note"):
        assert _match(projects, typed).id == "p1", typed  # type: ignore[arg-type,union-attr]
    for typed in ("işler", "isler", "ISLER", "İşler"):
        assert _match(projects, typed).id == "p2", typed  # type: ignore[arg-type,union-attr]
    assert _match(projects, "başka bir şey") is None  # type: ignore[arg-type]


def test_a_name_that_matches_nothing_says_so_in_the_persons_language(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """Never the internal key: ``no_such_project`` was shown to somebody as an answer."""
    _start(owner, repo)
    bot.engine._provider = Canned(  # noqa: SLF001
        '{"intent": "status", "subject": "bir yaz\\u0131l\\u0131m"}',
        '{"text": "Öyle bir şey bulamadım."}',
    )
    answer = _asked(bot, store, "bir yazılım ne durumda")
    assert answer is not None
    assert "no_such_project" not in answer


def test_a_development_that_stopped_is_asked_why_and_answers_with_the_error(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """"Neden durdu" is the question after "durdu", and the answer is in the job's own
    history: the transition that entered ``failed`` carries the build output that says
    what went wrong. It used to send only the last note, which after a failure is often
    the bookkeeping written on top of it."""
    job_id = _start(owner, repo, request="matematik sorusu ekrani")
    engine = bot.engine
    job = engine.store.get(job_id)
    engine.store.update_state(
        job.id,
        JobState.FAILED,
        note="build gate failed after 3 attempts",
        detail="FAILED tests/test_score.py::test_points - AssertionError: 0 != 10",
    )
    # what lands afterwards must not be read back as the reason
    engine.store.update_state(job.id, JobState.FAILED, note="jira: synced 1 story")

    bot.engine._provider = Canned(  # noqa: SLF001
        '{"intent": "status", "subject": "matematik"}',
        '{"text": "Durdu: build kapisinda, test_points basarisiz."}',
    )
    answer = _asked(bot, store, "matematik işi durmuş neden")
    assert answer is not None

    given = bot.engine._provider.requests[-1].prompt  # noqa: SLF001
    assert "build gate failed after 3 attempts" in given
    assert "AssertionError: 0 != 10" in given, "the error itself, not just the headline"
    assert "jira: synced 1 story" not in given.split('"stopped_because"')[-1]


def test_how_many_are_done_is_counted_over_all_of_them(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """"NoteApp'te işler ne durumda" is two questions: how many, and where the rest are.

    Only a handful are described one by one -- a chat message is not a report -- so the
    counts have to come from the whole set. Counting the list instead would answer "five"
    to a project with eight developments in it.
    """
    from slipwright.notify.ask import SHOWN

    made = owner.post("/api/projects", json={"name": "NoteApp", "repo_path": str(repo)})
    assert made.status_code == 201, made.text
    project_id = made.json()["id"]
    ids = []
    for n in range(SHOWN + 3):
        started = owner.post(f"/api/projects/{project_id}/jobs", json={"request": f"iş {n}"})
        assert started.status_code == 201, started.text
        ids.append(started.json()["id"])
    for finished in ids[:4]:
        bot.engine.store.update_state(finished, JobState.DONE, note="done")

    bot.engine._provider = Canned(  # noqa: SLF001
        '{"intent": "status", "subject": "noteapp"}',
        '{"text": "8 geliştirme: 4 bitti."}',
    )
    _asked(bot, store, "noteapp projesinde işler ne durumda")

    given = bot.engine._provider.requests[-1].prompt  # noqa: SLF001
    assert '"developments": 8' in given
    assert '"finished": 4' in given
    assert given.count('"steps_done"') == SHOWN, "only a handful are described one by one"


def test_the_cost_answer_says_which_agent_spent_it(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """"What did it cost" is really "what is eating it".

    The answer is the costs page's own arithmetic -- the call log re-priced on the way
    out -- rather than a second sum written for the chat, so the two cannot drift apart.
    """
    job_id = _start(owner, repo)
    job = bot.engine.store.get(job_id)
    job.data.invocation_log = [
        {
            "role": "devops",
            "model": "deepseek-chat",
            "provider": "deepseek",
            "state": "devops",
            "attempts": 1,
            "input_tokens": 40_000,
            "output_tokens": 8_000,
            "cost_usd": 0.286,
        },
        {
            "role": "po",
            "model": "deepseek-chat",
            "provider": "deepseek",
            "state": "backlog",
            "attempts": 1,
            "input_tokens": 900,
            "output_tokens": 300,
            "cost_usd": 0.003,
        },
    ]
    bot.engine.store.save(job)

    bot.engine._provider = Canned(  # noqa: SLF001
        '{"intent": "cost", "subject": "note app"}',
        '{"text": "Note app: $0.289. En çok DevOps harcadı."}',
    )
    _asked(bot, store, "noteapp projesi maliyeti nedir")

    given = bot.engine._provider.requests[-1].prompt  # noqa: SLF001
    assert '"by_agent"' in given
    assert "devops" in given and "0.286" in given
    assert given.index("0.286") < given.index("0.003"), "the biggest spender comes first"
    bot.engine._provider = Canned('{"intent": "unknown", "subject": ""}')  # noqa: SLF001
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

    # under way, not merely written down: a job left in ``created`` is one nothing resumes
    job = bot.engine.store.get(started[0])
    assert job.request == "login ekle"
    assert job.state is JobState.BACKLOG


def test_one_sentence_fills_the_form_and_stops_at_the_yes(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """"NoteApp'e checkbox ekle" is the whole form in one line -- and still asks.

    A sentence is the classifier's guess at what the words meant, and a wrong guess here
    starts a development and spends the account's money on it. So it fills the form,
    shows it back, and waits for a yes.
    """
    made = owner.post("/api/projects", json={"name": "NoteApp", "repo_path": str(repo)})
    assert made.status_code == 201, made.text
    owner.post("/api/projects", json={"name": "Other", "repo_path": str(repo)})
    started: list[str] = []
    bot.resume = started.append
    bot.engine._provider = Canned(  # noqa: SLF001
        '{"intent": "start", "subject": "noteapp", "work": "checkbox ekle"}'
    )

    asked = _said(bot, store, "noteapp projesine checkbox ekle işini ekle")
    assert asked is not None
    assert "NoteApp" in asked.text and "checkbox ekle" in asked.text
    assert started == [], "a sentence never starts anything on its own"

    # the question comes with its two answers under it: no spelling, no second guess
    assert [data for _, data in asked.buttons] == [f"{ask.PRESS}:yes", f"{ask.PRESS}:no"]

    done = ask.decide(bot, external_id=str(TG_USER), choice="yes")
    assert "başladı" in done.lower()
    assert len(started) == 1
    assert bot.engine.store.get(started[0]).request == "checkbox ekle"


def test_anything_that_is_not_a_yes_drops_it(
    bot: Notifier, owner: TestClient, store: JobStore, repo: Path  # noqa: F811
) -> None:
    """The expensive mistake is reading a no as a yes, so only a yes is a yes."""
    owner.post("/api/projects", json={"name": "NoteApp", "repo_path": str(repo)})
    started: list[str] = []
    bot.resume = started.append
    start = '{"intent": "start", "subject": "noteapp", "work": "checkbox ekle"}'
    bot.engine._provider = Canned(start, start)  # noqa: SLF001
    _asked(bot, store, "noteapp projesine checkbox ekle")
    # the button says no, and so does anything typed that is not a yes
    assert "vazgeçtim" in ask.decide(bot, external_id=str(TG_USER), choice="no").lower()
    assert started == []

    _asked(bot, store, "noteapp projesine checkbox ekle")
    assert "vazgeçtim" in (_asked(bot, store, "dur bi düşüneyim") or "").lower()
    assert started == []


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
    bot.engine._provider = Canned('{"intent": "unknown", "subject": ""}')  # noqa: SLF001
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
    assert answer is not None and "sahibine ait" in answer.text.lower()


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
