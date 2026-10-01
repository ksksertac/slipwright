"""Workers, their connection codes and the builds they are given: mixed into ``JobStore``.

Rows only. ``slipwright/workers.py`` decides what a code looks like, when a worker counts
as there and what a lost build means. The one rule kept here is that a build is claimed
by exactly one worker: the claim is a conditional update, so two polls racing for the
same row cannot both win it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, insert, select, update

from slipwright.schemas.job import new_job_id, utcnow
from slipwright.schemas.worker import TaskResult, Worker, WorkerTask
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import worker_codes, worker_tasks, workers


def _owner(owner_id: str | None) -> str:
    """The column is not nullable: "" is the installation, as with chat codes."""
    return owner_id or ""


def _worker(row: dict[str, Any], *, live_since: datetime | None = None) -> Worker:
    seen = datetime.fromisoformat(row["last_seen_at"]) if row["last_seen_at"] else None
    return Worker(
        id=row["id"],
        owner_id=row["owner_id"] or None,
        name=row["name"],
        capabilities=json.loads(row["capabilities_json"] or "[]"),
        paired_at=datetime.fromisoformat(row["paired_at"]),
        last_seen_at=seen,
        revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
        online=bool(
            seen is not None
            and live_since is not None
            and seen >= live_since
            and not row["revoked_at"]
        ),
    )


class WorkerStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    # -- codes -------------------------------------------------------------------------

    def create_worker_code(self, owner_id: str | None, secret_hash: str, *, ttl: timedelta) -> None:
        """Keep the hash of a fresh secret; any earlier code of this account stops working."""
        now = utcnow()
        with self.db.begin() as conn:
            conn.execute(delete(worker_codes).where(worker_codes.c.owner_id == _owner(owner_id)))
            conn.execute(
                insert(worker_codes).values(
                    code_hash=secret_hash,
                    owner_id=_owner(owner_id),
                    created_at=now.isoformat(),
                    expires_at=(now + ttl).isoformat(),
                )
            )

    def redeem_worker_code(self, secret_hash: str) -> tuple[bool, str | None]:
        """(valid, owner): a code is spent by being read, run out or not."""
        with self.db.begin() as conn:
            row = one(
                conn.execute(select(worker_codes).where(worker_codes.c.code_hash == secret_hash))
            )
            if row is None:
                return False, None
            conn.execute(delete(worker_codes).where(worker_codes.c.code_hash == secret_hash))
        if datetime.fromisoformat(row["expires_at"]) < utcnow():
            return False, None
        return True, row["owner_id"] or None

    # -- workers -----------------------------------------------------------------------

    def add_worker(
        self, owner_id: str | None, name: str, token_hash: str, capabilities: list[str]
    ) -> Worker:
        now = utcnow().isoformat()
        worker_id = new_job_id()
        with self.db.begin() as conn:
            conn.execute(
                insert(workers).values(
                    id=worker_id,
                    owner_id=_owner(owner_id),
                    name=name,
                    token_hash=token_hash,
                    capabilities_json=json.dumps(sorted(set(capabilities))),
                    paired_at=now,
                    last_seen_at=now,
                )
            )
        found = self.get_worker(worker_id)
        assert found is not None
        return found

    def get_worker(self, worker_id: str, *, live_since: datetime | None = None) -> Worker | None:
        with self.db.connect() as conn:
            row = one(conn.execute(select(workers).where(workers.c.id == worker_id)))
        return None if row is None else _worker(row, live_since=live_since)

    def worker_for_token(self, token_hash: str) -> Worker | None:
        """The worker a token belongs to -- never a revoked one."""
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(workers).where(
                        workers.c.token_hash == token_hash, workers.c.revoked_at.is_(None)
                    )
                )
            )
        return None if row is None else _worker(row)

    def touch_worker(self, worker_id: str, capabilities: list[str] | None = None) -> None:
        """It was just heard from; with ``capabilities``, that is what it builds now."""
        values: dict[str, Any] = {"last_seen_at": utcnow().isoformat()}
        if capabilities is not None:
            values["capabilities_json"] = json.dumps(sorted(set(capabilities)))
        with self.db.begin() as conn:
            conn.execute(update(workers).where(workers.c.id == worker_id).values(**values))

    def list_workers(
        self, owner_id: str | None, *, live_since: datetime | None = None
    ) -> list[Worker]:
        with self.db.connect() as conn:
            found = rows(
                conn.execute(
                    select(workers)
                    .where(workers.c.owner_id == _owner(owner_id), workers.c.revoked_at.is_(None))
                    .order_by(workers.c.paired_at)
                )
            )
        return [_worker(r, live_since=live_since) for r in found]

    def revoke_worker(self, owner_id: str | None, worker_id: str) -> bool:
        """Stop a worker; another account's is not found. Its builds go back in the queue."""
        with self.db.begin() as conn:
            done = conn.execute(
                update(workers)
                .where(
                    workers.c.id == worker_id,
                    workers.c.owner_id == _owner(owner_id),
                    workers.c.revoked_at.is_(None),
                )
                .values(revoked_at=utcnow().isoformat())
            ).rowcount
            if done:
                conn.execute(
                    update(worker_tasks)
                    .where(worker_tasks.c.worker_id == worker_id, worker_tasks.c.state == "running")
                    .values(state="queued", worker_id=None, claimed_at=None)
                )
        return bool(done)

    def delete_workers_of(self, owner_id: str) -> None:
        """An account going: its machines, codes and builds with it."""
        with self.db.begin() as conn:
            for table in (workers, worker_codes, worker_tasks):
                conn.execute(delete(table).where(table.c.owner_id == owner_id))

    # -- builds ------------------------------------------------------------------------

    def enqueue_worker_task(
        self,
        owner_id: str | None,
        job_id: str,
        platform: str,
        commands: list[tuple[str, str]],
        timeout_s: float,
        snapshot: bytes,
    ) -> str:
        task_id = new_job_id()
        with self.db.begin() as conn:
            conn.execute(
                insert(worker_tasks).values(
                    id=task_id,
                    owner_id=_owner(owner_id),
                    job_id=job_id,
                    platform=platform,
                    commands_json=json.dumps([list(c) for c in commands]),
                    timeout_s=timeout_s,
                    snapshot=snapshot,
                    state="queued",
                    created_at=utcnow().isoformat(),
                )
            )
        return task_id

    def claim_worker_task(
        self, owner_id: str | None, worker_id: str, platforms: list[str]
    ) -> WorkerTask | None:
        """The oldest queued build of this account the worker can do, now its own."""
        if not platforms:
            return None
        with self.db.begin() as conn:
            candidates = rows(
                conn.execute(
                    select(worker_tasks.c.id)
                    .where(
                        worker_tasks.c.owner_id == _owner(owner_id),
                        worker_tasks.c.state == "queued",
                        worker_tasks.c.platform.in_(platforms),
                    )
                    .order_by(worker_tasks.c.created_at)
                )
            )
            for candidate in candidates:
                won = conn.execute(
                    update(worker_tasks)
                    .where(
                        and_(worker_tasks.c.id == candidate["id"], worker_tasks.c.state == "queued")
                    )
                    .values(
                        state="running",
                        worker_id=worker_id,
                        tries=worker_tasks.c.tries + 1,
                        claimed_at=utcnow().isoformat(),
                    )
                ).rowcount
                if won:
                    row = one(
                        conn.execute(
                            select(
                                worker_tasks.c.id,
                                worker_tasks.c.job_id,
                                worker_tasks.c.platform,
                                worker_tasks.c.commands_json,
                                worker_tasks.c.timeout_s,
                            ).where(worker_tasks.c.id == candidate["id"])
                        )
                    )
                    assert row is not None
                    return WorkerTask(
                        id=row["id"],
                        job_id=row["job_id"],
                        platform=row["platform"],
                        commands=[(c[0], c[1]) for c in json.loads(row["commands_json"])],
                        timeout_s=float(row["timeout_s"]),
                    )
        return None

    def worker_task_snapshot(self, task_id: str, worker_id: str) -> bytes | None:
        """The worktree of a build this worker holds -- nobody else's."""
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(worker_tasks.c.snapshot).where(
                        worker_tasks.c.id == task_id,
                        worker_tasks.c.worker_id == worker_id,
                        worker_tasks.c.state == "running",
                    )
                )
            )
        return None if row is None else bytes(row["snapshot"])

    def finish_worker_task(self, task_id: str, worker_id: str, result: TaskResult) -> bool:
        """Record what a build did; only the worker holding it may, and only once."""
        with self.db.begin() as conn:
            done = conn.execute(
                update(worker_tasks)
                .where(
                    worker_tasks.c.id == task_id,
                    worker_tasks.c.worker_id == worker_id,
                    worker_tasks.c.state == "running",
                )
                .values(
                    state="done",
                    exit_code=result.exit_code,
                    output=result.output,
                    seconds=result.seconds,
                    snapshot=b"",  # built: the copy of the worktree has done its job
                    finished_at=utcnow().isoformat(),
                )
            ).rowcount
        return bool(done)

    def worker_task_row(self, task_id: str) -> dict[str, Any] | None:
        """Where a build stands, without its snapshot."""
        cols = [c for c in worker_tasks.c if c.name != "snapshot"]
        with self.db.connect() as conn:
            return one(conn.execute(select(*cols).where(worker_tasks.c.id == task_id)))

    def requeue_worker_task(self, task_id: str) -> None:
        with self.db.begin() as conn:
            conn.execute(
                update(worker_tasks)
                .where(worker_tasks.c.id == task_id, worker_tasks.c.state == "running")
                .values(state="queued", worker_id=None, claimed_at=None)
            )

    def drop_worker_task(self, task_id: str) -> None:
        with self.db.begin() as conn:
            conn.execute(delete(worker_tasks).where(worker_tasks.c.id == task_id))


__all__ = ["WorkerStoreMixin"]
