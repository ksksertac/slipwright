"""Persistence for projects and jobs.

Jobs live in the ``jobs`` table; phase transitions live in ``job_history`` and are only
ever inserted. ``update_state`` is the single write path for state changes and commits
the history row and the new state in one transaction, so the two can never disagree.
Projects live in ``projects``; a job's ``project_id`` points at one.

The tables are declared in ``store/schema.py`` and the engine is owned by
``store/db.py``, so the same queries run on SQLite (a local install, the test suite) and
on PostgreSQL (a hosted one). The module keeps its name because every caller imports
``JobStore`` from it.
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from sqlalchemy import delete, func, insert, select, update

from slipwright.events import EventBus
from slipwright.schemas.brief import ProjectBrief
from slipwright.schemas.job import Job, JobData, JobState, Transition, utcnow
from slipwright.schemas.profile import Profile
from slipwright.schemas.project import Project
from slipwright.schemas.testrun import TestRun
from slipwright.secrets import SecretBox, load_or_create_key
from slipwright.store.attachments import AttachmentStoreMixin
from slipwright.store.chat import ChatStoreMixin
from slipwright.store.db import Database, one, rows
from slipwright.store.members import MemberStoreMixin
from slipwright.store.messages import MessageStoreMixin
from slipwright.store.migrate import migrate
from slipwright.store.pages import PageStoreMixin
from slipwright.store.prices import PriceStoreMixin
from slipwright.store.schema import (
    attachments,
    job_history,
    jobs,
    project_briefs,
    projects,
    test_runs,
    translations,
)
from slipwright.store.settings import SettingsStoreMixin
from slipwright.store.support import SupportStoreMixin
from slipwright.store.users import UserStoreMixin
from slipwright.store.workers import WorkerStoreMixin

#: How many values one ``IN (...)`` carries. SQLite caps the parameter list and a very
#: long list is slow everywhere, so long lookups are chunked.
_IN_CHUNK = 400

#: The longest detail a history entry keeps. A diff is cut to ``MAX_DIFF_CHARS`` before it
#: is written and a build log to its tail, but nothing stopped a caller that forgot: one QA
#: note carried a 145 MB diff of node_modules, and every read of that development -- the
#: page polls it -- loaded, parsed and sent it whole. The start and the end are kept, where
#: a diff's file list and a log's error are.
MAX_DETAIL = 500_000
DETAIL_TAIL = 100_000


def bounded(detail: str | None) -> str | None:
    if detail is None or len(detail) <= MAX_DETAIL:
        return detail
    head = MAX_DETAIL - DETAIL_TAIL
    cut = len(detail) - MAX_DETAIL
    return f"{detail[:head]}\n\n(... {cut:,} characters cut here ...)\n\n{detail[-DETAIL_TAIL:]}"


#: Passed as ``owner_id`` to mean "no filter". ``None`` cannot mean that, because ``None``
#: is also a real owner: the one projects made before accounts had owners belong to.
ANY_OWNER = "*"


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


class JobInProgress(ValueError):
    def __init__(self, job_id: str, state: JobState) -> None:
        super().__init__(f"job {job_id} is still {state.value}; only finished jobs can be deleted")
        self.job_id = job_id
        self.state = state


class ProjectInUse(ValueError):
    def __init__(self, project_id: str, active: int) -> None:
        super().__init__(f"project {project_id} still has {active} unfinished job(s)")
        self.project_id = project_id
        self.active = active


class JobStore(
    UserStoreMixin,
    MemberStoreMixin,
    SettingsStoreMixin,
    PriceStoreMixin,
    SupportStoreMixin,
    PageStoreMixin,
    ChatStoreMixin,
    AttachmentStoreMixin,
    WorkerStoreMixin,
    MessageStoreMixin,
):
    """One store per database. Safe to share across threads within a process.

    ``target`` is either a file path (SQLite, the local default) or a database URL such
    as ``postgresql+psycopg://user:pass@host/slipwright``. ``secret_key`` encrypts stored
    secrets; when omitted it is read from (or created in) ``secret.key`` beside a SQLite
    file, and must be supplied — usually through ``SLIPWRIGHT_SECRET_KEY`` — for a server
    database that has no directory of its own.
    """

    def __init__(self, target: Path | str, *, secret_key: bytes | str | None = None) -> None:
        self.db = Database(target)
        self.path = Path(str(target)) if self.db.dialect == "sqlite" else None
        if secret_key is None:
            here = self.path.parent if self.path is not None else Path.cwd()
            secret_key = load_or_create_key(here)
        self.secret_box = SecretBox(secret_key)
        # every persisted change is announced here (see ``GET /api/events``)
        self.events = EventBus()
        migrate(self.db)

    # -- lifecycle ---------------------------------------------------------------------

    def close(self) -> None:
        self.db.dispose()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- reads -------------------------------------------------------------------------

    def get(self, job_id: str, owner_id: str | None = ANY_OWNER, *, details: bool = True) -> Job:
        """One job. With ``owner_id``, a job belonging to somebody else is *not found*
        rather than forbidden: a 404 says nothing about what exists.

        ``details=False`` leaves every history entry's ``detail`` unread and gives its
        size instead: what a list or a page that polls needs. The diffs and logs are most
        of a development's bytes, and only the one somebody opens is worth reading."""
        with self.db.connect() as conn:
            query = select(jobs).where(jobs.c.id == job_id)
            if owner_id != ANY_OWNER:
                query = query.where(jobs.c.owner_id == owner_id)
            row = one(conn.execute(query))
            if row is None:
                raise JobNotFound(job_id)
            columns = [
                job_history.c.from_state,
                job_history.c.to_state,
                job_history.c.at,
                job_history.c.note,
                job_history.c.detail_size,
            ]
            if details:
                columns.append(job_history.c.detail)
            history = rows(
                conn.execute(
                    select(*columns)
                    .where(job_history.c.job_id == job_id)
                    .order_by(job_history.c.seq)
                )
            )
            inbox = self._read_inbox(conn, job_id)
        job = self._row_to_job(row, history)
        job.data.inbox = inbox
        return job

    def list(
        self,
        project_id: str | None = None,
        owner_id: str | None = ANY_OWNER,
        *,
        details: bool = True,
    ) -> list[Job]:
        query = select(jobs.c.id).order_by(jobs.c.created_at, jobs.c.id)
        if project_id is not None:
            query = query.where(jobs.c.project_id == project_id)
        if owner_id != ANY_OWNER:
            query = query.where(jobs.c.owner_id == owner_id)
        with self.db.connect() as conn:
            ids = [r["id"] for r in rows(conn.execute(query))]
        return [self.get(job_id, details=details) for job_id in ids]

    def transition(self, job_id: str, index: int) -> Transition | None:
        """One history entry, whole: the ``index``-th of the job's, as ``Job.history``
        numbers them. Read on its own, so opening one does not read all the others."""
        if index < 0:
            return None
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(job_history)
                    .where(job_history.c.job_id == job_id)
                    .order_by(job_history.c.seq)
                    .offset(index)
                    .limit(1)
                )
            )
        return None if row is None else self._transition(row)

    # -- projects ----------------------------------------------------------------------

    def create_project(self, project: Project) -> Project:
        now = utcnow()
        with self.db.begin() as conn:
            conn.execute(
                insert(projects).values(
                    id=project.id,
                    owner_id=project.owner_id,
                    name=project.name,
                    data_json=project.model_dump_json(),
                    created_at=project.created_at.isoformat(),
                    updated_at=now.isoformat(),
                )
            )
        self.events.emit(
            "project",
            project_id=project.id,
            owner_id=project.owner_id,
            payload={"action": "created"},
        )
        return self.get_project(project.id)

    def get_project(self, project_id: str, owner_id: str | None = ANY_OWNER) -> Project:
        """One project, not found rather than forbidden when it is somebody else's."""
        query = select(projects.c.data_json).where(projects.c.id == project_id)
        if owner_id != ANY_OWNER:
            query = query.where(projects.c.owner_id == owner_id)
        with self.db.connect() as conn:
            row = one(conn.execute(query))
        if row is None:
            raise ProjectNotFound(project_id)
        return Project.model_validate_json(row["data_json"])

    def list_projects(self, owner_id: str | None = ANY_OWNER) -> builtins.list[Project]:
        query = select(projects.c.data_json).order_by(projects.c.created_at, projects.c.id)
        if owner_id != ANY_OWNER:
            query = query.where(projects.c.owner_id == owner_id)
        with self.db.connect() as conn:
            found = rows(conn.execute(query))
        return [Project.model_validate_json(r["data_json"]) for r in found]

    # -- project brief -----------------------------------------------------------------

    def get_brief(self, project_id: str) -> ProjectBrief:
        """The project's brief; an empty one when nothing has been written yet."""
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(project_briefs.c.data_json).where(
                        project_briefs.c.project_id == project_id
                    )
                )
            )
        if row is None:
            return ProjectBrief(project_id=project_id)
        return ProjectBrief.model_validate_json(row["data_json"])

    def save_brief(self, brief: ProjectBrief) -> ProjectBrief:
        brief = brief.model_copy(update={"updated_at": utcnow()})
        with self.db.begin() as conn:
            conn.execute(
                self.db.upsert(
                    project_briefs,
                    {
                        "project_id": brief.project_id,
                        "state": brief.state.value,
                        "data_json": brief.model_dump_json(),
                        "updated_at": brief.updated_at.isoformat(),
                    },
                    key=["project_id"],
                    update=["state", "data_json", "updated_at"],
                )
            )
        self.events.emit(
            "project.brief",
            project_id=brief.project_id,
            owner_id=self._owner_of_project(brief.project_id),
            payload={"state": brief.state.value},
        )
        return brief

    # -- test runs ---------------------------------------------------------------------

    def create_test_run(self, run: TestRun) -> TestRun:
        with self.db.begin() as conn:
            conn.execute(
                insert(test_runs).values(
                    id=run.id,
                    project_id=run.project_id,
                    job_id=run.job_id,
                    started_at=run.started_at.isoformat(),
                    data_json=run.model_dump_json(),
                )
            )
        self._emit_run(run)
        return self.get_test_run(run.id)

    def update_test_run(self, run: TestRun) -> TestRun:
        with self.db.begin() as conn:
            changed = conn.execute(
                update(test_runs)
                .where(test_runs.c.id == run.id)
                .values(data_json=run.model_dump_json())
            )
            if changed.rowcount == 0:
                raise TestRunNotFound(run.id)
        self._emit_run(run)
        return self.get_test_run(run.id)

    def _emit_run(self, run: TestRun) -> None:
        self.events.emit(
            "test_run.state",
            project_id=run.project_id,
            job_id=run.job_id,
            owner_id=self._owner_of_project(run.project_id),
            payload={"run_id": run.id, "status": run.status.value, "source": run.source.value},
        )

    def get_test_run(self, run_id: str, owner_id: str | None = ANY_OWNER) -> TestRun:
        """One run. The owner is the project's, so this joins rather than denormalising:
        a run is read once on a page, not in a loop."""
        query = select(test_runs.c.data_json).where(test_runs.c.id == run_id)
        if owner_id != ANY_OWNER:
            query = query.where(
                test_runs.c.project_id.in_(
                    select(projects.c.id).where(projects.c.owner_id == owner_id)
                )
            )
        with self.db.connect() as conn:
            row = one(conn.execute(query))
        if row is None:
            raise TestRunNotFound(run_id)
        return TestRun.model_validate_json(row["data_json"])

    def list_test_runs(
        self,
        project_id: str,
        job_id: str | None = None,
        owner_id: str | None = ANY_OWNER,
    ) -> builtins.list[TestRun]:
        query = (
            select(test_runs.c.data_json)
            .where(test_runs.c.project_id == project_id)
            .order_by(test_runs.c.started_at.desc(), test_runs.c.id)
        )
        if job_id is not None:
            query = query.where(test_runs.c.job_id == job_id)
        if owner_id != ANY_OWNER:
            query = query.where(
                test_runs.c.project_id.in_(
                    select(projects.c.id).where(projects.c.owner_id == owner_id)
                )
            )
        with self.db.connect() as conn:
            found = rows(conn.execute(query))
        return [TestRun.model_validate_json(r["data_json"]) for r in found]

    # -- translations ------------------------------------------------------------------

    def translations(self, lang: str, sources: Sequence[str]) -> dict[str, str]:
        """The cached translations into ``lang`` for the sources that have one."""
        wanted = list(dict.fromkeys(sources))
        found: dict[str, str] = {}
        with self.db.connect() as conn:
            for start in range(0, len(wanted), _IN_CHUNK):
                chunk = wanted[start : start + _IN_CHUNK]
                got = rows(
                    conn.execute(
                        select(translations.c.source, translations.c.text).where(
                            translations.c.lang == lang, translations.c.source.in_(chunk)
                        )
                    )
                )
                found.update({r["source"]: r["text"] for r in got})
        return found

    def save_translations(self, lang: str, texts: Mapping[str, str]) -> None:
        if not texts:
            return
        now = utcnow().isoformat()
        values = [
            {"lang": lang, "source": source, "text": text, "at": now}
            for source, text in texts.items()
        ]
        with self.db.begin() as conn:
            conn.execute(
                self.db.upsert(translations, values, key=["lang", "source"], update=["text", "at"])
            )

    def find_project_by_repo(
        self, repo_path: Path, owner_id: str | None = ANY_OWNER
    ) -> Project | None:
        """The project on this checkout. Scoped, or one tenant registering a path another
        already uses would be handed their project."""
        wanted = str(Path(repo_path).resolve())
        for project in self.list_projects(owner_id):
            if project.repo_path is not None and str(project.repo_path.resolve()) == wanted:
                return project
        return None

    def update_project(self, project: Project) -> Project:
        with self.db.begin() as conn:
            changed = conn.execute(
                update(projects)
                .where(projects.c.id == project.id)
                .values(
                    owner_id=project.owner_id,
                    name=project.name,
                    data_json=project.model_dump_json(),
                    updated_at=utcnow().isoformat(),
                )
            )
            if changed.rowcount == 0:
                raise ProjectNotFound(project.id)
        self.events.emit(
            "project",
            project_id=project.id,
            owner_id=project.owner_id,
            payload={"action": "updated"},
        )
        return self.get_project(project.id)

    def delete_project(
        self, project_id: str, owner_id: str | None = ANY_OWNER, *, force: bool = False
    ) -> None:
        """Delete a project and its finished jobs. Refused while a job is still running.

        ``force`` deletes it anyway. A development stopped at a gate can never reach a
        terminal state on its own -- no approval state has an edge to one -- so without
        this a project somebody has given up on could not be got rid of at all. Deleting
        is not a transition: the row simply stops existing, and the caller is responsible
        for the worktrees and the checkout that go with it.
        """
        from slipwright.schemas.job import TERMINAL_STATES

        with self.db.begin() as conn:
            mine = select(func.count()).select_from(projects).where(projects.c.id == project_id)
            if owner_id != ANY_OWNER:
                mine = mine.where(projects.c.owner_id == owner_id)
            exists = conn.execute(mine).scalar_one()
            if not exists:
                raise ProjectNotFound(project_id)
            states = rows(conn.execute(select(jobs.c.state).where(jobs.c.project_id == project_id)))
            active = sum(1 for r in states if JobState(r["state"]) not in TERMINAL_STATES)
            if active and not force:
                raise ProjectInUse(project_id, active)
            conn.execute(delete(test_runs).where(test_runs.c.project_id == project_id))
            conn.execute(delete(attachments).where(attachments.c.project_id == project_id))
            conn.execute(delete(jobs).where(jobs.c.project_id == project_id))
            conn.execute(delete(project_briefs).where(project_briefs.c.project_id == project_id))
            gone = one(conn.execute(select(projects.c.owner_id).where(projects.c.id == project_id)))
            conn.execute(delete(projects).where(projects.c.id == project_id))
        self.events.emit(
            "project",
            project_id=project_id,
            owner_id=None if gone is None else gone["owner_id"],
            payload={"action": "deleted"},
        )

    def delete_job(self, job_id: str, owner_id: str | None = ANY_OWNER) -> None:
        """Delete a finished job with its history and test runs."""
        from slipwright.schemas.job import TERMINAL_STATES

        with self.db.begin() as conn:
            query = select(jobs.c.state, jobs.c.project_id, jobs.c.owner_id).where(
                jobs.c.id == job_id
            )
            if owner_id != ANY_OWNER:
                query = query.where(jobs.c.owner_id == owner_id)
            row = one(conn.execute(query))
            if row is None:
                raise JobNotFound(job_id)
            if JobState(row["state"]) not in TERMINAL_STATES:
                raise JobInProgress(job_id, JobState(row["state"]))
            conn.execute(delete(test_runs).where(test_runs.c.job_id == job_id))
            conn.execute(delete(attachments).where(attachments.c.job_id == job_id))
            conn.execute(delete(jobs).where(jobs.c.id == job_id))
        self.events.emit(
            "job.state",
            project_id=row["project_id"],
            job_id=job_id,
            owner_id=row["owner_id"],
            payload={"state": "deleted"},
        )

    # -- writes ------------------------------------------------------------------------

    def create(self, job: Job) -> Job:
        """Persist a new job. Any history already on the object is written as-is."""
        now = utcnow()
        with self.db.begin() as conn:
            conn.execute(
                insert(jobs).values(
                    id=job.id,
                    project_id=job.project_id,
                    owner_id=job.owner_id,
                    request=job.request,
                    title=job.title,
                    repo_path=str(job.repo_path),
                    worktree_path=None if job.worktree_path is None else str(job.worktree_path),
                    port=job.port,
                    state=job.state.value,
                    profile_json=None if job.profile is None else job.profile.model_dump_json(),
                    data_json=job.data.model_dump_json(),
                    created_at=job.created_at.isoformat(),
                    updated_at=now.isoformat(),
                )
            )
            for t in job.history:
                self._insert_transition(conn, job.id, t)
            self._merge_inbox(conn, job.id, job.data.inbox)
        self.events.emit(
            "job.state",
            project_id=job.project_id,
            job_id=job.id,
            owner_id=job.owner_id,
            payload={"state": job.state.value, "request": job.request, "title": job.title},
        )
        return self.get(job.id)

    def note(self, job_id: str, note: str, detail: str | None = None) -> Job:
        """Append an entry to the job's history and leave its state as it is *now*.

        A note used to be ``update_state(job.id, job.state, ...)`` -- a move to the state
        the writer's copy held. A phase written ahead (T16.3) runs on a copy taken while
        the job was developing; its retry note, written while the run had moved on to
        review, put the job back in developing, and the run's next save crashed it:
        "save() cannot change state (developing -> review)". The state is read in the
        same transaction as the entry is written, so nothing can come between them."""
        return self.update_state(job_id, None, note=note, detail=detail)

    def update_state(
        self,
        job_id: str,
        to_state: JobState | None,
        note: str | None = None,
        detail: str | None = None,
    ) -> Job:
        """Append a transition and move the job to ``to_state`` atomically. None: no move,
        an entry at whatever state the job is in (``note``)."""
        with self.db.begin() as conn:
            row = one(conn.execute(select(jobs.c.state).where(jobs.c.id == job_id)))
            if row is None:
                raise JobNotFound(job_id)
            current = JobState(row["state"])
            to_state = current if to_state is None else to_state
            transition = Transition(
                from_state=current,
                to_state=to_state,
                at=utcnow(),
                note=note,
                detail=detail,
            )
            self._insert_transition(conn, job_id, transition)
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job_id)
                .values(state=to_state.value, updated_at=transition.at.isoformat())
            )
        job = self.get(job_id)
        self.events.emit(
            "job.state",
            project_id=job.project_id,
            job_id=job.id,
            owner_id=job.owner_id,
            payload={"state": job.state.value, "from_state": transition.from_state.value},
        )
        self.events.emit(
            "activity",
            project_id=job.project_id,
            job_id=job.id,
            owner_id=job.owner_id,
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
        with self.db.begin() as conn:
            row = one(conn.execute(select(jobs.c.state).where(jobs.c.id == job.id)))
            if row is None:
                raise JobNotFound(job.id)
            if row["state"] != job.state.value:
                raise ValueError(
                    f"save() cannot change state ({row['state']} -> {job.state.value}); "
                    "use update_state()"
                )
            conn.execute(
                update(jobs)
                .where(jobs.c.id == job.id)
                .values(
                    title=job.title,  # the one thing about a job a person may rename
                    worktree_path=(None if job.worktree_path is None else str(job.worktree_path)),
                    port=job.port,
                    profile_json=(None if job.profile is None else job.profile.model_dump_json()),
                    data_json=job.data.model_dump_json(),
                    updated_at=utcnow().isoformat(),
                )
            )
            # added to, never replaced: this copy may be older than a message sent since
            self._merge_inbox(conn, job.id, job.data.inbox)
        self.events.emit(
            "job.data", project_id=job.project_id, job_id=job.id, owner_id=job.owner_id
        )
        return self.get(job.id)

    def _owner_of_project(self, project_id: str) -> str | None:
        """Who a project belongs to, for events raised where only its id is at hand."""
        with self.db.connect() as conn:
            row = one(conn.execute(select(projects.c.owner_id).where(projects.c.id == project_id)))
        return None if row is None else row["owner_id"]

    # -- helpers -----------------------------------------------------------------------

    @staticmethod
    def _insert_transition(conn: Any, job_id: str, t: Transition) -> None:
        detail = bounded(t.detail)
        conn.execute(
            insert(job_history).values(
                job_id=job_id,
                from_state=t.from_state.value,
                to_state=t.to_state.value,
                at=t.at.isoformat(),
                note=t.note,
                detail=detail,
                detail_size=None if detail is None else len(detail),
            )
        )

    @staticmethod
    def _transition(h: Mapping[str, Any]) -> Transition:
        return Transition(
            from_state=JobState(h["from_state"]),
            to_state=JobState(h["to_state"]),
            at=datetime.fromisoformat(h["at"]),
            note=h["note"],
            detail=h.get("detail"),
            detail_size=h.get("detail_size"),
        )

    @staticmethod
    def _row_to_job(row: Mapping[str, Any], history: Sequence[Mapping[str, Any]]) -> Job:
        return Job(
            id=row["id"],
            project_id=row["project_id"],
            owner_id=row["owner_id"],
            request=row["request"],
            title=row["title"] or "",
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
            history=[JobStore._transition(h) for h in history],
            data=(
                JobData()
                if row["data_json"] is None
                else JobData.model_validate_json(row["data_json"])
            ),
        )
