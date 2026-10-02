"""The sending side: one account's work, read out and sent part by part.

Everything is read from this installation's own database and checkouts and nothing here
is changed until the receiver has said it wrote the lot -- and then only if the person
asked for it to be deleted. A transfer that fails anywhere leaves this side exactly as it
was.

A checkout travels as a ``git bundle`` of every branch, which is the repository itself
rather than a copy of its files: the development branches go with it, unpushed or not.
Work not yet committed -- a phase is committed only once it passes, so a development
stopped at a gate usually has some -- follows as a snapshot of the files git would track,
the same one a Mac is sent to build (``workers.snapshot``).
"""

from __future__ import annotations

import base64
import json
import logging
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import or_, select

from slipwright import workers as macs
from slipwright.schemas.job import APPROVAL_STATES, TERMINAL_STATES, JobState, new_job_id
from slipwright.schemas.project import Project
from slipwright.store.migrate import current_revision
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
from slipwright.store.scoped import is_personal
from slipwright.store.settings import INSTALLATION
from slipwright.transfer import rows as R
from slipwright.transfer.channel import (
    ChannelError,
    CodeError,
    Part,
    SenderHandshake,
    parse_code,
    seal,
)
from slipwright.workspace import git as g

if TYPE_CHECKING:
    from slipwright.engine import Engine

log = logging.getLogger(__name__)

#: A development in one of these is not doing anything: it waits for a person, a Mac, or
#: nothing at all. Anything else is running, and its checkout is changing under us.
IDLE = (
    APPROVAL_STATES
    | TERMINAL_STATES
    | {
        JobState.AWAITING_BUILDER,
        JobState.CREATED,
        JobState.PAUSED,
    }
)


class Refused(RuntimeError):
    """The transfer cannot go ahead; the message is for the person who asked."""


@dataclass
class Scope:
    """Whose work is sent.

    ``owner`` is the account; ``everything`` is an installation with sign-in off, where
    there is nobody to separate and all of it is the one person's. ``admin`` also carries
    the installation's own settings -- mail, prices, webhooks -- and the projects from
    before accounts owned anything.
    """

    owner: str | None
    admin: bool = False
    everything: bool = False
    # what the person chose to send. ``projects`` None is all of them; without
    # ``checkouts`` the receiver clones each project from its remote instead, so only
    # what was pushed arrives
    projects: list[str] | None = None
    checkouts: bool = True
    settings: bool = True
    attachments: bool = True
    installation: bool = True


@dataclass
class Sending:
    """One transfer from here, as the page polls it."""

    target: str
    id: str = field(default_factory=new_job_id)
    owner: str | None = None
    state: str = "running"  # running | done | failed
    error: str | None = None
    progress: R.Progress = field(default_factory=R.Progress)
    summary: dict[str, Any] = field(default_factory=dict)
    receiver: str = ""


# -- what is sent ------------------------------------------------------------------------


def projects_of(engine: Engine, scope: Scope) -> list[Project]:
    query = select(projects.c.data_json).order_by(projects.c.created_at, projects.c.id)
    if not scope.everything:
        mine = projects.c.owner_id == scope.owner
        query = query.where(or_(mine, projects.c.owner_id.is_(None)) if scope.admin else mine)
    with engine.raw_store.db.connect() as conn:
        found = [Project.model_validate_json(r[0]) for r in conn.execute(query)]
    # the worked example is every account's own and has no checkout: the receiver has one
    found = [p for p in found if not p.is_demo]
    if scope.projects is not None:
        chosen = set(scope.projects)
        found = [p for p in found if p.id in chosen]
    return found


def busy(engine: Engine, project_ids: list[str]) -> list[str]:
    """The developments of these projects that are running right now, by title."""
    running = []
    for pid in project_ids:
        for job in engine.store.list(pid):
            if job.state not in IDLE:
                running.append(job.title)
    return running


def _repo(path: Path) -> dict[str, Any]:
    """What the receiver needs to rebuild a checkout: which branch it is on, whether it
    has commits to bundle, uncommitted work to follow, and the remote it pushes to."""
    head = g.run(path, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip() or None
    commits = g.run(path, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0
    has_refs = bool(g.run(path, "for-each-ref", "--count=1", check=False).stdout.strip())
    origin = g.run(path, "remote", "get-url", "origin", check=False).stdout.strip() or None
    return {
        "head": head,
        "bundle": commits or has_refs,
        "dirty": _dirty(path),
        "origin": origin,
    }


def _dirty(path: Path) -> bool:
    return bool(g.run(path, "status", "--porcelain", check=False).stdout.strip())


@dataclass
class Plan:
    """Everything that will be sent, worked out before anything is."""

    projects: list[Project]
    repos: dict[str, dict[str, Any]]
    trees: dict[str, dict[str, Any]]
    counts: dict[str, int]
    # where each worktree is here; not sent, the receiver makes its own
    tree_paths: dict[str, Path] = field(default_factory=dict)


def plan(engine: Engine, scope: Scope) -> Plan:
    """What would go, or ``Refused`` saying why nothing can yet."""
    found = projects_of(engine, scope)
    ids = [p.id for p in found]
    running = busy(engine, ids)
    if running:
        names = ", ".join(running[:3]) + ("…" if len(running) > 3 else "")
        raise Refused(
            f"{len(running)} development(s) are running ({names}); wait until they finish "
            "or stop at a gate, then move"
        )
    repos: dict[str, dict[str, Any]] = {}
    trees: dict[str, dict[str, Any]] = {}
    tree_paths: dict[str, Path] = {}
    for project in found:
        path = project.repo_path
        if not scope.checkouts:
            # cloned over there from where it is pushed: there has to be such a place
            here = _repo(path) if path is not None and path.is_dir() else {}
            origin = here.get("origin") or project.effective_clone_url
            if not origin:
                raise Refused(
                    f"{project.name} has no remote to clone from; send it with its checkout"
                )
            repos[project.id] = {
                "head": here.get("head"),
                "bundle": False,
                "dirty": False,
                "origin": origin,
            }
            continue
        if path is None or not path.is_dir():
            raise Refused(f"the checkout of {project.name} is missing ({path}); nothing to send")
        repos[project.id] = _repo(path)
        for job in engine.store.list(project.id):
            tree = job.worktree_path
            if job.is_terminal or tree is None or not tree.is_dir():
                continue
            trees[job.id] = {"project": project.id, "branch": job.branch, "dirty": _dirty(tree)}
            tree_paths[job.id] = tree
    counts = {table: len(list(_rows(engine, scope, table, ids))) for table in R.TABLES}
    return Plan(found, repos, trees, counts, tree_paths)


def _rows(
    engine: Engine, scope: Scope, table: str, project_ids: list[str]
) -> Iterator[dict[str, Any]]:
    """The rows of one table that belong to what is sent, in the order they were made."""
    if not project_ids and table not in ("standards_pages", "translations", "settings"):
        return
    db = engine.raw_store.db
    with db.connect() as conn:
        if table == "projects":
            query = select(projects).where(projects.c.id.in_(project_ids))
        elif table == "project_briefs":
            query = select(project_briefs).where(project_briefs.c.project_id.in_(project_ids))
        elif table == "jobs":
            query = select(jobs).where(jobs.c.project_id.in_(project_ids))
        elif table == "job_history":
            mine = select(jobs.c.id).where(jobs.c.project_id.in_(project_ids))
            query = select(job_history).where(job_history.c.job_id.in_(mine))
            query = query.order_by(job_history.c.seq)
        elif table == "test_runs":
            query = select(test_runs).where(test_runs.c.project_id.in_(project_ids))
        elif table == "attachments":
            if not scope.attachments:
                return
            query = select(attachments).where(attachments.c.project_id.in_(project_ids))
        elif table == "standards_pages":
            if not scope.attachments:
                return
            query = select(standards_pages).where(
                standards_pages.c.owner_id == (scope.owner or INSTALLATION)
            )
        elif table == "translations":
            # a cache of agent prose across every account: only an administrator's
            # transfer carries it, since it holds other people's text too
            if not (scope.admin and scope.installation):
                return
            query = select(translations)
        elif table == "settings":
            yield from _settings(engine, scope)
            return
        else:  # pragma: no cover - TABLES and this list are kept together
            raise KeyError(table)
        result = conn.execution_options(stream_results=True).execute(query)
        for row in result:
            yield dict(row._mapping)


def _settings(engine: Engine, scope: Scope) -> Iterator[dict[str, Any]]:
    """The account's settings, and the installation's when an administrator sends.

    A stored secret is opened here: the receiver has a key of its own and seals it again
    with that. Inside the transfer it is protected by the channel, never by this key.
    """
    store = engine.raw_store
    mine = scope.owner or INSTALLATION
    with store.db.connect() as conn:
        found = [
            dict(r._mapping)
            for r in conn.execute(
                select(settings).where(settings.c.user_id.in_({mine, INSTALLATION}))
            )
        ]
    for row in found:
        name = str(row["name"])
        if not R.carried(name):
            continue
        personal = is_personal(name)
        if personal and row["user_id"] != mine:
            continue  # an installation row of a personal name: pre-account leftovers
        if personal and not scope.settings:
            continue
        if not personal and not (scope.admin and scope.installation):
            continue
        value = row["value_json"]
        if row["encrypted"]:
            try:
                value = store.secret_box.decrypt(value)
            except ValueError:
                log.warning("transfer: setting %s does not decrypt; left behind", name)
                continue
        yield {
            "name": name,
            "value_json": value,
            "secret": bool(row["encrypted"]),
            "scope": "personal" if personal else "installation",
        }


# -- sending ------------------------------------------------------------------------------


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail") or response.text)
    except ValueError:
        return response.text or f"HTTP {response.status_code}"


class _Line:
    """The session with the receiver: every part sealed with the agreed key, in order."""

    def __init__(self, http: httpx.Client, address: str, session: str, key: bytes) -> None:
        self.http, self.address, self.session, self.key = http, address, session, key
        self.seq = 0

    def send(self, part: Part) -> dict[str, Any]:
        sealed = seal(self.key, self.session, self.seq, part)
        self.seq += 1
        got = self.http.post(
            f"{self.address}/api/transfer/peer/{self.session}/part",
            content=sealed,
            headers={"content-type": "application/octet-stream"},
        )
        if got.status_code != 200:
            raise Refused(_detail(got))
        answer: dict[str, Any] = got.json()
        return answer


def pair(
    http: httpx.Client, address: str, code: str, *, name: str, revision: str | None, version: str
) -> _Line:
    """Agree a key with the receiver from the code typed here."""
    try:
        slot, secret = parse_code(code)
    except CodeError as exc:
        raise Refused(str(exc)) from exc
    handshake = SenderHandshake(secret)
    try:
        got = http.post(
            f"{address}/api/transfer/peer/pair",
            json={
                "slot": slot,
                "message": base64.b64encode(handshake.start()).decode("ascii"),
                "name": name,
                "revision": revision,
                "version": version,
            },
        )
    except httpx.TransportError as exc:
        raise Refused(f"{address} did not answer: {exc}") from exc
    if got.status_code != 200:
        raise Refused(_detail(got))
    answer = got.json()
    try:
        key = handshake.finish(base64.b64decode(answer["message"]), answer["confirm"])
    except ChannelError as exc:
        raise Refused("the code did not match; type the one on the receiving screen now") from exc
    return _Line(http, address, str(answer["session"]), key)


def send(
    engine: Engine,
    scope: Scope,
    sending: Sending,
    *,
    address: str,
    code: str,
    http: httpx.Client,
    name: str,
    version: str,
    delete_after: bool = False,
) -> None:
    """Send everything ``scope`` owns to ``address``. Raises ``Refused`` on any failure,
    and changes nothing here unless the receiver wrote it all and ``delete_after``."""
    progress = sending.progress
    if delete_after:
        progress.add("delete")
    work = plan(engine, scope)
    progress.begin("pair")
    line = pair(
        http,
        address.rstrip("/"),
        code,
        name=name,
        revision=current_revision(engine.raw_store.db),
        version=version,
    )
    progress.finish("pair")
    for table, step in R.STEP_OF.items():
        if step is not None:
            progress.step(step).total += work.counts[table]
    progress.step("repos").total = len(work.repos)

    line.send(
        Part(
            {
                "kind": "manifest",
                "name": name,
                "version": version,
                "admin": scope.admin,
                "projects": [{"id": p.id, "name": p.name} for p in work.projects],
                "repos": work.repos,
                "trees": work.trees,
                "checkouts": scope.checkouts,
                "counts": work.counts,
            }
        )
    )
    ids = [p.id for p in work.projects]
    for table in R.TABLES:
        step = R.STEP_OF[table]
        batch = R.FILE_BATCH if table == "attachments" else R.BATCH
        chunk: list[dict[str, Any]] = []
        for row in _rows(engine, scope, table, ids):
            chunk.append(R.encode(row))
            if len(chunk) >= batch:
                _send_rows(line, table, chunk, progress, step)
                chunk = []
        if chunk:
            _send_rows(line, table, chunk, progress, step)
    for key in ("projects", "jobs", "settings", "attachments", "standards"):
        progress.finish(key)

    progress.begin("repos")
    with tempfile.TemporaryDirectory(prefix="slipwright-move-") as tmp:
        for project in work.projects:
            _send_checkout(line, project, work, Path(tmp))
            progress.advance("repos")
    progress.finish("repos")

    progress.begin("finish")
    answer = line.send(Part({"kind": "finish"}))
    sending.summary = answer
    progress.finish("finish")

    if delete_after:
        progress.begin("delete", total=len(work.projects))
        moved = set(answer.get("moved", ids))
        for project in work.projects:
            if project.id in moved:
                try:
                    engine.delete_project(project.id, purge=True)
                except Exception as exc:  # noqa: BLE001 - it is safely over there; say so
                    log.warning("transfer: could not delete %s here: %s", project.name, exc)
            progress.advance("delete")
        progress.finish("delete")


def _send_rows(
    line: _Line, table: str, chunk: list[dict[str, Any]], progress: R.Progress, step: str | None
) -> None:
    line.send(Part({"kind": "rows", "table": table}, json.dumps(chunk).encode()))
    if step is not None:
        progress.advance(step, len(chunk))


def _send_checkout(line: _Line, project: Project, work: Plan, tmp: Path) -> None:
    assert project.repo_path is not None  # plan() refused any without
    repo = project.repo_path
    meta = work.repos[project.id]
    if meta["bundle"]:
        bundle = tmp / f"{project.id}.bundle"
        g.run(repo, "bundle", "create", "-q", str(bundle), "--all")
        _send_file(line, f"repo/{project.id}.bundle", bundle)
        bundle.unlink()
    if meta["dirty"]:
        _send_blob(line, f"repo/{project.id}.tar.gz", _snapshot(repo, project.name))
    for job_id, tree in work.trees.items():
        if tree["project"] == project.id and tree["dirty"]:
            snapshot = _snapshot(work.tree_paths[job_id], project.name)
            _send_blob(line, f"tree/{job_id}.tar.gz", snapshot)


def _snapshot(path: Path, name: str) -> bytes:
    try:
        return macs.snapshot(path)
    except ValueError as exc:
        raise Refused(f"{name}: {exc}") from exc


def _send_file(line: _Line, name: str, path: Path) -> None:
    size = path.stat().st_size
    with path.open("rb") as handle:
        sent = 0
        while True:
            piece = handle.read(R.CHUNK)
            sent += len(piece)
            line.send(Part({"kind": "blob", "name": name, "last": sent >= size}, piece))
            if sent >= size:
                return


def _send_blob(line: _Line, name: str, data: bytes) -> None:
    for start in range(0, max(len(data), 1), R.CHUNK):
        piece = data[start : start + R.CHUNK]
        line.send(Part({"kind": "blob", "name": name, "last": start + R.CHUNK >= len(data)}, piece))


# -- in the background ------------------------------------------------------------------


def start(
    engine: Engine,
    scope: Scope,
    sending: Sending,
    **kwargs: Any,
) -> threading.Thread:
    """Run ``send`` in a thread, writing how it ended onto ``sending``."""

    def go() -> None:
        try:
            send(engine, scope, sending, **kwargs)
            sending.state = "done"
        except Refused as exc:
            sending.state, sending.error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001 - a thread has nobody to raise to
            log.exception("transfer to %s failed", sending.target)
            sending.state, sending.error = "failed", f"the transfer failed: {exc}"

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    return thread


__all__ = [
    "IDLE",
    "Plan",
    "projects_of",
    "Refused",
    "Scope",
    "Sending",
    "busy",
    "pair",
    "plan",
    "send",
    "start",
]
