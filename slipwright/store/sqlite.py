"""SQLite persistence for projects and jobs.

Jobs live in the ``jobs`` table; phase transitions live in ``job_history`` and are only
ever inserted. ``update_state`` is the single write path for state changes and commits
the history row and the new state in one transaction, so the two can never disagree.
Projects live in ``projects``; a job's ``project_id`` points at one.
"""

from __future__ import annotations

import builtins
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from slipwright.events import EventBus
from slipwright.schemas.job import Job, JobData, JobState, Transition, utcnow
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.schemas.testrun import TestRun
from slipwright.secrets import SecretBox, load_or_create_key
from slipwright.store.settings import SETTINGS_SCHEMA, SettingsStoreMixin
from slipwright.store.users import USERS_SCHEMA, UserStoreMixin

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    data_json     TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id            TEXT PRIMARY KEY,
    project_id    TEXT,
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
CREATE INDEX IF NOT EXISTS jobs_project_id ON jobs(project_id, created_at);

CREATE TABLE IF NOT EXISTS test_runs (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    job_id        TEXT,
    started_at    TEXT NOT NULL,
    data_json     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS test_runs_project ON test_runs(project_id, started_at);
"""

# Columns added after the first release; applied to databases created before them.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "data_json", "ALTER TABLE jobs ADD COLUMN data_json TEXT"),
    ("job_history", "detail", "ALTER TABLE job_history ADD COLUMN detail TEXT"),
    ("jobs", "project_id", "ALTER TABLE jobs ADD COLUMN project_id TEXT"),
)


class JobNotFound(KeyError):
    def __init__(self, job_id: str) -> None:
        super().__init__(job_id)
        self.job_id = job_id

    def __str__(self) -> str:
        return f"job not found: {self.job_id}"


class ProjectNotFound(KeyError):
    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.project_id = project_id

    def __str__(self) -> str:
        return f"project not found: {self.project_id}"


class TestRunNotFound(KeyError):
    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)
        self.run_id = run_id

    def __str__(self) -> str:
        return f"test run not found: {self.run_id}"


class ProjectInUse(ValueError):
    def __init__(self, project_id: str, active: int) -> None:
        super().__init__(f"project {project_id} still has {active} unfinished job(s)")
        self.project_id = project_id
        self.active = active


class JobStore(UserStoreMixin, SettingsStoreMixin):
    """One store per SQLite file. Safe to share across threads within a process.

    ``secret_key`` encrypts stored secrets; when omitted it is read from (or created
    in) ``secret.key`` next to the database.
    """

    def __init__(self, path: Path | str, *, secret_key: bytes | str | None = None) -> None:
        self.path = Path(path)
        if secret_key is None:
            secret_key = load_or_create_key(self.path.parent)
        self.secret_box = SecretBox(secret_key)
        # every persisted change is announced here (see ``GET /api/events``)
        self.events = EventBus()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(USERS_SCHEMA)
        self._conn.executescript(SETTINGS_SCHEMA)
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

    def list(self, project_id: str | None = None) -> list[Job]:
        with self._lock:
            if project_id is None:
                rows = self._conn.execute("SELECT id FROM jobs ORDER BY created_at, id")
            else:
                rows = self._conn.execute(
                    "SELECT id FROM jobs WHERE project_id = ? ORDER BY created_at, id",
                    (project_id,),
                )
            ids = [r["id"] for r in rows.fetchall()]
            return [self.get(job_id) for job_id in ids]

    # -- projects ----------------------------------------------------------------------

    def create_project(self, project: Project) -> Project:
        now = utcnow()
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, data_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    project.id,
                    project.name,
                    project.model_dump_json(),
                    project.created_at.isoformat(),
                    now.isoformat(),
                ),
            )
        self.events.emit("project", project_id=project.id, payload={"action": "created"})
        return self.get_project(project.id)

    def get_project(self, project_id: str) -> Project:
        with self._lock:
            row = self._conn.execute(
                "SELECT data_json FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise ProjectNotFound(project_id)
        return Project.model_validate_json(row["data_json"])

    def list_projects(self) -> builtins.list[Project]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data_json FROM projects ORDER BY created_at, id"
            ).fetchall()
        return [Project.model_validate_json(r["data_json"]) for r in rows]

    # -- test runs ---------------------------------------------------------------------

    def create_test_run(self, run: TestRun) -> TestRun:
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO test_runs (id, project_id, job_id, started_at, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.project_id,
                    run.job_id,
                    run.started_at.isoformat(),
                    run.model_dump_json(),
                ),
            )
        self._emit_run(run)
        return self.get_test_run(run.id)

    def update_test_run(self, run: TestRun) -> TestRun:
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE test_runs SET data_json = ? WHERE id = ?", (run.model_dump_json(), run.id)
            )
            if cur.rowcount == 0:
                raise TestRunNotFound(run.id)
        self._emit_run(run)
        return self.get_test_run(run.id)

    def _emit_run(self, run: TestRun) -> None:
        self.events.emit(
            "test_run.state",
            project_id=run.project_id,
            job_id=run.job_id,
            payload={"run_id": run.id, "status": run.status.value, "source": run.source.value},
        )

    def get_test_run(self, run_id: str) -> TestRun:
        with self._lock:
            row = self._conn.execute(
                "SELECT data_json FROM test_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise TestRunNotFound(run_id)
        return TestRun.model_validate_json(row["data_json"])

    def list_test_runs(self, project_id: str, job_id: str | None = None) -> builtins.list[TestRun]:
        with self._lock:
            if job_id is None:
                rows = self._conn.execute(
                    "SELECT data_json FROM test_runs WHERE project_id = ? "
                    "ORDER BY started_at DESC, id",
                    (project_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT data_json FROM test_runs WHERE project_id = ? AND job_id = ? "
                    "ORDER BY started_at DESC, id",
                    (project_id, job_id),
                ).fetchall()
        return [TestRun.model_validate_json(r["data_json"]) for r in rows]

    def find_project_by_repo(self, repo_path: Path) -> Project | None:
        wanted = str(Path(repo_path).resolve())
        for project in self.list_projects():
            if project.repo_path is not None and str(project.repo_path.resolve()) == wanted:
                return project
        return None

    def update_project(self, project: Project) -> Project:
        with self._tx() as conn:
            cur = conn.execute(
                "UPDATE projects SET name = ?, data_json = ?, updated_at = ? WHERE id = ?",
                (project.name, project.model_dump_json(), utcnow().isoformat(), project.id),
            )
            if cur.rowcount == 0:
                raise ProjectNotFound(project.id)
        self.events.emit("project", project_id=project.id, payload={"action": "updated"})
        return self.get_project(project.id)

    def delete_project(self, project_id: str) -> None:
        """Delete a project and its finished jobs. Refused while a job is still running."""
        from slipwright.schemas.job import TERMINAL_STATES

        with self._tx() as conn:
            if (
                conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
                is None
            ):
                raise ProjectNotFound(project_id)
            rows = conn.execute(
                "SELECT state FROM jobs WHERE project_id = ?", (project_id,)
            ).fetchall()
            active = sum(1 for r in rows if JobState(r["state"]) not in TERMINAL_STATES)
            if active:
                raise ProjectInUse(project_id, active)
            conn.execute("DELETE FROM test_runs WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM jobs WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.events.emit("project", project_id=project_id, payload={"action": "deleted"})

    # -- writes ------------------------------------------------------------------------

    def create(self, job: Job) -> Job:
        """Persist a new job. Any history already on the object is written as-is."""
        now = utcnow()
        with self._tx() as conn:
            conn.execute(
                "INSERT INTO jobs (id, project_id, request, repo_path, worktree_path, port, "
                "state, profile_json, data_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.project_id,
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
        self.events.emit(
            "job.state",
            project_id=job.project_id,
            job_id=job.id,
            payload={"state": job.state.value, "request": job.request},
        )
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
        job = self.get(job_id)
        self.events.emit(
            "job.state",
            project_id=job.project_id,
            job_id=job.id,
            payload={"state": job.state.value, "from_state": transition.from_state.value},
        )
        self.events.emit(
            "activity",
            project_id=job.project_id,
            job_id=job.id,
            payload={
                "index": len(job.history) - 1,
                "title": note or f"{transition.from_state.value} -> {to_state.value}",
                "to_state": to_state.value,
            },
        )
        return job

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
        self.events.emit("job.data", project_id=job.project_id, job_id=job.id)
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
            project_id=row["project_id"],
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
