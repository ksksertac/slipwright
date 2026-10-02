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
from slipwright.schemas.worker import (
    CallAnswer,
    CallFailure,
    TaskResult,
    Worker,
    WorkerCall,
    WorkerTask,
)
from slipwright.store.db import Database, one, rows
from slipwright.store.schema import worker_calls, worker_codes, worker_tasks, workers

#: What a machine says it writes: ``write:<domain>`` (T17.1).
WRITES = "write:"


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
        lent_by=row.get("lent_by") or None,
    )


class WorkerStoreMixin:
    """Requires ``db`` on the host class."""

    db: Database

    # -- codes -------------------------------------------------------------------------

    def create_worker_code(
        self,
        owner_id: str | None,
        secret_hash: str,
        *,
        ttl: timedelta,
        lent_by: str | None = None,
        pair_key: str | None = None,
    ) -> None:
        """Keep the hash of a fresh secret. Any earlier code of the same person stops
        working -- of the same *person*, not the account: a member making a code for their
        laptop must not void the one the owner is halfway through typing on a Mac."""
        now = utcnow()
        mine = (
            worker_codes.c.lent_by.is_(None)
            if lent_by is None
            else worker_codes.c.lent_by == lent_by
        )
        with self.db.begin() as conn:
            conn.execute(
                delete(worker_codes).where(worker_codes.c.owner_id == _owner(owner_id), mine)
            )
            conn.execute(
                insert(worker_codes).values(
                    code_hash=secret_hash,
                    owner_id=_owner(owner_id),
                    created_at=now.isoformat(),
                    expires_at=(now + ttl).isoformat(),
                    lent_by=lent_by,
                    pair_key=pair_key,
                )
            )

    def worker_code_pair_key(self, secret_hash: str) -> str | None:
        """The key that proves the server to a machine pairing through the relay, while the
        code is good. Read, not spent: the pairing that follows spends the code."""
        with self.db.connect() as conn:
            row = one(
                conn.execute(
                    select(worker_codes.c.pair_key, worker_codes.c.expires_at).where(
                        worker_codes.c.code_hash == secret_hash
                    )
                )
            )
        if row is None or datetime.fromisoformat(row["expires_at"]) < utcnow():
            return None
        return row["pair_key"] or None

    def redeem_worker_code(self, secret_hash: str) -> tuple[bool, str | None, str | None]:
        """(valid, owner, lent by): a code is spent by being read, run out or not."""
        with self.db.begin() as conn:
            row = one(
                conn.execute(select(worker_codes).where(worker_codes.c.code_hash == secret_hash))
            )
            if row is None:
                return False, None, None
            conn.execute(delete(worker_codes).where(worker_codes.c.code_hash == secret_hash))
        if datetime.fromisoformat(row["expires_at"]) < utcnow():
            return False, None, None
        return True, row["owner_id"] or None, row.get("lent_by") or None

    # -- workers -----------------------------------------------------------------------

    def add_worker(
        self,
        owner_id: str | None,
        name: str,
        token_hash: str,
        capabilities: list[str],
        *,
        lent_by: str | None = None,
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
                    lent_by=lent_by,
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

    def touch_worker(
        self, worker_id: str, capabilities: list[str] | None = None, *, name: str | None = None
    ) -> None:
        """It was just heard from; with ``capabilities``, that is what it builds now, and
        with ``name``, what it is called now -- a Mac renamed, or one paired by an older
        worker that sent its network address for a name, is put right without re-pairing."""
        values: dict[str, Any] = {"last_seen_at": utcnow().isoformat()}
        if capabilities is not None:
            values["capabilities_json"] = json.dumps(sorted(set(capabilities)))
        if name:
            values["name"] = name
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

    def revoke_worker(
        self, owner_id: str | None, worker_id: str, *, lent_by: str | None = None
    ) -> bool:
        """Stop a worker; another account's is not found, and with ``lent_by`` neither is
        one somebody else lent. Its builds go back in the queue; the calls it held are taken
        back, and whoever waits on them asks the server's own model instead."""
        now = utcnow().isoformat()
        where = [
            workers.c.id == worker_id,
            workers.c.owner_id == _owner(owner_id),
            workers.c.revoked_at.is_(None),
        ]
        if lent_by is not None:
            where.append(workers.c.lent_by == lent_by)
        with self.db.begin() as conn:
            done = conn.execute(update(workers).where(*where).values(revoked_at=now)).rowcount
            if done:
                conn.execute(
                    update(worker_tasks)
                    .where(worker_tasks.c.worker_id == worker_id, worker_tasks.c.state == "running")
                    .values(state="queued", worker_id=None, claimed_at=None)
                )
                conn.execute(
                    update(worker_calls)
                    .where(
                        worker_calls.c.worker_id == worker_id,
                        worker_calls.c.state.in_(("queued", "running")),
                    )
                    .values(state="cancelled", error="the machine was removed", finished_at=now)
                )
        return bool(done)

    def delete_workers_of(self, owner_id: str) -> None:
        """An account going: its machines, codes and builds with it."""
        with self.db.begin() as conn:
            for table in (workers, worker_codes, worker_tasks, worker_calls):
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


    # -- calls (T17.1) ---------------------------------------------------------------------

    def writers_free(self, owner_id: str | None, domain: str, *, live_since: datetime) -> int:
        """How many of this account's machines that write ``domain`` are there now and not
        already busy with a call of it. A call offered when every one of them is busy would
        only sit out the claim window before the server wrote it anyway."""
        wanted = WRITES + domain
        there = sum(
            1
            for w in self.list_workers(owner_id, live_since=live_since)
            if w.online and wanted in w.capabilities
        )
        if not there:
            return 0
        with self.db.connect() as conn:
            busy = len(
                rows(
                    conn.execute(
                        select(worker_calls.c.id).where(
                            worker_calls.c.owner_id == _owner(owner_id),
                            worker_calls.c.domain == domain,
                            worker_calls.c.state.in_(("queued", "running")),
                        )
                    )
                )
            )
        return max(there - busy, 0)

    def enqueue_worker_call(
        self,
        owner_id: str | None,
        job_id: str,
        *,
        role: str,
        domain: str,
        phase: int | None,
        request: dict[str, Any],
    ) -> str:
        call_id = new_job_id()
        with self.db.begin() as conn:
            conn.execute(
                insert(worker_calls).values(
                    id=call_id,
                    owner_id=_owner(owner_id),
                    job_id=job_id,
                    phase=phase,
                    role=role,
                    domain=domain,
                    request_json=json.dumps(request, ensure_ascii=False),
                    state="queued",
                    created_at=utcnow().isoformat(),
                )
            )
        return call_id

    def claim_worker_call(
        self, owner_id: str | None, worker_id: str, capabilities: list[str]
    ) -> WorkerCall | None:
        """The oldest queued call of this account in a domain the machine writes, now its
        own. The same conditional update as a build: two machines polling at once cannot
        both win it."""
        domains = [c[len(WRITES) :] for c in capabilities if c.startswith(WRITES)]
        if not domains:
            return None
        now = utcnow().isoformat()
        with self.db.begin() as conn:
            candidates = rows(
                conn.execute(
                    select(worker_calls.c.id)
                    .where(
                        worker_calls.c.owner_id == _owner(owner_id),
                        worker_calls.c.state == "queued",
                        worker_calls.c.domain.in_(domains),
                    )
                    .order_by(worker_calls.c.created_at)
                )
            )
            for candidate in candidates:
                won = conn.execute(
                    update(worker_calls)
                    .where(
                        and_(worker_calls.c.id == candidate["id"], worker_calls.c.state == "queued")
                    )
                    .values(state="running", worker_id=worker_id, claimed_at=now, heard_at=now)
                ).rowcount
                if won:
                    row = one(
                        conn.execute(
                            select(worker_calls.c.request_json).where(
                                worker_calls.c.id == candidate["id"]
                            )
                        )
                    )
                    assert row is not None
                    return WorkerCall(id=candidate["id"], **json.loads(row["request_json"]))
        return None

    def worker_call_row(self, call_id: str) -> dict[str, Any] | None:
        """Where a call stands, without its request."""
        cols = [c for c in worker_calls.c if c.name != "request_json"]
        with self.db.connect() as conn:
            return one(conn.execute(select(*cols).where(worker_calls.c.id == call_id)))

    def hear_worker_call(self, call_id: str, worker_id: str, text: str) -> bool:
        """The machine holding it is still at it. False when it is not its call any more --
        taken back, or never its -- and the machine should stop."""
        now = utcnow().isoformat()
        with self.db.begin() as conn:
            done = conn.execute(
                update(worker_calls)
                .where(
                    worker_calls.c.id == call_id,
                    worker_calls.c.worker_id == worker_id,
                    worker_calls.c.state == "running",
                )
                .values(heard_at=now, progress=text or None)
            ).rowcount
            conn.execute(update(workers).where(workers.c.id == worker_id).values(last_seen_at=now))
        return bool(done)

    def answer_worker_call(self, call_id: str, worker_id: str, answer: CallAnswer) -> bool:
        """The answer, exactly as the machine's model gave it. Only the machine holding the
        call may give it, and only once."""
        with self.db.begin() as conn:
            done = conn.execute(
                update(worker_calls)
                .where(
                    worker_calls.c.id == call_id,
                    worker_calls.c.worker_id == worker_id,
                    worker_calls.c.state == "running",
                )
                .values(
                    state="done",
                    answer=answer.text,
                    model=answer.model,
                    input_tokens=answer.input_tokens,
                    output_tokens=answer.output_tokens,
                    seconds=answer.seconds,
                    finished_at=utcnow().isoformat(),
                )
            ).rowcount
        return bool(done)

    def fail_worker_call(self, call_id: str, worker_id: str, failure: CallFailure) -> bool:
        with self.db.begin() as conn:
            done = conn.execute(
                update(worker_calls)
                .where(
                    worker_calls.c.id == call_id,
                    worker_calls.c.worker_id == worker_id,
                    worker_calls.c.state == "running",
                )
                .values(
                    state="failed",
                    error=failure.message,
                    error_kind=failure.kind,
                    finished_at=utcnow().isoformat(),
                )
            ).rowcount
        return bool(done)

    def take_back_worker_call(self, call_id: str, why: str) -> bool:
        """The server stops waiting: nobody claimed it, or its machine went quiet. True when
        it was still open -- an answer that landed a moment ago wins, and is read instead."""
        with self.db.begin() as conn:
            done = conn.execute(
                update(worker_calls)
                .where(
                    worker_calls.c.id == call_id,
                    worker_calls.c.state.in_(("queued", "running")),
                )
                .values(state="cancelled", error=why, finished_at=utcnow().isoformat())
            ).rowcount
        return bool(done)

    def open_worker_calls(self, owner_id: str | None) -> list[dict[str, Any]]:
        """This account's calls a machine is writing now, with the machine writing each:
        what *Right now* and the Machines page show."""
        with self.db.connect() as conn:
            return rows(
                conn.execute(
                    select(
                        worker_calls.c.id,
                        worker_calls.c.job_id,
                        worker_calls.c.phase,
                        worker_calls.c.role,
                        worker_calls.c.worker_id,
                        worker_calls.c.progress,
                        worker_calls.c.claimed_at,
                        workers.c.name.label("worker_name"),
                    )
                    .select_from(
                        worker_calls.outerjoin(workers, workers.c.id == worker_calls.c.worker_id)
                    )
                    .where(
                        worker_calls.c.owner_id == _owner(owner_id),
                        worker_calls.c.state == "running",
                    )
                    .order_by(worker_calls.c.claimed_at)
                )
            )

    def prune_worker_calls(self, older_than: datetime) -> None:
        """A finished call carries a whole prompt and answer; once read it is history
        nobody asks for, and the next development's prompts would pile up behind it."""
        with self.db.begin() as conn:
            conn.execute(
                delete(worker_calls).where(
                    worker_calls.c.state.in_(("done", "failed", "cancelled")),
                    worker_calls.c.created_at < older_than.isoformat(),
                )
            )


__all__ = ["WRITES", "WorkerStoreMixin"]
