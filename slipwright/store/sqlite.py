"""SQLite persistence for jobs.

Jobs live in the ``jobs`` table; phase transitions live in ``job_history`` and are only
ever inserted. ``update_state`` is the single write path for state changes and commits
the history row and the new state in one transaction, so the two can never disagree.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from slipwright.schemas.job import Job, JobData, JobState, Transition, utcnow
from slipwright.schemas.profile import Profile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    request       TEXT NOT NULL,
    repo_path     TEXT NOT NULL,
    worktree_path TEXT,
    port          INTEGER,
    state         TEXT NOT NULL,
    profile_json  TEXT,
    data_json     TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_history (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    from_state TEXT NOT NULL,
    to_state   TEXT NOT NULL,
    at         TEXT NOT NULL,
    note       TEXT,
    detail     TEXT
);

CREATE INDEX IF NOT EXISTS job_history_job_id ON job_history(job_id, seq);
"""

# Columns added after the first release; applied to databases created before them.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "data_json", "ALTER TABLE jobs ADD COLUMN data_json TEXT"),
    ("job_history", "detail", "ALTER TABLE job_history ADD COLUMN detail TEXT"),
)


class JobNotFound(KeyError):
    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id

    def __str__(self) -> str:
        return f"job not found: {self.job_id}"


class JobStore:
    """One store per SQLite file. Safe to share across threads within a process."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        for table, column, ddl in _MIGRATIONS:
            columns = {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self._conn.execute(ddl)

    # -- lifecycle ---------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # -- reads -------------------------------------------------------------------------

    def get(self, job_id: str) -> Job:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            history = self._conn.execute(
                "SELECT from_state, to_state, at, note, detail FROM job_history "
                "WHERE job_id = ? ORDER BY seq",
                (job_id,),
            ).fetchall()
        return self._row_to_job(row, history)

    def list(self) -> list[Job]:
        with self._lock:
            ids = [
                r["id"]
                for r in self._conn.execute(
                    "SELECT id FROM jobs ORDER BY created_at, id"
                ).fetchall()
            ]
            return [self.get(job_id) for job_id in ids]

    # -- writes ------------------------------------------------------------------------

    def create(self, job: Job) -> Job:
        """Persist a new job. Any history already on the object is written as-is."""
        now = utcnow()
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO jobs (id, request, repo_path, worktree_path, port, state, "
                "profile_json, data_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.request,
                    str(job.repo_path),
                    None if job.worktree_path is None else str(job.worktree_path),
                    job.port,
                    job.state.value,
                    None if job.profile is None else job.profile.model_dump_json(),
                    job.data.model_dump_json(),
                    job.created_at.isoformat(),
                    now.isoformat(),
                ),
            )
            for t in job.history:
                self._insert_transition(conn, job.id, t)
        return self.get(job.id)

    def update_state(
        self,
        job_id: str,
        to_state: JobState,
        note: str | None = None,
        detail: str | None = None,
    ) -> Job:
        """Append a transition and move the job to ``to_state`` atomically."""
        with self._tx() as conn:
            row = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            transition = Transition(
                from_state=JobState(row["state"]),
                to_state=to_state,
                at=utcnow(),
                note=note,
                detail=detail,
            )
            self._insert_transition(conn, job_id, transition)
            conn.execute(
                "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
                (to_state.value, transition.at.isoformat(), job_id),
            )
        return self.get(job_id)

    def save(self, job: Job) -> Job:
        """Persist mutable non-state fields (worktree, port, profile, data).

        State and history are deliberately not written here; use ``update_state``.
        """
        with self._tx() as conn:
            row = conn.execute("SELECT state FROM jobs WHERE id = ?", (job.id,)).fetchone()
            if row is None:
                raise JobNotFound(job.id)
            if row["state"] != job.state.value:
                raise ValueError(
                    f"save() cannot change state ({row['state']} -> {job.state.value}); "
                    "use update_state()"
                )
            conn.execute(
                "UPDATE jobs SET worktree_path = ?, port = ?, profile_json = ?, data_json = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    None if job.worktree_path is None else str(job.worktree_path),
                    job.port,
                    None if job.profile is None else job.profile.model_dump_json(),
                    job.data.model_dump_json(),
                    utcnow().isoformat(),
                    job.id,
                ),
            )
        return self.get(job.id)

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def _insert_transition(conn: sqlite3.Connection, job_id: str, t: Transition) -> None:
        conn.execute(
            "INSERT INTO job_history (job_id, from_state, to_state, at, note, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, t.from_state.value, t.to_state.value, t.at.isoformat(), t.note, t.detail),
        )

    @staticmethod
    def _row_to_job(row: sqlite3.Row, history: Sequence[sqlite3.Row]) -> Job:
        return Job(
            id=row["id"],
            request=row["request"],
            repo_path=Path(row["repo_path"]),
            worktree_path=None if row["worktree_path"] is None else Path(row["worktree_path"]),
            port=row["port"],
            state=JobState(row["state"]),
            profile=(
                None
                if row["profile_json"] is None
                else Profile.model_validate_json(row["profile_json"])
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            history=[
                Transition(
                    from_state=JobState(h["from_state"]),
                    to_state=JobState(h["to_state"]),
                    at=datetime.fromisoformat(h["at"]),
                    note=h["note"],
                    detail=h["detail"],
                )
                for h in history
            ],
            data=(
                JobData()
                if row["data_json"] is None
                else JobData.model_validate_json(row["data_json"])
            ),
        )
