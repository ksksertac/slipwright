"""A newer release, offered where the version is shown, and installed on a press.

Two halves, because a container cannot replace itself: the moment it stops, so does the
code that was going to start its successor.

The server does what it can do from inside. It asks the registry which releases exist,
says when one is newer than itself, and on a press pulls that image and starts a helper
container **from the new image** -- ``slipwright self-update`` -- with the Docker socket
mounted and nothing else. Then it waits to be stopped.

The helper does the part that has to happen from outside. It reads how the running
container was made (its volumes, ports, networks, restart policy, the environment
somebody gave it), stops it, makes the new one the same way under the same name, and
waits for the new one's health check. Healthy: the old container is removed. Anything
else: the new one is removed and the old one is started again under its own name, so a
bad release costs a restart, not the installation.

What is kept is everything that lives outside the container, which is everything that
matters: ``/data`` and ``/work`` are volumes, a PostgreSQL server is its own container.
The trap is a volume nobody named. ``docker run`` without ``-v`` gives ``/data`` an
anonymous volume, and a container made again from the image would get a fresh, empty
one -- so every volume the old container had is carried over by name, whether anybody
declared it or not.

Releases are the registry's semantic-version tags, never ``latest`` or ``sha-…``. Every
merge to main is one: CI takes the newest ``v1.2.3`` tag, publishes the next patch
(``1.2.4``) and tags it. A bigger step is a ``v1.3.0`` tag pushed by hand, and the patches
count on from there.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import socket
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from slipwright import net

log = logging.getLogger(__name__)

#: Where releases are published. ``SLIPWRIGHT_UPDATE_IMAGE`` points a fork at its own
#: registry, or turns the whole thing off with ``off``.
DEFAULT_IMAGE = "ghcr.io/ksksertac/slipwright"
DEFAULT_SOCKET = "/var/run/docker.sock"
#: How often the registry is asked. Every merge to main is a release, so a fix merged
#: should reach the corner in minutes, not the six hours this once was -- one small
#: anonymous request per installation every five minutes is nothing to the registry.
CHECK_EVERY_S = 5 * 60.0
#: How many copies of a SQLite database are kept from before an update.
BACKUPS_KEPT = 3
#: A release is three numbers and nothing else: ``1.2`` is a moving alias of the newest
#: ``1.2.x`` and ``sha-…`` is a build of main.
RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

State = Literal["idle", "pulling", "restarting", "failed"]
#: Why the button cannot install by itself. ``no_docker``: this server cannot reach the
#: Docker daemon (the socket is not mounted). ``source``: it is not a container at all.
Blocked = Literal["no_docker", "source"]


class DockerError(RuntimeError):
    """The daemon said no, in its own words."""


class UpdateRefused(RuntimeError):
    """An install that cannot start: nothing to install, one already running, or no
    Docker to do it with. The API answers 409 with this message."""


def version_key(text: str) -> tuple[int, int, int] | None:
    """``1.2.3`` → ``(1, 2, 3)``; anything that is not a release → ``None``. A source
    checkout's ``0.2.0.dev1`` is read as ``0.2.0``, which is what it is on its way to."""
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", text.strip())
    if match is None:
        return None
    major, minor, patch = (int(g) for g in match.groups())
    return (major, minor, patch)


def running_version() -> str:
    """The version this code was released as. A published image carries it in
    ``SLIPWRIGHT_VERSION``, written by CI from the release tag it computed: every merge to
    main is a release, and ``pyproject.toml`` cannot follow -- CI may not commit to a
    protected main. A source checkout has no such variable and reports ``pyproject.toml``'s.

    The variable is the image's own, so a container made again from the next release gets
    the next release's (``recreated`` drops what the old image set)."""
    if released := os.environ.get("SLIPWRIGHT_VERSION", "").strip():
        return released
    try:
        return package_version("slipwright")
    except PackageNotFoundError:  # pragma: no cover - always installed, even from source
        return "0.0.0"


# -- the registry ------------------------------------------------------------------------


def split_image(image: str) -> tuple[str, str]:
    """``ghcr.io/owner/name`` → ``("ghcr.io", "owner/name")``."""
    registry, _, repo = image.partition("/")
    return registry, repo


def latest_release(image: str, client: httpx.Client) -> str | None:
    """The newest release tag the registry holds for ``image``, or ``None``.

    Anonymous: a public image's tags are readable by anybody, but only with a token, and
    the registry hands a pull-only one to anybody who asks.
    """
    registry, repo = split_image(image)
    token = net.request(
        client,
        "GET",
        f"https://{registry}/token",
        params={"scope": f"repository:{repo}:pull", "service": registry},
    )
    token.raise_for_status()
    resp = net.request(
        client,
        "GET",
        f"https://{registry}/v2/{repo}/tags/list",
        params={"n": 1000},
        headers={"Authorization": f"Bearer {token.json()['token']}"},
    )
    resp.raise_for_status()
    releases = [str(t) for t in resp.json().get("tags") or [] if RELEASE.match(str(t))]
    if not releases:
        return None
    return max(releases, key=lambda t: version_key(t) or (0, 0, 0))


def notes_url(image: str, version: str) -> str | None:
    """Where a release is described: its GitHub release, when the image is on GHCR."""
    registry, repo = split_image(image)
    if registry != "ghcr.io":
        return None
    return f"https://github.com/{repo}/releases/tag/v{version}"


@dataclass
class ReleaseNotes:
    """What a release changes, in the words it was published with (Markdown)."""

    text: str
    published_at: datetime | None = None


def release_notes(image: str, version: str, client: httpx.Client) -> ReleaseNotes | None:
    """The GitHub release's own text; failing that, the release's section of the
    changelog as it stood at its tag. A tag pushed without a release written for it is
    the ordinary case, and the changelog is written either way.

    Only for images on GHCR, whose repository is the one on GitHub. Never raises: notes
    that cannot be fetched leave a dialog with the version and nothing else, which is
    still enough to install it.
    """
    registry, repo = split_image(image)
    if registry != "ghcr.io":
        return None
    try:
        resp = net.request(
            client,
            "GET",
            f"https://api.github.com/repos/{repo}/releases/tags/v{version}",
            headers={"Accept": "application/vnd.github+json"},
        )
        if resp.status_code == 200:
            data = resp.json()
            body = str(data.get("body") or "").strip()
            published = data.get("published_at")
            when = datetime.fromisoformat(published) if published else None
            if body:
                return ReleaseNotes(body, when)
        else:
            when = None
        resp = net.request(
            client, "GET", f"https://raw.githubusercontent.com/{repo}/v{version}/CHANGELOG.md"
        )
        if resp.status_code != 200:
            return ReleaseNotes("", when) if when else None
        section = changelog_section(resp.text, version)
        return ReleaseNotes(section, when) if section or when else None
    except (httpx.HTTPError, ValueError) as exc:
        log.info("could not fetch the notes of %s: %s", version, exc)
        return None


def changelog_section(changelog: str, version: str) -> str:
    """The body under ``## <version>`` in a changelog, up to the next ``## ``."""
    lines = changelog.splitlines()
    heading = re.compile(rf"^##\s+v?{re.escape(version)}(\s|$)")
    for i, line in enumerate(lines):
        if heading.match(line):
            rest = lines[i + 1 :]
            end = next((j for j, ln in enumerate(rest) if ln.startswith("## ")), len(rest))
            return "\n".join(rest[:end]).strip()
    return ""


# -- the Docker daemon -------------------------------------------------------------------


class Docker(Protocol):
    """The handful of Engine API calls an update needs. ``EngineAPI`` speaks them over
    the socket; the tests speak them to a dictionary."""

    def container(self, ref: str) -> dict[str, Any]: ...
    def image(self, ref: str) -> dict[str, Any]: ...
    def pull(self, repo: str, tag: str) -> None: ...
    def tag(self, image: str, repo: str, tag: str) -> None: ...
    def create(self, body: dict[str, Any], name: str) -> str: ...
    def connect(self, network: str, container: str, endpoint: dict[str, Any]) -> None: ...
    def start(self, ref: str) -> None: ...
    def stop(self, ref: str, timeout_s: int) -> None: ...
    def rename(self, ref: str, name: str) -> None: ...
    def remove(self, ref: str, *, force: bool = False) -> None: ...
    def logs(self, ref: str, tail: int) -> str: ...


class EngineAPI:
    """The Docker Engine API over its unix socket. The image carries no Docker client, and
    needs none for this: every call is one HTTP request."""

    def __init__(self, socket_path: str = DEFAULT_SOCKET, *, timeout_s: float = 60.0) -> None:
        self._client = httpx.Client(
            transport=httpx.HTTPTransport(uds=socket_path),
            base_url="http://docker",
            timeout=timeout_s,
        )

    def _call(self, method: str, path: str, **kw: Any) -> httpx.Response:
        resp = self._client.request(method, path, **kw)
        # 304: started what was running, stopped what was stopped -- already so, not wrong
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message") or resp.text
            except ValueError:
                message = resp.text
            raise DockerError(f"{method} {path}: {message}")
        return resp

    def container(self, ref: str) -> dict[str, Any]:
        data: dict[str, Any] = self._call("GET", f"/containers/{ref}/json").json()
        return data

    def image(self, ref: str) -> dict[str, Any]:
        data: dict[str, Any] = self._call("GET", f"/images/{ref}/json").json()
        return data

    def pull(self, repo: str, tag: str) -> None:
        # The daemon answers 200 at once and then streams progress; a failure half way
        # through (a missing tag, a full disk) arrives as an ``error`` line in that stream,
        # so the stream has to be read to the end to know whether it worked.
        with self._client.stream(
            "POST", "/images/create", params={"fromImage": repo, "tag": tag}, timeout=None
        ) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise DockerError(f"pull {repo}:{tag}: {resp.text}")
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("error"):
                    raise DockerError(f"pull {repo}:{tag}: {event['error']}")

    def tag(self, image: str, repo: str, tag: str) -> None:
        self._call("POST", f"/images/{image}/tag", params={"repo": repo, "tag": tag})

    def create(self, body: dict[str, Any], name: str) -> str:
        created: str = self._call(
            "POST", "/containers/create", params={"name": name}, json=body
        ).json()["Id"]
        return created

    def connect(self, network: str, container: str, endpoint: dict[str, Any]) -> None:
        self._call(
            "POST",
            f"/networks/{network}/connect",
            json={"Container": container, "EndpointConfig": endpoint},
        )

    def start(self, ref: str) -> None:
        self._call("POST", f"/containers/{ref}/start")

    def stop(self, ref: str, timeout_s: int) -> None:
        # the daemon waits ``t`` seconds before it kills; the request has to outlast that
        self._call(
            "POST", f"/containers/{ref}/stop", params={"t": timeout_s}, timeout=timeout_s + 30
        )

    def rename(self, ref: str, name: str) -> None:
        self._call("POST", f"/containers/{ref}/rename", params={"name": name})

    def remove(self, ref: str, *, force: bool = False) -> None:
        # never ``v=1``: that would take the anonymous volumes with it, and those are
        # exactly what the new container was just handed
        self._call("DELETE", f"/containers/{ref}", params={"force": int(force)})

    def logs(self, ref: str, tail: int) -> str:
        raw = self._call(
            "GET",
            f"/containers/{ref}/logs",
            params={"stdout": 1, "stderr": 1, "tail": tail},
        ).content
        return _demux(raw)


def _demux(raw: bytes) -> str:
    """A container without a TTY interleaves stdout and stderr in frames, each behind an
    eight-byte header; one with a TTY sends the text as it is."""
    if not raw or raw[0] not in (0, 1, 2):
        return raw.decode(errors="replace")
    out: list[bytes] = []
    i = 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        out.append(raw[i + 8 : i + 8 + size])
        i += 8 + size
    return b"".join(out).decode(errors="replace")


def own_container(docker: Docker) -> dict[str, Any] | None:
    """The container this process runs in, as the daemon describes it.

    Docker makes the hostname the container's short id, unless somebody set one; the
    mount table names the id either way, through the files Docker mounts in
    (``/etc/hostname`` and friends live under ``…/containers/<id>/``).
    """
    candidates = [socket.gethostname()]
    try:
        mounts = Path("/proc/self/mountinfo").read_text()
        candidates += re.findall(r"/containers/([0-9a-f]{64})/", mounts)
    except OSError:
        pass
    for candidate in dict.fromkeys(candidates):
        try:
            return docker.container(candidate)
        except DockerError:
            continue
    return None


# -- making the container again ----------------------------------------------------------

#: What ``docker compose`` recognises its own containers by. With it, the image reference
#: compose knows the service by is pointed at the new image as well -- otherwise the next
#: ``docker compose up`` would see a container whose image is not the service's and
#: quietly put the old version back.
COMPOSE_PROJECT = "com.docker.compose.project"
COMPOSE_IMAGE = "com.docker.compose.image"

#: Settings the image supplies; carried over only where somebody changed them, so that a
#: release that moves its entrypoint or its health check actually gets to.
_FROM_IMAGE = ("Cmd", "Entrypoint", "WorkingDir", "User", "Healthcheck", "StopSignal")
_ENDPOINT_KEPT = ("IPAMConfig", "Links", "DriverOpts")


def recreated(
    old: dict[str, Any],
    old_image: dict[str, Any] | None,
    new_image: dict[str, Any],
    image_ref: str,
) -> dict[str, Any]:
    """The body that makes ``old`` again from another image: same volumes, same ports,
    same networks, same restart policy, same environment -- except what the old image
    itself put there, which the new image replaces with its own.

    ``old_image`` may be gone. With containerd's image store, moving a tag deletes the
    image it moved from even while a container still runs on it -- a ``docker pull`` of
    ``latest`` before pressing the button is enough. Then the new image decides by
    *name*: a variable or label it sets itself is the image's, anything else is the
    person's. That loses an override of one of the image's own variables, which is the
    rarer thing to lose.
    """
    config: dict[str, Any] = old.get("Config") or {}
    was: dict[str, Any] = (old_image or {}).get("Config") or {}
    now: dict[str, Any] = new_image.get("Config") or {}
    short_id = str(old.get("Id", ""))[:12]

    # The environment a container reports is the image's and the person's together. Only
    # the person's is carried: were the image's carried too, a release that changed one
    # of its own variables would be overruled by the release before it.
    env: list[str] = config.get("Env") or []
    labels: dict[str, str] = config.get("Labels") or {}
    if old_image is not None:
        image_env = set(was.get("Env") or [])
        from_image = was.get("Labels") or {}
        env = [e for e in env if e not in image_env]
        labels = {k: v for k, v in labels.items() if from_image.get(k) != v}
    else:
        names = {e.partition("=")[0] for e in now.get("Env") or []}
        env = [e for e in env if e.partition("=")[0] not in names]
        labels = {
            k: v
            for k, v in labels.items()
            if k not in (now.get("Labels") or {}) and not k.startswith("org.opencontainers.")
        }
    body: dict[str, Any] = {
        "Image": image_ref,
        "Env": env,
        "Labels": labels,
        "ExposedPorts": config.get("ExposedPorts"),
        "Tty": config.get("Tty", False),
        "OpenStdin": config.get("OpenStdin", False),
    }
    if COMPOSE_IMAGE in body["Labels"]:
        body["Labels"][COMPOSE_IMAGE] = new_image.get("Id", "")
    # without the old image there is no telling a changed command from the image's own,
    # and the new image's is the one that fits it
    for key in _FROM_IMAGE if old_image is not None else ():
        if config.get(key) != was.get(key):
            body[key] = config.get(key)
    # Docker names a container's host after its id; carried over, the new container would
    # answer to the old one's name -- and could not find itself the next time round
    if config.get("Hostname") and config["Hostname"] != short_id:
        body["Hostname"] = config["Hostname"]
        body["Domainname"] = config.get("Domainname", "")

    host: dict[str, Any] = dict(old.get("HostConfig") or {})
    declared = {_bind_target(b) for b in host.get("Binds") or []}
    declared |= {m.get("Target") for m in host.get("Mounts") or []}
    anonymous = [
        {"Type": "volume", "Source": m["Name"], "Target": m["Destination"]}
        for m in old.get("Mounts") or []
        if m.get("Type") == "volume" and m.get("Destination") not in declared
    ]
    if anonymous:
        host["Mounts"] = [*(host.get("Mounts") or []), *anonymous]
    body["HostConfig"] = host

    networks = (old.get("NetworkSettings") or {}).get("Networks") or {}
    endpoints: dict[str, Any] = {}
    for name, endpoint in networks.items():
        kept = {k: endpoint.get(k) for k in _ENDPOINT_KEPT if endpoint.get(k)}
        aliases = [a for a in endpoint.get("Aliases") or [] if a != short_id]
        if aliases:
            kept["Aliases"] = aliases
        endpoints[name] = kept
    if endpoints:
        body["NetworkingConfig"] = {"EndpointsConfig": endpoints}
    return body


def _bind_target(bind: str) -> str:
    """Where a ``source:target[:options]`` bind lands. The source may be a Windows path
    with a colon of its own, so the target is the first part after it that is absolute."""
    return next((p for p in bind.split(":")[1:] if p.startswith("/")), "")


def _split_ref(ref: str) -> tuple[str, str]:
    """``host:5000/owner/name:tag`` → ``("host:5000/owner/name", "tag")``."""
    head, _, last = ref.rpartition("/")
    name, _, tag = last.partition(":")
    return (f"{head}/{name}" if head else name), (tag or "latest")


def replace(
    docker: Docker,
    container: str,
    image: str,
    *,
    say: Callable[[str], None] = print,
    stop_timeout_s: int = 60,
    health_timeout_s: float = 300.0,
    poll_s: float = 2.0,
) -> None:
    """Make ``container`` again from ``image``, keeping everything that was kept outside
    it, and put the old one back if the new one never becomes healthy."""
    old = docker.container(container)
    old_id: str = old["Id"]
    name = str(old["Name"]).lstrip("/")
    new_image = docker.image(image)
    try:
        old_image: dict[str, Any] | None = docker.image(old["Image"])
    except DockerError:
        old_image = None  # see `recreated`
        say("the old image is gone; the new one decides what was its own")
    labels = (old.get("Config") or {}).get("Labels") or {}

    ref = image
    if COMPOSE_PROJECT in labels:
        ref = old["Config"]["Image"]
        repo, tag = _split_ref(ref)
        docker.tag(new_image["Id"], repo, tag)
        say(f"{ref} now names {image}, so docker compose agrees with what runs")
    body = recreated(old, old_image, new_image, ref)

    say(f"stopping {name}")
    docker.rename(old_id, f"{name}-previous")
    docker.stop(old_id, stop_timeout_s)
    new_id: str | None = None
    try:
        endpoints = (body.get("NetworkingConfig") or {}).get("EndpointsConfig") or {}
        first = next(iter(endpoints.items()), None)
        # one network at creation, the rest connected after: older daemons refuse more
        if first is not None:
            body["NetworkingConfig"] = {"EndpointsConfig": dict([first])}
        new_id = docker.create(body, name)
        for network, endpoint in list(endpoints.items())[1:]:
            docker.connect(network, new_id, endpoint)
        say(f"starting {name} on {image}")
        docker.start(new_id)
        _wait_healthy(docker, new_id, health_timeout_s, poll_s)
    except Exception as exc:
        say(f"the new container did not come up ({exc}); putting the old one back")
        if new_id is not None:
            try:
                say(docker.logs(new_id, 20))
                docker.remove(new_id, force=True)
            except DockerError:
                pass
        docker.rename(old_id, name)
        docker.start(old_id)
        raise
    docker.remove(old_id)
    say(f"{name} runs {image}")


def _wait_healthy(docker: Docker, ref: str, timeout_s: float, poll_s: float) -> None:
    """Until the image's health check passes. Without one, a container still running
    after a few polls is taken at its word."""
    deadline = time.monotonic() + timeout_s
    alive = 0
    while True:
        state = docker.container(ref).get("State") or {}
        if not state.get("Running"):
            raise DockerError(f"exited with {state.get('ExitCode')}")
        health = (state.get("Health") or {}).get("Status")
        if health == "healthy":
            return
        # Docker says so only after the check has failed several times in a row, past its
        # start period: there is nothing more to wait for
        if health == "unhealthy":
            raise DockerError("its health check failed")
        if health is None:
            alive += 1
            if alive >= 5:
                return
        if time.monotonic() >= deadline:
            raise DockerError(f"not healthy after {timeout_s:.0f}s (last: {health})")
        time.sleep(poll_s)


# -- the server's half --------------------------------------------------------------------


def backup_sqlite(path: Path, version: str, *, keep: int = BACKUPS_KEPT) -> Path:
    """A consistent copy of the database from before the new version migrates it.

    Through SQLite's own backup, not a file copy: jobs may be writing while it is taken.
    A PostgreSQL server is its own container and outlives the update untouched; it is
    backed up the way its owner backs it up.
    """
    folder = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"{path.stem}-before-{version}-{stamp}.sqlite3"
    with sqlite3.connect(path) as source, sqlite3.connect(target) as copy:
        source.backup(copy)
    for stale in sorted(folder.glob(f"{path.stem}-before-*.sqlite3"))[:-keep]:
        stale.unlink(missing_ok=True)
    return target


@dataclass
class Status:
    current: str
    latest: str | None
    notes_url: str | None
    notes: str | None
    published_at: datetime | None
    blocked: Blocked | None
    state: State
    error: str | None
    backup: bool
    command: str


@dataclass
class Updater:
    """What the version corner knows, and the one button that acts on it."""

    image: str = DEFAULT_IMAGE
    current: str = field(default_factory=running_version)
    socket_path: str = DEFAULT_SOCKET
    #: The SQLite file to copy before a new version migrates it; ``None`` on PostgreSQL.
    sqlite: Path | None = None
    in_container: bool = field(default_factory=lambda: Path("/.dockerenv").exists())
    docker_factory: Callable[[str], Docker] = EngineAPI
    registry: Callable[[str], str | None] | None = None
    #: Where a release's notes come from; ``None`` asks GitHub, unless ``registry`` is
    #: stood in for too -- a test offering a release that does not exist has none.
    notes_source: Callable[[str, str], ReleaseNotes | None] | None = None

    latest: str | None = None
    notes: ReleaseNotes | None = None
    state: State = "idle"
    error: str | None = None
    _docker: Docker | None = field(default=None, repr=False)
    _me: dict[str, Any] | None = field(default=None, repr=False)
    _probed: bool = field(default=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_env(cls, *, sqlite: Path | None = None) -> Updater:
        image = os.environ.get("SLIPWRIGHT_UPDATE_IMAGE", DEFAULT_IMAGE).strip()
        socket_path = os.environ.get("SLIPWRIGHT_DOCKER_SOCKET", DEFAULT_SOCKET).strip()
        return cls(
            image="" if image.lower() in ("", "0", "off", "no", "false") else image,
            socket_path=socket_path,
            sqlite=sqlite,
        )

    # -- what is on offer --

    def check(self) -> str | None:
        """Ask the registry. Never raises: an update check that could not be made is the
        same, to anybody looking, as one that found nothing."""
        if not self.image:
            return None
        try:
            if self.registry is not None:
                newest = self.registry(self.image)
            else:
                with httpx.Client(timeout=15.0) as client:
                    newest = latest_release(self.image, client)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.info("could not ask %s for releases: %s", self.image, exc)
            return self.latest
        mine, theirs = version_key(self.current), version_key(newest or "")
        offered = newest if (mine and theirs and theirs > mine) else None
        # asked once per release, not on every check: they do not change once published
        if offered != self.latest or (offered and self.notes is None):
            self.notes = self._notes(offered) if offered else None
        self.latest = offered
        return self.latest

    def _notes(self, version: str) -> ReleaseNotes | None:
        if self.notes_source is not None:
            return self.notes_source(self.image, version)
        if self.registry is not None:
            return None
        with httpx.Client(timeout=15.0) as client:
            return release_notes(self.image, version, client)

    def _probe(self) -> None:
        """Whether this server can reach the daemon and find itself there. Asked once: a
        socket is not mounted into a running container."""
        if self._probed:
            return
        self._probed = True
        if not self.in_container or not Path(self.socket_path).exists():
            return
        try:
            docker = self.docker_factory(self.socket_path)
            self._me = own_container(docker)
            self._docker = docker if self._me else None
        except (DockerError, httpx.HTTPError, OSError) as exc:
            log.info("the Docker socket is mounted but did not answer: %s", exc)

    def blocked(self) -> Blocked | None:
        self._probe()
        if self._docker is not None:
            return None
        return "no_docker" if self.in_container else "source"

    def command(self) -> str:
        """What a person would type instead, for a server that cannot do it itself.

        Commands that run as pasted, and nothing else: the prose that once followed a
        ``#`` is a comment to bash but an argument to zsh, macOS's shell, where it made
        ``docker pull`` refuse the line. The names are the README's; the new container is
        given the socket, so the next release installs from the page."""
        if not self.in_container:
            return "git pull && uv sync && uv run slipwright serve"
        ref = f"{self.image}:{self.latest or 'latest'}"
        port = os.environ.get("SLIPWRIGHT_PORT", "8500")
        return "\n".join(
            [
                f"docker pull {ref}",
                "docker stop slipwright && docker rm slipwright",
                f"docker run -d --name slipwright --restart unless-stopped -p {port}:{port} \\",
                "    -v slipwright-state:/data -v slipwright-work:/work \\",
                "    -v /var/run/docker.sock:/var/run/docker.sock --group-add 0 \\",
                f"    {ref}",
            ]
        )

    def status(self) -> Status:
        return Status(
            current=self.current,
            latest=self.latest,
            notes_url=notes_url(self.image, self.latest) if self.latest else None,
            notes=(self.notes.text or None) if self.notes else None,
            published_at=self.notes.published_at if self.notes else None,
            blocked=self.blocked(),
            state=self.state,
            error=self.error,
            backup=self.sqlite is not None,
            command=self.command(),
        )

    # -- installing --

    def install(self, version: str) -> None:
        """Start installing ``version``: pull it, copy the database, hand over to the
        helper. Returns at once; ``state`` says how far it got."""
        with self._lock:
            if self.state in ("pulling", "restarting"):
                raise UpdateRefused("an update is already being installed")
            if self.latest is None or version != self.latest:
                raise UpdateRefused(f"{version} is not the release on offer")
            if self.blocked() is not None:
                raise UpdateRefused("this server cannot reach Docker to install it")
            self.state, self.error = "pulling", None
        threading.Thread(target=self._install, args=(version,), daemon=True).start()

    def _install(self, version: str) -> None:
        assert self._docker is not None and self._me is not None
        docker, me = self._docker, self._me
        ref = f"{self.image}:{version}"
        try:
            docker.pull(self.image, version)
            if self.sqlite is not None and self.sqlite.is_file():
                log.info("database copied to %s", backup_sqlite(self.sqlite, self.current))
            helper = helper_name(me)
            with contextlib.suppress(DockerError):  # there was no earlier one
                docker.remove(helper, force=True)
            docker.create(helper_body(me, ref, self.socket_path), helper)
            self.state = "restarting"
            docker.start(helper)
        except Exception as exc:  # the button has to say *something* went wrong
            log.warning("installing %s failed: %s", version, exc)
            self.state, self.error = "failed", str(exc)

    def reconcile(self, *, wait_s: float = 600.0, poll_s: float = 2.0) -> None:
        """At startup: what happened to the last attempt. A helper that failed put the old
        version back and left its account of why; that is shown once, then cleared.

        The helper is always still running when this starts: it starts this server, then
        waits for it to be healthy before it finishes. So it is waited for -- in the
        background, where this runs -- rather than looked at once and missed.
        """
        self._probe()
        if self._docker is None or self._me is None:
            return
        name = helper_name(self._me)
        deadline = time.monotonic() + wait_s
        while True:
            try:
                helper = self._docker.container(name)
            except DockerError:
                return
            state = helper.get("State") or {}
            if not state.get("Running"):
                break
            if time.monotonic() >= deadline:
                return
            time.sleep(poll_s)
        if state.get("ExitCode"):
            lines = [ln for ln in self._docker.logs(name, 20).splitlines() if ln.strip()]
            self.state = "failed"
            self.error = lines[-1] if lines else f"exited with {state.get('ExitCode')}"
        with contextlib.suppress(DockerError):
            self._docker.remove(name, force=True)


def helper_name(me: dict[str, Any]) -> str:
    return f"{str(me['Name']).lstrip('/')}-update"


def helper_body(me: dict[str, Any], image: str, socket_path: str) -> dict[str, Any]:
    """The helper: the new image, the socket, and nothing else. No volumes -- it has no
    business with the data it is carrying over, only with the daemon.

    The socket is mounted from wherever the host has it, which is where this container
    got its own; and the helper joins the same groups, because on most hosts the socket
    is writable by a group, not by the user the image runs as.
    """
    source = next(
        (
            m.get("Source") or socket_path
            for m in me.get("Mounts") or []
            if m.get("Destination") == socket_path
        ),
        socket_path,
    )
    host: dict[str, Any] = {"Binds": [f"{source}:{DEFAULT_SOCKET}"]}
    if (me.get("HostConfig") or {}).get("GroupAdd"):
        host["GroupAdd"] = me["HostConfig"]["GroupAdd"]
    return {
        "Image": image,
        "Cmd": ["self-update", "--container", me["Id"], "--image", image],
        "User": (me.get("Config") or {}).get("User", ""),
        "Labels": {"org.slipwright.role": "update"},
        # the image's check asks for a server the helper never runs
        "Healthcheck": {"Test": ["NONE"]},
        "HostConfig": host,
    }


def checker(updater: Updater, every_s: float, stop: threading.Event) -> None:
    """Ask the registry now and every ``every_s`` after, until the server stops."""
    updater.reconcile()
    while True:
        updater.check()
        if stop.wait(every_s):
            return


__all__ = [
    "CHECK_EVERY_S",
    "DEFAULT_IMAGE",
    "Docker",
    "DockerError",
    "EngineAPI",
    "Status",
    "ReleaseNotes",
    "UpdateRefused",
    "Updater",
    "backup_sqlite",
    "changelog_section",
    "checker",
    "helper_body",
    "latest_release",
    "own_container",
    "recreated",
    "release_notes",
    "replace",
    "running_version",
    "version_key",
]
