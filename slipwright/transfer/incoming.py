"""The receiving side: a code on the screen, then everything it lets in, or nothing.

What arrives is staged first -- rows in files, checkouts as bundles -- in a private
temporary directory, never the work directory a project's own commands can reach: the
settings among them are model keys and Git tokens with the sender's encryption taken off.
Only the last part, ``finish``, writes anything real, and it writes all of it or none:
checkouts are rebuilt first, then every row goes in one transaction, and a failure in
either removes the checkouts again.

Nothing here is persisted. A code lives thirty seconds and a transfer a few minutes; a
server restarted in between has simply forgotten them, which is the right answer for
both. That is also why it needs no migration: the database learns about a transfer only
when it is over.

Everything that arrives is somebody else's: it is rewritten to belong to whoever showed
the code. Users, sessions and memberships never come at all (``rows.py``).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import and_, delete, insert, select

from slipwright.schemas.job import new_job_id, utcnow
from slipwright.schemas.project import Project
from slipwright.store.schema import (
    attachments,
    job_history,
    jobs,
    project_briefs,
    projects,
    settings,
    standards_pages,
    test_runs,
    translations,
)
from slipwright.store.settings import INSTALLATION
from slipwright.transfer import rows as R
from slipwright.transfer.channel import ChannelError, Part, new_code, receive_handshake, unseal
from slipwright.workspace import git as g
from slipwright.workspace.worktree import rmtree

if TYPE_CHECKING:
    from slipwright.engine import Engine

log = logging.getLogger(__name__)

#: How long a code is shown before the next one replaces it.
SHOWN_S = 30
#: ...and how long it still works after that: somebody half-way through typing the old
#: one when it changes is not made to start again.
GRACE_S = 30
#: A transfer nobody has sent a part of for this long is given up on and its staging
#: removed.
IDLE_S = 10 * 60
#: The largest part accepted: a chunk of a checkout (``rows.CHUNK``) and its envelope.
MAX_PART = R.CHUNK + 1024 * 1024
#: Transfers from here kept for the page to ask about.
SENDINGS_KEPT = 20
_BLOB = re.compile(r"^(repo|tree)/([A-Za-z0-9_-]{1,64})\.(bundle|tar\.gz)$")


class Rejected(ValueError):
    """A part or a pairing the receiver will not take; the message says why."""


@dataclass
class Offer:
    """A code on somebody's screen."""

    slot: str
    secret: str
    owner: str | None
    admin: bool
    made: float = field(default_factory=time.monotonic)

    def live(self, now: float) -> bool:
        return now - self.made < SHOWN_S + GRACE_S


@dataclass
class Receiving:
    """One transfer arriving."""

    owner: str | None
    admin: bool
    key: bytes
    sender: str
    staging: Path
    id: str = field(default_factory=new_job_id)
    seq: int = 0
    state: str = "receiving"  # receiving | importing | done | failed
    error: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)
    settings: list[dict[str, Any]] = field(default_factory=list)
    progress: R.Progress = field(default_factory=R.Progress)
    summary: dict[str, Any] = field(default_factory=dict)
    touched: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


def _key(owner: str | None) -> str:
    return owner or ""


class Desk:
    """The codes on show and the transfers under way, for one running server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._offers: dict[str, Offer] = {}
        self._incoming: dict[str, Receiving] = {}
        self.sending: dict[str, Any] = {}  # outgoing.Sending by id, newest last

    def keep_sending(self, sending: Any) -> None:
        """Remember a transfer from here for the page to poll; only the latest few are
        worth keeping, and a running one is never dropped."""
        with self._lock:
            self.sending[sending.id] = sending
            ended = [k for k, s in self.sending.items() if s.state != "running"]
            for k in ended[: max(len(self.sending) - SENDINGS_KEPT, 0)]:
                del self.sending[k]

    # -- codes ---------------------------------------------------------------------------

    def offer(self, owner: str | None, *, admin: bool) -> tuple[str, int]:
        """A fresh code for this account, and how many seconds it is shown for. The last
        one keeps working through its grace; any older one stops."""
        code, slot, secret = new_code()
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            mine = sorted(
                (o for o in self._offers.values() if _key(o.owner) == _key(owner)),
                key=lambda o: o.made,
            )
            for old in mine[:-1]:
                del self._offers[old.slot]
            self._offers[slot] = Offer(slot, secret, owner, admin)
        return code, SHOWN_S

    def withdraw(self, owner: str | None) -> None:
        with self._lock:
            for slot in [s for s, o in self._offers.items() if _key(o.owner) == _key(owner)]:
                del self._offers[slot]

    def pair(self, slot: str, message: bytes, sender: str) -> tuple[Receiving, bytes]:
        """Run the exchange for the code in ``slot``: (the transfer, the answer to send
        back). The code is spent whether the exchange works or not -- a wrong guess is
        the only guess."""
        with self._lock:
            self._sweep(time.monotonic())
            offer = self._offers.pop(slot.upper(), None)
        if offer is None:
            raise Rejected("this code has been used or has run out; type the one on screen now")
        try:
            answer, key = receive_handshake(offer.secret, message)
        except ChannelError as exc:
            raise Rejected(str(exc)) from exc
        staging = Path(tempfile.mkdtemp(prefix="slipwright-incoming-"))
        receiving = Receiving(offer.owner, offer.admin, key, sender[:120], staging)
        receiving.progress.finish("pair")
        with self._lock:
            # a receiver takes one transfer at a time per account: a second sender with a
            # second code replaces nothing that is already arriving
            for other in self._incoming.values():
                if _key(other.owner) == _key(offer.owner) and other.state in (
                    "receiving",
                    "importing",
                ):
                    shutil.rmtree(staging, ignore_errors=True)
                    raise Rejected("another transfer is already arriving here")
            self._incoming[receiving.id] = receiving
            # a code that worked ends the showing of codes
            for s in [s for s, o in self._offers.items() if _key(o.owner) == _key(offer.owner)]:
                del self._offers[s]
        return receiving, answer

    # -- transfers -----------------------------------------------------------------------

    def receiving(self, session: str) -> Receiving | None:
        with self._lock:
            self._sweep(time.monotonic())
            return self._incoming.get(session)

    def latest(self, owner: str | None) -> Receiving | None:
        """The transfer arriving for this account, or the one that last did."""
        with self._lock:
            mine = [r for r in self._incoming.values() if _key(r.owner) == _key(owner)]
        return max(mine, key=lambda r: r.touched, default=None)

    def _sweep(self, now: float) -> None:
        for slot in [s for s, o in self._offers.items() if not o.live(now)]:
            del self._offers[slot]
        for sid, rec in list(self._incoming.items()):
            if now - rec.touched > IDLE_S:
                shutil.rmtree(rec.staging, ignore_errors=True)
                del self._incoming[sid]


# -- the parts --------------------------------------------------------------------------


def accept(engine: Engine, rec: Receiving, sealed: bytes) -> dict[str, Any]:
    """Take one part. A part that does not open ends the transfer: it was not sent by
    whoever holds the key, or not in this order."""
    with rec.lock:
        if rec.state != "receiving":
            raise Rejected(f"this transfer is {rec.state}")
        if len(sealed) > MAX_PART:
            _fail(rec, "a part larger than any sender makes")
        try:
            part = unseal(rec.key, rec.id, rec.seq, sealed)
        except ChannelError as exc:
            _fail(rec, str(exc))
        rec.seq += 1
        rec.touched = time.monotonic()
        kind = part.header.get("kind")
        if kind == "manifest":
            return _manifest(rec, part)
        if not rec.manifest:
            _fail(rec, "a part before the manifest")
        if kind == "rows":
            return _rows(rec, part)
        if kind == "blob":
            return _blob(rec, part)
        if kind == "finish":
            rec.state = "importing"
            rec.progress.begin("finish")
            try:
                rec.summary = import_transfer(engine, rec)
            except Exception as exc:
                log.exception("transfer from %s: import failed", rec.sender)
                rec.state, rec.error = "failed", f"could not write what arrived: {exc}"
                shutil.rmtree(rec.staging, ignore_errors=True)
                raise Rejected(rec.error) from exc
            for step in rec.progress.steps:
                rec.progress.finish(step.key)
            rec.state = "done"
            shutil.rmtree(rec.staging, ignore_errors=True)
            return rec.summary
        _fail(rec, f"a part of unknown kind {kind!r}")
    raise AssertionError("unreachable")  # pragma: no cover


def _fail(rec: Receiving, why: str) -> None:
    rec.state, rec.error = "failed", why
    shutil.rmtree(rec.staging, ignore_errors=True)
    raise Rejected(why)


def _manifest(rec: Receiving, part: Part) -> dict[str, Any]:
    if rec.manifest:
        _fail(rec, "a second manifest")
    header = part.header
    counts = header.get("counts") or {}
    if not isinstance(counts, dict) or not isinstance(header.get("repos"), dict):
        _fail(rec, "a manifest without its lists")
    rec.manifest = header
    for table, step in R.STEP_OF.items():
        if step is not None:
            rec.progress.step(step).total += int(counts.get(table, 0))
    rec.progress.step("repos").total = len(header["repos"])
    return {"ok": True}


def _rows(rec: Receiving, part: Part) -> dict[str, Any]:
    table = part.header.get("table")
    if table not in R.TABLES:
        _fail(rec, f"rows of a table that is not carried: {table!r}")
    found = json.loads(part.body)
    if not isinstance(found, list):
        _fail(rec, "rows that are not a list")
    if table == "settings":
        # never written to disk: these are the account's keys in the clear
        rec.settings.extend(found)
    else:
        with (rec.staging / f"{table}.jsonl").open("a", encoding="utf-8") as out:
            for row in found:
                out.write(json.dumps(row) + "\n")
    step = R.STEP_OF[str(table)]
    if step is not None:
        rec.progress.advance(step, len(found))
    return {"ok": True}


def _blob(rec: Receiving, part: Part) -> dict[str, Any]:
    name = str(part.header.get("name", ""))
    match = _BLOB.match(name)
    if match is None:
        _fail(rec, f"a file the receiver does not know where to put: {name!r}")
        raise AssertionError  # pragma: no cover - _fail raises
    kind, owner_id, _ext = match.groups()
    known = rec.manifest["repos"] if kind == "repo" else rec.manifest.get("trees", {})
    if owner_id not in known:
        _fail(rec, f"a checkout of something not in the manifest: {name!r}")
    target = rec.staging / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab") as out:
        out.write(part.body)
    if part.header.get("last") and kind == "repo" and name.endswith(".bundle"):
        rec.progress.advance("repos")
    return {"ok": True}


# -- writing it ---------------------------------------------------------------------------


def _staged(rec: Receiving, table: str) -> list[dict[str, Any]]:
    path = rec.staging / f"{table}.jsonl"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [R.decode(json.loads(line)) for line in handle if line.strip()]


def _free(path: Path) -> Path:
    """``path``, or the first ``path-N`` beside it that nothing occupies. Something
    already there is never written over: it is not ours to know what it is."""
    candidate, n = path, 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}-{n}")
    return candidate


def _overlay(tree: Path, archive: Path) -> None:
    """Lay a snapshot over a checkout: its files as they were, and the tracked files it
    did not have -- deleted there and not yet committed -- deleted here too."""
    with tarfile.open(archive, "r:gz") as tar:
        names = {m.name for m in tar.getmembers() if m.isfile()}
        tar.extractall(tree, filter="data")
    tracked = g.run(tree, "ls-files", "-z").stdout.split("\0")
    for name in filter(None, tracked):
        if name not in names:
            (tree / name).unlink(missing_ok=True)


def _rebuild(rec: Receiving, project_id: str, meta: dict[str, Any], target: Path) -> None:
    target.mkdir(parents=True)
    g.run(target, "init", "-q")
    bundle = rec.staging / "repo" / f"{project_id}.bundle"
    if bundle.is_file():
        g.run(
            target,
            "fetch",
            "-q",
            "--update-head-ok",
            str(bundle),
            "+refs/heads/*:refs/heads/*",
            "+refs/tags/*:refs/tags/*",
        )
        head = meta.get("head")
        if isinstance(head, str) and head.startswith("refs/heads/"):
            g.run(target, "symbolic-ref", "HEAD", head)
        g.run(target, "reset", "-q", "--hard")
    snapshot = rec.staging / "repo" / f"{project_id}.tar.gz"
    if snapshot.is_file():
        _overlay(target, snapshot)
    origin = meta.get("origin")
    if isinstance(origin, str) and origin:
        g.set_remote(target, "origin", _without_credentials(origin))


def _without_credentials(url: str) -> str:
    """A remote with a token written into it is put back without one: the engine
    supplies credentials per push, and a token left in ``.git/config`` is readable by
    the project's own build commands."""
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and "@" in parts.netloc:
        return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))
    return url


def import_transfer(engine: Engine, rec: Receiving) -> dict[str, Any]:
    """Write what arrived: checkouts, then every row in one transaction. All or nothing."""
    db = engine.raw_store.db
    manifest = rec.manifest

    with db.connect() as conn:
        have_projects = {r[0] for r in conn.execute(select(projects.c.id))}
        have_jobs = {r[0] for r in conn.execute(select(jobs.c.id))}
        have_runs = {r[0] for r in conn.execute(select(test_runs.c.id))}
        have_files = {r[0] for r in conn.execute(select(attachments.c.id))}

    project_rows = _staged(rec, "projects")
    # a project that is already here -- moved once before -- is left as it is, and
    # everything of it with it: two copies of one project would share its branches
    skipped = [r["id"] for r in project_rows if r["id"] in have_projects]
    moving = [r for r in project_rows if r["id"] not in have_projects]
    kept = {r["id"] for r in moving}

    made: list[Path] = []
    repo_of: dict[str, Path] = {}
    tree_of: dict[str, Path] = {}
    try:
        for row in moving:
            pid = row["id"]
            target = _free(engine.repos_root / pid)
            made.append(target)
            _rebuild(rec, pid, manifest["repos"].get(pid, {}), target)
            repo_of[pid] = target
        for job_id, tree in (manifest.get("trees") or {}).items():
            pid = tree.get("project")
            if pid not in kept or job_id in have_jobs:
                continue
            path = _free(engine.workspace.worktrees_root / job_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            g.run(repo_of[pid], "worktree", "add", "-q", str(path), str(tree["branch"]))
            made.append(path)
            snapshot = rec.staging / "tree" / f"{job_id}.tar.gz"
            if snapshot.is_file():
                _overlay(path, snapshot)
            tree_of[job_id] = path

        counts = _write(
            engine, rec, moving, kept, repo_of, tree_of, have_jobs, have_runs, have_files
        )
    except Exception:
        for path in reversed(made):
            if path.exists():
                rmtree(path)
        raise
    return {
        "moved": sorted(kept),
        "skipped": skipped,
        "counts": counts,
        "projects": [p["name"] for p in manifest.get("projects", []) if p.get("id") in kept],
    }


def _write(
    engine: Engine,
    rec: Receiving,
    moving: list[dict[str, Any]],
    kept: set[str],
    repo_of: dict[str, Path],
    tree_of: dict[str, Path],
    have_jobs: set[str],
    have_runs: set[str],
    have_files: set[str],
) -> dict[str, int]:
    store = engine.raw_store
    owner = rec.owner
    counts = {table: 0 for table in R.TABLES}
    with store.db.begin() as conn:
        for row in moving:
            project = Project.model_validate_json(row["data_json"])
            project = project.model_copy(
                update={"owner_id": owner, "repo_path": repo_of[row["id"]]}
            )
            conn.execute(
                insert(projects).values(
                    {**row, "owner_id": owner, "data_json": project.model_dump_json()}
                )
            )
            counts["projects"] += 1
        for row in _staged(rec, "project_briefs"):
            if row["project_id"] in kept:
                conn.execute(insert(project_briefs).values(row))
                counts["project_briefs"] += 1
        moved_jobs: set[str] = set()
        for row in _staged(rec, "jobs"):
            if row["project_id"] not in kept or row["id"] in have_jobs:
                continue
            tree = tree_of.get(row["id"])
            if tree is None and row["worktree_path"]:
                # recorded there but not sent -- gone from the sender's disk, or a finished
                # development's: recorded here the same way, so the engine treats it
                # exactly as it would have there
                tree = engine.workspace.worktrees_root / row["id"]
            conn.execute(
                insert(jobs).values(
                    {
                        **row,
                        "owner_id": owner,
                        "repo_path": str(repo_of[row["project_id"]]),
                        "worktree_path": str(tree) if tree is not None else None,
                        # a port is this machine's to hand out; one is given when needed
                        "port": None,
                    }
                )
            )
            moved_jobs.add(row["id"])
            counts["jobs"] += 1
        for row in _staged(rec, "job_history"):
            if row["job_id"] in moved_jobs:
                # the sequence is the receiver's: rows go in in the order they were made
                conn.execute(
                    insert(job_history).values({k: v for k, v in row.items() if k != "seq"})
                )
                counts["job_history"] += 1
        for row in _staged(rec, "test_runs"):
            if row["project_id"] in kept and row["id"] not in have_runs:
                conn.execute(insert(test_runs).values(row))
                counts["test_runs"] += 1
        for row in _staged(rec, "attachments"):
            if row["project_id"] in kept and row["id"] not in have_files:
                conn.execute(insert(attachments).values({**row, "owner_id": owner}))
                counts["attachments"] += 1
        page_owner = owner or INSTALLATION
        for row in _staged(rec, "standards_pages"):
            # the moved page replaces this account's own rewrite of the same page
            conn.execute(
                delete(standards_pages).where(
                    and_(
                        standards_pages.c.owner_id == page_owner,
                        standards_pages.c.domain == row["domain"],
                        standards_pages.c.name == row["name"],
                    )
                )
            )
            conn.execute(
                insert(standards_pages).values({**row, "id": new_job_id(), "owner_id": page_owner})
            )
            counts["standards_pages"] += 1
        for row in _staged(rec, "translations"):
            exists = conn.execute(
                select(translations.c.lang).where(
                    translations.c.lang == row["lang"], translations.c.source == row["source"]
                )
            ).first()
            if exists is None:
                conn.execute(insert(translations).values(row))
                counts["translations"] += 1
        counts["settings"] = _write_settings(engine, rec, conn)
    return counts


def _write_settings(engine: Engine, rec: Receiving, conn: Any) -> int:
    """The account's settings become the receiving account's; the installation's only
    reach an installation whose administrator showed the code, and only from one whose
    administrator sent them."""
    store = engine.raw_store
    mine = rec.owner or INSTALLATION
    written = 0
    now = utcnow().isoformat()
    for item in rec.settings:
        name = str(item.get("name", ""))
        if not name or not R.carried(name):
            continue
        if item.get("scope") == "installation":
            if not (rec.admin and rec.manifest.get("admin")):
                continue
            user_id = INSTALLATION
        else:
            user_id = mine
        value = str(item["value_json"])
        secret = bool(item.get("secret"))
        json.loads(value)  # a value that is not JSON is not written
        if secret:
            value = store.secret_box.encrypt(value)
        conn.execute(
            store.db.upsert(
                settings,
                {
                    "user_id": user_id,
                    "name": name,
                    "value_json": value,
                    "encrypted": int(secret),
                    "updated_at": now,
                },
                key=["user_id", "name"],
                update=["value_json", "encrypted", "updated_at"],
            )
        )
        written += 1
    return written


__all__ = [
    "GRACE_S",
    "SHOWN_S",
    "Desk",
    "Offer",
    "Receiving",
    "Rejected",
    "accept",
    "import_transfer",
]
