"""What a development is doing right now.

No provider streams, so an answer only ever arrives whole, minutes after it was asked for.
The page that follows a development still has to say something in between: the job
records the call it is waiting on -- who was asked, on which model, since when -- and,
once the answer is in, what it said.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from slipwright.engine import Engine
from slipwright.providers import ModelRequest, ModelResponse
from slipwright.providers.scripted import ScriptedProvider
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from tests.pipeline import full_engine, full_provider


class Watching:
    """The scripted vendor, looking at the job while each call is still in the air."""

    def __init__(self, inner: ScriptedProvider, store: JobStore) -> None:
        self.inner = inner
        self.store = store
        self.seen: list[dict[str, Any] | None] = []
        self.fail: RoleName | None = None

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.seen.append(self.store.list()[-1].data.inflight)
        if request.role is self.fail:
            raise RuntimeError("the vendor fell over")
        return self.inner.complete(request)


@pytest.fixture
def watching(store: JobStore, seed: Profile) -> Watching:
    return Watching(full_provider(seed, phases=1), store)


@pytest.fixture
def engine(store: JobStore, worktrees_root: Path, seed: Profile, watching: Watching) -> Engine:
    return full_engine(store, worktrees_root, seed, watching)  # type: ignore[arg-type]


def test_while_an_agent_is_asked_the_development_says_who_and_since_when(
    engine: Engine, watching: Watching, repo: Path
) -> None:
    engine.start(engine.create_job("health", repo).id)

    asked = watching.seen[0]
    assert asked is not None
    assert asked["role"] == "po"
    assert asked["model"]  # the model it was sent to, before any answer names one
    assert asked["started_at"]


def test_once_answered_the_call_says_what_it_wrote_and_nothing_is_waited_on(
    engine: Engine, store: JobStore, repo: Path
) -> None:
    job = engine.start(engine.create_job("health", repo).id)

    entry = next(e for e in job.data.invocation_log if e["role"] == "po")
    assert entry["summary"] == "1 tasks"  # the role's own account of what it did
    assert entry["output"] and entry["output"].startswith("{")  # the answer itself, clipped
    assert entry["started_at"] <= entry["at"]
    assert store.get(job.id).data.inflight is None


def test_a_call_that_blows_up_is_not_left_on_the_page_as_one_still_waited_for(
    engine: Engine, watching: Watching, store: JobStore, repo: Path
) -> None:
    watching.fail = RoleName.PO
    job = engine.create_job("health", repo)

    engine.start(job.id)

    assert watching.seen and watching.seen[0] is not None
    assert store.get(job.id).data.inflight is None


def test_what_a_call_wrote_is_kept_short(
    engine: Engine, watching: Watching, seed: Profile, repo: Path
) -> None:
    watching.inner.replies[RoleName.PO]["summary"] = "x" * 5000
    job = engine.start(engine.create_job("health", repo).id)

    entry = next(e for e in job.data.invocation_log if e["role"] == "po")
    assert len(entry["summary"]) <= 400 and entry["summary"].endswith("…")
    assert len(entry["output"]) <= 1500
