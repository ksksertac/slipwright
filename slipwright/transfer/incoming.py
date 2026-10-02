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

A project that is already here -- moved once before, and worked on since on the other
side -- is replaced by what arrived: the sender's is the copy somebody is carrying on with.
Never one that belongs to another account here, never under a development running here,
and never over a development that was only ever started here: that would be work lost
without anybody having been asked, so the transfer stops and says which.
"""

from __future__ import annotations

import contextlib
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

from slipwright.providers import codex
from slipwright.schemas.job import APPROVAL_STATES, TERMINAL_STATES, JobState, new_job_id, utcnow
from slipwright.schemas.project import Project
from slipwright.store.schema import (
    attachments,
    job_history,
    job_messages,
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

#: How long a code is shown before the next one replaces it: time to walk to the other
#: computer and type it there.
SHOWN_S = 180
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
#: A ChatGPT sign-in is a small JSON file; anything far larger is not one.
MAX_SIGN_IN = 256 * 1024
#: A development in one of these is not running: replacing its project here takes
#: nothing out from under a model call (the sender's own rule, ``outgoing.IDLE``).
IDLE = (
    APPROVAL_STATES
    | TERMINAL_STATES
    | {
        JobState.AWAITING_BUILDER,
        JobState.CREATED,
        JobState.PAUSED,
    }
)


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
    # the settings' JSON lines as they arrive: in memory, never on disk (see _rows)
    settings_raw: bytearray = field(default_factory=bytearray)
    # the ChatGPT sign-in (Codex's auth.json), held like the settings: never staged
    sign_in: bytes | None = None
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
            # one transfer at a time per account. One being written is left to finish; one
            # still arriving is given up for this one -- the code that opened this was shown
            # after it, so whoever is at the screen has moved on, and a sender that died
            # half-way must not hold the door shut until its transfer times out
            for other in list(self._incoming.values()):
                if _key(other.owner) != _key(offer.owner):
                    continue
                if other.state == "importing":
                    shutil.rmtree(staging, ignore_errors=True)
                    raise Rejected("another transfer is being written here; wait for it")
                if other.state == "receiving":
                    other.state, other.error = "failed", "replaced by a newer transfer"
                    shutil.rmtree(other.staging, ignore_errors=True)
                    log.warning("transfer from %s replaced by a newer one", other.sender)
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
            return _manifest(engine, rec, part)
        if not rec.manifest:
            _fail(rec, "a part before the manifest")
        if kind == "rows":
            return _rows(rec, part)
        if kind == "blob":
            return _blob(rec, part)
        if kind == "sign_in":
            if len(part.body) > MAX_SIGN_IN:
                _fail(rec, "a sign-in larger than any sign-in is")
            rec.sign_in = bytes(part.body)
            return {"ok": True}
        if kind == "abort":
            why = str(part.header.get("reason") or "the sender gave up")
            log.warning("transfer from %s abandoned by its sender: %s", rec.sender, why)
            rec.state, rec.error = "failed", why
            shutil.rmtree(rec.staging, ignore_errors=True)
            return {"ok": True}
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
    log.warning("transfer from %s refused: %s", rec.sender, why)
    rec.state, rec.error = "failed", why
    shutil.rmtree(rec.staging, ignore_errors=True)
    raise Rejected(why)


def _manifest(engine: Engine, rec: Receiving, part: Part) -> dict[str, Any]:
    if rec.manifest:
        _fail(rec, "a second manifest")
    header = part.header
    counts = header.get("counts") or {}
    if not isinstance(counts, dict) or not isinstance(header.get("repos"), dict):
        _fail(rec, "a manifest without its lists")
    # asked now, before the sender spends minutes on checkouts that could not be written;
    # asked again when they are, since this computer can move on in between
    sent_jobs = header.get("jobs")
    if isinstance(sent_jobs, dict):
        problem = _cannot_replace(
            engine, rec, {str(k): {str(j) for j in v} for k, v in sent_jobs.items()}
        )
        if problem:
            _fail(rec, problem)
    rec.manifest = header
    for table, step in R.STEP_OF.items():
        if step is not None:
            rec.progress.step(step).total += int(counts.get(table, 0))
    rec.progress.step("repos").total = len(header["repos"])
    return {"ok": True}


def _rows(rec: Receiving, part: Part) -> dict[str, Any]:
    """A run of a table's JSON lines, cut wherever the sender's part was full. Joined
    as bytes; a row is only read once the whole table is in (``_staged``)."""
    table = part.header.get("table")
    if table not in R.TABLES:
        _fail(rec, f"rows of a table that is not carried: {table!r}")
    if table == "settings":
        # never written to disk: these are the account's keys in the clear
        rec.settings_raw += part.body
        if part.header.get("last"):
            rec.settings = [
                json.loads(line) for line in bytes(rec.settings_raw).splitlines() if line.strip()
            ]
            rec.settings_raw.clear()
    else:
        with (rec.staging / f"{table}.jsonl").open("ab") as out:
            out.write(part.body)
    step = R.STEP_OF[str(table)]
    if step is not None:
        rec.progress.advance(step, int(part.header.get("rows") or 0))
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


def _clone(
    engine: Engine, owner: str | None, project: Project, meta: dict[str, Any], target: Path
) -> None:
    """A project sent without its checkout, cloned from where it is pushed -- on this
    account's Git token here, as a project created here would be."""
    url = meta.get("origin") or project.effective_clone_url
    if not isinstance(url, str) or not url:
        raise ValueError(f"{project.name} came without a checkout or a remote to clone")
    url = _without_credentials(url)
    mine = engine.for_user(owner)
    source = project.source or mine.default_source()
    try:
        g.clone(mine._authenticated(url, source), target)
    except g.GitError as exc:
        raise ValueError(
            f"could not clone {project.name} from {url}: add a token for it under "
            "Settings -> Sources here, or send it with its checkout"
        ) from exc
    g.set_remote(target, "origin", url)
    head = meta.get("head")
    if isinstance(head, str) and head.startswith("refs/heads/"):
        branch = head.removeprefix("refs/heads/")
        g.run(target, "checkout", "-q", branch, check=False)


def _without_credentials(url: str) -> str:
    """A remote with a token written into it is put back without one: the engine
    supplies credentials per push, and a token left in ``.git/config`` is readable by
    the project's own build commands."""
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and "@" in parts.netloc:
        return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[1]))
    return url


def _replaceable(engine: Engine, rec: Receiving, project_ids: list[str]) -> list[str]:
    """Which of these projects are here already, as this account's: they are replaced.
    One that is another account's here is not ours to touch and is left as it was."""
    if not project_ids:
        return []
    with engine.raw_store.db.connect() as conn:
        found = conn.execute(
            select(projects.c.id, projects.c.owner_id).where(projects.c.id.in_(project_ids))
        ).all()
    return [pid for pid, owner in found if _key(owner) == _key(rec.owner)]


def _cannot_replace(engine: Engine, rec: Receiving, sent_jobs: dict[str, set[str]]) -> str | None:
    """Why the projects already here cannot be replaced by the ones arriving, or None.

    A development running here would have its checkout pulled from under a model call.
    One that only exists here -- started after the last move -- would be deleted with
    nobody having said so. Both stop the transfer, by name, before anything is written."""
    running: list[str] = []
    only_here: list[str] = []
    for pid in _replaceable(engine, rec, list(sent_jobs)):
        for job in engine.raw_store.list(pid):
            if job.state not in IDLE:
                running.append(job.title)
            elif job.id not in sent_jobs[pid]:
                only_here.append(job.title)
    if running:
        return (
            f"{', '.join(running[:3])} is running on this computer; stop it or let it reach "
            "a gate here, then move again"
        )
    if only_here:
        return (
            f"{', '.join(only_here[:3])} was started on this computer and the sender does not "
            "have it; moving would delete it. Delete it here, or move it to the sender first"
        )
    return None


def _jobs_sent(rec: Receiving) -> dict[str, set[str]]:
    sent: dict[str, set[str]] = {}
    for row in _staged(rec, "jobs"):
        sent.setdefault(str(row["project_id"]), set()).add(str(row["id"]))
    for row in _staged(rec, "projects"):
        sent.setdefault(str(row["id"]), set())
    return sent


def import_transfer(engine: Engine, rec: Receiving) -> dict[str, Any]:
    """Write what arrived: checkouts, then every row in one transaction. All or nothing."""
    db = engine.raw_store.db
    manifest = rec.manifest

    problem = _cannot_replace(engine, rec, _jobs_sent(rec))
    if problem:
        raise ValueError(problem)
    project_rows = _staged(rec, "projects")
    replacing = set(_replaceable(engine, rec, [str(r["id"]) for r in project_rows]))
    # what of the copy here goes once the new one is written: read now, removed after
    old = {
        pid: (engine.raw_store.get_project(pid), engine.raw_store.list(pid)) for pid in replacing
    }
    files_sent = bool(rec.manifest.get("attachments", True))

    with db.connect() as conn:
        have_projects = {r[0] for r in conn.execute(select(projects.c.id))}
        # the rows of a project being replaced are deleted before the new ones go in, so
        # they do not count as already here
        going = list(replacing)
        have_jobs = {
            r[0] for r in conn.execute(select(jobs.c.id).where(jobs.c.project_id.notin_(going)))
        }
        have_runs = {
            r[0]
            for r in conn.execute(
                select(test_runs.c.id).where(test_runs.c.project_id.notin_(going))
            )
        }
        files = select(attachments.c.id)
        if files_sent:
            files = files.where(attachments.c.project_id.notin_(going))
        have_files = {r[0] for r in conn.execute(files)}

    # a project that is another account's here is left as it is, and everything of it
    # with it: two copies of one project would share its branches
    skipped = [r["id"] for r in project_rows if r["id"] in have_projects - replacing]
    moving = [r for r in project_rows if r["id"] not in have_projects or r["id"] in replacing]
    kept = {r["id"] for r in moving}

    made: list[Path] = []
    repo_of: dict[str, Path] = {}
    tree_of: dict[str, Path] = {}
    try:
        for row in moving:
            pid = row["id"]
            target = _free(engine.repos_root / pid)
            made.append(target)
            meta = manifest["repos"].get(pid, {})
            if manifest.get("checkouts", True):
                _rebuild(rec, pid, meta, target)
            else:
                _clone(
                    engine, rec.owner, Project.model_validate_json(row["data_json"]), meta, target
                )
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
            engine,
            rec,
            moving,
            kept,
            repo_of,
            tree_of,
            have_jobs,
            have_runs,
            have_files,
            replacing=replacing,
            files_sent=files_sent,
        )
    except Exception:
        for path in reversed(made):
            if path.exists():
                rmtree(path)
        raise
    # the rows are the new copy's now; what the old one had on disk goes
    for project, gone in old.values():
        _clear_old(engine, project, gone)
    named = {str(p.get("id")): str(p.get("name")) for p in manifest.get("projects", [])}
    return {
        "moved": sorted(kept),
        "skipped": skipped,
        "replaced": [named.get(pid, pid) for pid in sorted(replacing)],
        "counts": counts,
        "projects": [p["name"] for p in manifest.get("projects", []) if p.get("id") in kept],
        "chatgpt": _sign_in(engine, rec),
    }


def _clear_old(engine: Engine, project: Project, gone: list[Any]) -> None:
    """The worktrees, branches and checkout of the copy that was replaced. Best effort:
    the new copy is written and works; something left on the disk is only space."""
    for job in gone:
        if job.worktree_path is None and job.port is None:
            continue
        try:
            engine.workspace.destroy(job)
        except Exception as exc:  # noqa: BLE001 - one bad worktree must not stop the rest
            log.warning("transfer: replacing %s: job %s: %s", project.name, job.id, exc)
    try:
        engine._remove_our_checkout(project)
    except Exception as exc:  # noqa: BLE001
        log.warning("transfer: replacing %s: its old checkout: %s", project.name, exc)


def _sign_in(engine: Engine, rec: Receiving) -> str | None:
    """Put the ChatGPT sign-in that arrived where this account's Codex reads it.

    Only into an empty place: a sign-in already here is somebody's choice on this
    computer, perhaps another ChatGPT account, and is kept. Only where the feature is on
    -- a hosted server has it off and is never handed one. ``moved``, ``kept`` or None
    when none came or it could not be put anywhere."""
    if rec.sign_in is None:
        return None
    home = engine.for_user(rec.owner).codex_home()
    if home is None:
        return None
    if codex.signed_in(home):
        return "kept"
    home.mkdir(parents=True, exist_ok=True)
    target = home / "auth.json"
    target.write_bytes(rec.sign_in)
    with contextlib.suppress(OSError):
        target.chmod(0o600)  # a session token; nobody else on the machine reads it
    return "moved"


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
    *,
    replacing: set[str] | frozenset[str] = frozenset(),
    files_sent: bool = True,
) -> dict[str, int]:
    store = engine.raw_store
    owner = rec.owner
    counts = {table: 0 for table in R.TABLES}
    with store.db.begin() as conn:
        if replacing:
            going = list(replacing)
            # the history and the messages of its developments go with them (cascade)
            conn.execute(delete(test_runs).where(test_runs.c.project_id.in_(going)))
            if files_sent:
                conn.execute(delete(attachments).where(attachments.c.project_id.in_(going)))
            conn.execute(delete(jobs).where(jobs.c.project_id.in_(going)))
            conn.execute(delete(project_briefs).where(project_briefs.c.project_id.in_(going)))
            conn.execute(delete(projects).where(projects.c.id.in_(going)))
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
        for row in _staged(rec, "job_messages"):
            if row["job_id"] in moved_jobs:
                conn.execute(insert(job_messages).values(row))
                counts["job_messages"] += 1
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
