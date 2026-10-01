"""``slipwright worker``: the Mac's side of a paired worker (T14.4).

It calls out and nothing calls in. Paired once with a connection code, it keeps the token
it was given and from then on only asks the server whether there is something to build,
builds it in a directory of its own, and says what happened. It is the same package as
the server, installed on the Mac, and runs as a plain process -- never in Docker, which on
a Mac is a Linux VM with no Xcode in it.

What it builds is written by a model, so it is treated the way the server treats a
project's commands (``gates/env.py``): an environment of named variables only, a fresh
directory per build that is deleted afterwards, and only the commands of the build it
was handed. Running it as a macOS user of its own keeps those commands away from the
Keychain and SSH keys of the person who owns the Mac; the README says so.
"""

from __future__ import annotations

import io
import ipaddress
import json
import logging
import os
import platform as _platform
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from slipwright import workers as pairing
from slipwright.gates.env import project_env

log = logging.getLogger(__name__)

#: How often a long build tells the server it is still there (it counts a worker gone
#: after ``workers.LIVE``, 90 s).
HEARTBEAT_S = 20.0
#: Kept for every build's output, as the server's gate keeps it.
MAX_OUTPUT = 200_000
LAUNCH_LABEL = "com.slipwright.worker"


class Unpaired(RuntimeError):
    """This Mac has no pairing, or the server no longer knows it (it was removed)."""


# -- where it keeps its pairing -------------------------------------------------------------


def config_path(home: Path | None = None) -> Path:
    home = home or Path.home()
    if _platform.system() == "Darwin":
        return home / "Library" / "Application Support" / "Slipwright" / "worker.json"
    return home / ".config" / "slipwright" / "worker.json"


def load_config(path: Path | None = None) -> dict[str, str] | None:
    path = path or config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("token") else None


def save_config(data: dict[str, str], path: Path | None = None) -> Path:
    """Written readable by this user alone: the token is the worker's whole identity."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    return path


# -- what this machine can build -------------------------------------------------------------


@dataclass
class Found:
    """What a look around the machine found: the platforms it can build, the variables
    a build needs to find them, and what is missing, said the way a person would fix it."""

    capabilities: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def detect(
    env: Mapping[str, str] | None = None,
    *,
    system: str | None = None,
    home: Path | None = None,
    run: Callable[[list[str]], int] | None = None,
) -> Found:
    """Look for Xcode and for a JDK with an Android SDK.

    ``xcodebuild`` is run, not just found: the Command Line Tools install a stub of it
    that only says Xcode is required. Android Studio keeps its SDK under
    ``~/Library/Android/sdk`` and a JDK inside the app, so both are looked for there when
    the environment does not name them.
    """
    source = dict(os.environ if env is None else env)
    system = system or _platform.system()
    home = home or Path.home()
    run = run or _exit_code
    found = Found()

    if system == "Darwin":
        if (
            shutil.which("xcodebuild", path=source.get("PATH"))
            and run(["xcodebuild", "-version"]) == 0
        ):
            found.capabilities.append("ios")
        else:
            found.missing.append(
                "iOS: Xcode not found -- install it from the App Store, open it once"
            )
    sdk = source.get("ANDROID_HOME") or source.get("ANDROID_SDK_ROOT")
    if not sdk and (home / "Library" / "Android" / "sdk").is_dir():
        sdk = str(home / "Library" / "Android" / "sdk")
    java = source.get("JAVA_HOME")
    studio = Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home")
    if not java and studio.is_dir():
        java = str(studio)
    if sdk and (Path(sdk) / "platforms").is_dir() and (java or shutil.which("java")):
        found.capabilities.append("android")
        found.env["ANDROID_HOME"] = sdk
        if java:
            found.env["JAVA_HOME"] = java
    else:
        found.missing.append("Android: no Android SDK with a JDK -- install Android Studio")
    return found


def machine_name(
    *, system: str | None = None, ask: Callable[[list[str]], str | None] | None = None
) -> str:
    """What the person calls this machine: "Sertac's MacBook Pro", as System Settings
    shows it. ``socket.gethostname()`` is not that on a Mac -- with no name from the
    network's DNS it answers the IP address, and the Mac Connect page listed a Mac as
    ``192.168.1.11``."""
    if (system or _platform.system()) == "Darwin":
        said = (ask or _output)(["scutil", "--get", "ComputerName"])
        if said and said.strip():
            return said.strip()[:120]
    return socket.gethostname()[:120] or "Mac"


def _output(argv: list[str]) -> str | None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=10)  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _exit_code(argv: list[str]) -> int:
    try:
        return subprocess.run(argv, capture_output=True, timeout=60).returncode  # noqa: S603
    except (OSError, subprocess.SubprocessError):
        return 1


# -- pairing ------------------------------------------------------------------------------


def pair(
    code: str,
    *,
    name: str | None = None,
    client: httpx.Client | None = None,
    look_around: Callable[[int], list[str]] | None = None,
) -> dict[str, str]:
    """Trade a connection code for a token, and keep both with the address that took it.

    The code's address is tried first. A code made at ``localhost`` has none -- only a
    port -- and an address can go stale, so after it come this Mac itself (the server in
    Docker beside the worker) and then the hosts of this Mac's own network that answer on
    that port. Only the server that made the code accepts it, so a wrong door costs a
    refusal and nothing else.
    """
    address, _secret = pairing.unpack(code)  # a bad copy is refused before the network
    name = name or machine_name()
    http = client or httpx.Client(timeout=30)
    body = {"code": code, "name": name, "capabilities": detect().capabilities}
    refused: str | None = None
    for candidate in _candidates(address, look_around or nearby_servers):
        try:
            got = http.post(f"{candidate}/api/worker/pair", json=body)
        except httpx.TransportError:
            continue
        if got.status_code == 200:
            answer = got.json()
            return {
                "address": candidate,
                "worker_id": answer["worker_id"],
                "token": answer["token"],
                "name": name,
            }
        # the first refusal is the one to show: a server further down the list that
        # never made this code would only say it does not know it
        refused = refused or _detail(got)
    if refused:
        raise Unpaired(refused)
    port = urlsplit(address).port or 80
    raise Unpaired(
        f"no Slipwright server found: tried {address}, this Mac and its network on port "
        f"{port}. Is the Mac on the same network as the server?"
    )


def _candidates(address: str, look_around: Callable[[int], list[str]]) -> Iterator[str]:
    """Where the server may be, best first. Lazy: the network is only searched when
    nothing nearer answered."""
    parts = urlsplit(address)
    if pairing.reachable(address):
        yield address
    if parts.scheme != "http":
        return  # a server behind https has a real name; it is not looked for nearby
    port = parts.port or 80
    yield f"http://localhost:{port}"
    for host in look_around(port):
        yield f"http://{host}:{port}"


def nearby_servers(port: int) -> list[str]:
    """The hosts of this Mac's network (its /24) that accept a connection on ``port``.

    A probe is only a TCP connect, a few hundred milliseconds at most and many at once,
    so the whole of a home network is looked at in a second or two.
    """
    me = _own_address()
    if me is None:
        return []
    hosts = [str(h) for h in ipaddress.ip_network(f"{me}/24", strict=False).hosts() if str(h) != me]
    with ThreadPoolExecutor(max_workers=64) as pool:
        answers = list(pool.map(lambda host: _answers(host, port), hosts))
    return [host for host, ok in zip(hosts, answers, strict=True) if ok]


def _own_address() -> str | None:
    """This Mac's address on its network: the one a packet out would leave from. A UDP
    socket that is only connected sends nothing."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # TEST-NET: never routed anywhere real
            me = str(probe.getsockname()[0])
    except OSError:
        return None
    return None if ipaddress.ip_address(me).is_loopback else me


def _answers(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail") or response.text)
    except ValueError:
        return response.text or f"HTTP {response.status_code}"


# -- building ------------------------------------------------------------------------------


class Worker:
    """One paired worker: poll, build, report. ``client`` and ``found`` are injectable so
    the loop can be driven against a test server."""

    def __init__(
        self,
        config: Mapping[str, str],
        *,
        client: httpx.Client | None = None,
        found: Found | None = None,
        name: str | None = None,
    ) -> None:
        self.address = config["address"].rstrip("/")
        # asked afresh each start, not read from the pairing: that is how a rename (or a
        # pairing that kept an IP address for a name) reaches the page
        self.name = name or machine_name()
        self.headers = {"Authorization": f"Bearer {config['token']}"}
        self.http = client or httpx.Client(
            timeout=httpx.Timeout(60, read=pairing.LIVE.total_seconds())
        )
        self.found = found or detect()

    def _url(self, path: str) -> str:
        return f"{self.address}/api/worker{path}"

    def _check(self, response: httpx.Response) -> httpx.Response:
        if response.status_code == 401:
            raise Unpaired("the server does not know this Mac any more; pair it again")
        return response

    def once(self, wait_s: float = 25.0) -> bool:
        """Ask for one build and do it. True when there was one."""
        got = self._check(
            self.http.post(
                self._url("/poll"),
                json={
                    "capabilities": self.found.capabilities,
                    "wait_s": wait_s,
                    "name": self.name,
                },
                headers=self.headers,
            )
        )
        if got.status_code == 204:
            return False
        got.raise_for_status()
        task = got.json()
        packed = self._check(
            self.http.get(self._url(f"/tasks/{task['id']}/snapshot"), headers=self.headers)
        )
        packed.raise_for_status()
        result = self.build(task, packed.content)
        self._check(
            self.http.post(
                self._url(f"/tasks/{task['id']}/result"), json=result, headers=self.headers
            )
        )
        return True

    def build(self, task: Mapping[str, Any], packed: bytes) -> dict[str, Any]:
        """Unpack the worktree somewhere fresh, run the commands in order, stop at the first
        that fails -- the same record the server's own gate writes."""
        started = time.monotonic()
        chunks: list[str] = []
        code = 0
        stop = threading.Event()
        beat = threading.Thread(target=self._heartbeat, args=(stop,), daemon=True)
        beat.start()
        try:
            with tempfile.TemporaryDirectory(prefix="slipwright-build-") as scratch:
                where = Path(scratch)
                with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as tar:
                    tar.extractall(where, filter="data")  # nothing outside, no devices
                env = project_env(self.found.env)
                for label, cmd in task["commands"]:
                    code, output = _run(cmd, where, env, float(task["timeout_s"]))
                    chunks.append(f"$ {cmd}\n{output.rstrip()}\n[{label}: exit {code}]")
                    if code != 0:
                        break
        finally:
            stop.set()
        text = "\n\n".join(chunks)
        return {
            "exit_code": code,
            "output": text[-MAX_OUTPUT:],
            "seconds": time.monotonic() - started,
        }

    def _heartbeat(self, stop: threading.Event) -> None:
        while not stop.wait(HEARTBEAT_S):
            try:
                self.http.post(self._url("/heartbeat"), headers=self.headers)
            except httpx.HTTPError as exc:
                log.warning("heartbeat not sent: %s", exc)

    def forever(self) -> None:
        """Poll until stopped. The network going away is waited out, not given up on; a
        server that no longer knows this Mac is the one thing that ends it."""
        pause = 1.0
        while True:
            try:
                self.once()
                pause = 1.0
            except Unpaired:
                raise
            except httpx.HTTPError as exc:
                log.warning("cannot reach %s (%s); trying again in %.0fs", self.address, exc, pause)
                time.sleep(pause)
                pause = min(pause * 2, 60.0)


def _run(cmd: str, cwd: Path, env: Mapping[str, str], timeout_s: float) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S602 - a project's command, which is a shell line
            cmd,
            shell=True,
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        out = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout or b"").decode(errors="replace")
        )
        return 124, f"{out}\n[timed out after {timeout_s:.0f}s]"
    return proc.returncode, proc.stdout + proc.stderr


# -- running at login ---------------------------------------------------------------------


def launch_agent(program: list[str], home: Path | None = None) -> tuple[Path, str]:
    """The launchd agent that starts the worker at login and again if it stops: its path
    and its text."""
    home = home or Path.home()
    log_file = home / "Library" / "Logs" / "slipwright-worker.log"
    args = "\n".join(f"    <string>{_xml(a)}</string>" for a in program)
    text = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LAUNCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args}
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{_xml(str(log_file))}</string>
  <key>StandardErrorPath</key>
  <string>{_xml(str(log_file))}</string>
</dict>
</plist>
"""
    return home / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist", text


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = [
    "Found",
    "Unpaired",
    "Worker",
    "config_path",
    "detect",
    "launch_agent",
    "load_config",
    "pair",
    "save_config",
]
