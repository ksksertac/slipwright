import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from slipwright.schemas.job import Job, JobState, Transition, utcnow
from slipwright.schemas.profile import load_profile
from slipwright.store import JobNotFound, JobStore

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "python-fastapi.profile.json"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jobs.sqlite3"


@pytest.fixture
def store(db_path: Path) -> Iterator[JobStore]:
    with JobStore(db_path) as s:
        yield s


def _job(**overrides: object) -> Job:
    base: dict[str, object] = {"request": "add a health endpoint", "repo_path": Path("/repo")}
    base.update(overrides)
    return Job.model_validate(base)


def test_create_and_get(store: JobStore) -> None:
    job = store.create(_job())
    fetched = store.get(job.id)
    assert fetched == job
    assert fetched.state is JobState.CREATED
    assert fetched.history == []
    assert fetched.worktree_path is None
    assert fetched.port is None
    assert fetched.profile is None


def test_get_unknown_raises(store: JobStore) -> None:
    with pytest.raises(JobNotFound, match="nope"):
        store.get("nope")


def test_duplicate_id_rejected(store: JobStore) -> None:
    job = store.create(_job())
    with pytest.raises(sqlite3.IntegrityError):
        store.create(_job(id=job.id))


def test_read_back_after_reopening_connection(db_path: Path) -> None:
    profile = load_profile(EXAMPLE)
    with JobStore(db_path) as s:
        job = s.create(_job(profile=profile, port=8123, worktree_path=Path("/wt/abc")))
        s.update_state(job.id, JobState.ANALYZING)
        s.update_state(job.id, JobState.AWAITING_PROFILE_APPROVAL, note="analyst done")

    with JobStore(db_path) as s:
        fetched = s.get(job.id)

    assert fetched.state is JobState.AWAITING_PROFILE_APPROVAL
    assert fetched.profile == profile
    assert fetched.port == 8123
    assert fetched.worktree_path == Path("/wt/abc")
    assert [(t.from_state, t.to_state) for t in fetched.history] == [
        (JobState.CREATED, JobState.ANALYZING),
        (JobState.ANALYZING, JobState.AWAITING_PROFILE_APPROVAL),
    ]
    assert fetched.history[1].note == "analyst done"


def test_transitions_append_never_overwrite(store: JobStore) -> None:
    job = store.create(_job())
    before = utcnow()
    store.update_state(job.id, JobState.ANALYZING)
    store.update_state(job.id, JobState.AWAITING_PROFILE_APPROVAL)
    store.update_state(job.id, JobState.ANALYZING, note="rejected: wrong package manager")
    fetched = store.update_state(job.id, JobState.AWAITING_PROFILE_APPROVAL)

    assert len(fetched.history) == 4
    assert [t.to_state for t in fetched.history] == [
        JobState.ANALYZING,
        JobState.AWAITING_PROFILE_APPROVAL,
        JobState.ANALYZING,
        JobState.AWAITING_PROFILE_APPROVAL,
    ]
    # each entry carries its own timestamp and they are monotonic
    stamps = [t.at for t in fetched.history]
    assert all(s >= before for s in stamps)
    assert stamps == sorted(stamps)
    # from_state always chains from the previous to_state
    for prev, nxt in zip(fetched.history, fetched.history[1:], strict=False):
        assert nxt.from_state is prev.to_state


def test_update_state_unknown_job(store: JobStore) -> None:
    with pytest.raises(JobNotFound):
        store.update_state("missing", JobState.ANALYZING)


def test_history_row_count_grows_monotonically(store: JobStore, db_path: Path) -> None:
    job = store.create(_job())
    for state in (JobState.ANALYZING, JobState.AWAITING_PROFILE_APPROVAL, JobState.PLANNING):
        store.update_state(job.id, state)
    raw = sqlite3.connect(db_path)
    (count,) = raw.execute(
        "SELECT COUNT(*) FROM job_history WHERE job_id = ?", (job.id,)
    ).fetchone()
    raw.close()
    assert count == 3


def test_create_persists_preexisting_history(store: JobStore) -> None:
    t = Transition(from_state=JobState.CREATED, to_state=JobState.ANALYZING, at=utcnow())
    job = store.create(_job(state=JobState.ANALYZING, history=[t]))
    assert job.history == [t]


def test_save_updates_fields_but_not_state(store: JobStore) -> None:
    job = store.create(_job())
    job.port = 9000
    job.worktree_path = Path("/wt/x")
    job.profile = load_profile(EXAMPLE)
    saved = store.save(job)
    assert saved.port == 9000
    assert saved.worktree_path == Path("/wt/x")
    assert saved.profile is not None
    assert saved.history == []

    job.state = JobState.DONE
    with pytest.raises(ValueError, match="use update_state"):
        store.save(job)
    assert store.get(job.id).state is JobState.CREATED


def test_list_orders_by_creation(store: JobStore) -> None:
    assert store.list() == []
    a = store.create(_job(request="first"))
    b = store.create(_job(request="second"))
    c = store.create(_job(request="third"))
    store.update_state(b.id, JobState.ANALYZING)
    listed = store.list()
    assert [j.id for j in listed] == [a.id, b.id, c.id]
    assert listed[1].state is JobState.ANALYZING


def test_failed_transaction_leaves_no_partial_history(store: JobStore, db_path: Path) -> None:
    job = store.create(_job())
    # Force a failure after the history insert by violating the FK on a phantom job id
    # within the same transaction primitive the store uses.
    with pytest.raises(sqlite3.IntegrityError), store._tx() as conn:
        store._insert_transition(
            conn,
            job.id,
            Transition(from_state=JobState.CREATED, to_state=JobState.ANALYZING, at=utcnow()),
        )
        store._insert_transition(
            conn,
            "ghost",
            Transition(from_state=JobState.CREATED, to_state=JobState.ANALYZING, at=utcnow()),
        )
    assert store.get(job.id).history == []
