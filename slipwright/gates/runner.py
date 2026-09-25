"""Where a project's own commands actually run.

``build_cmd``, ``test_cmd`` and ``run_cmd`` are written by a model and then executed. On
a machine of your own that is the tool working as intended. On a server people sign up
to, it is somebody else's shell on your box, and the only honest answer is to give it a
box of its own.

Two runners, one interface:

* ``LocalRunner`` runs the command where the server runs, with a scrubbed environment.
  It is what a single-team installation wants and what the test suite uses: the machine
  already belongs to the person whose agents are writing the commands.
* ``DockerRunner`` runs it in a container that is thrown away afterwards, with no
  network, no privileges, a read-only root filesystem and nothing mounted but the one
  worktree. It is what a hosted installation must use, because there the commands are
  written on behalf of strangers.

``SLIPWRIGHT_RUNNER`` picks one. There is no default-to-safe here and that is
deliberate: a container runner that silently fell back to running on the host would be
worse than none, because the installation would believe it was isolated. If Docker is
asked for and is not there, jobs fail and say why.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from slipwright.gates.env import project_env

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 900.0
#: Where the worktree is mounted inside a container. Short, and not a path anything in a
#: project is likely to hard-code.
WORKDIR = "/work"


@dataclass(frozen=True)
class Limits:
    """What one command may consume. Only the container runner can enforce them."""

    memory: str = "2g"
    cpus: str = "2"
    pids: int = 512
    #: ``none`` is the safe default; a project that genuinely has to fetch dependencies
    #: is given ``bridge`` by the installation, knowingly.
    network: str = "none"
    image: str = "slipwright-runner:local"


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    output: str


class Runner(Protocol):
    def run(
        self,
        cmd: str,
        cwd: Path,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        extra_env: Mapping[str, str] | None = None,
    ) -> CommandResult: ...


class LocalRunner:
    """The command, where the server is. Isolation is the machine's, not ours."""

    name = "local"

    def run(
        self,
        cmd: str,
        cwd: Path,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        extra_env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        try:
            proc = subprocess.run(  # noqa: S602 - a model wrote this; see the module docstring
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=project_env(dict(extra_env or {})),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(124, _timed_out(exc, timeout_s))
        return CommandResult(proc.returncode, proc.stdout + proc.stderr)


@dataclass
class DockerRunner:
    """The command, in a container that exists for the length of it and no longer.

    What the container does *not* have is the point of the class: no network, no added
    capabilities, no way to gain privileges, a read-only root filesystem, and one
    writable mount -- the worktree the job is working in. Nothing else on the host is
    reachable, including the state directory, the key beside it, and every other
    tenant's worktree.
    """

    name = "docker"
    limits: Limits = field(default_factory=Limits)
    docker: str = "docker"
    #: Which uid the command runs as inside the container. Not root, so a file it writes
    #: into the mounted worktree is not owned by root on the host either.
    user: str = "1000:1000"

    def available(self) -> bool:
        return shutil.which(self.docker) is not None

    def run(
        self,
        cmd: str,
        cwd: Path,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        extra_env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        if not self.available():
            return CommandResult(
                125,
                f"the {self.name} runner is configured but {self.docker!r} is not on PATH; "
                "install it or set SLIPWRIGHT_RUNNER=local",
            )
        argv = self._argv(cmd, cwd, extra_env)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                # the *docker client* gets a scrubbed environment too: it needs only a
                # PATH and, where set, DOCKER_HOST
                env=project_env(
                    {k: v for k, v in os.environ.items() if k.startswith("DOCKER_")}
                ),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(124, _timed_out(exc, timeout_s))
        return CommandResult(proc.returncode, proc.stdout + proc.stderr)

    def _argv(self, cmd: str, cwd: Path, extra_env: Mapping[str, str] | None) -> list[str]:
        limits = self.limits
        argv = [
            self.docker,
            "run",
            "--rm",
            # a name to find it by if it ever outlives its command
            "--name",
            f"slipwright-{uuid.uuid4().hex[:12]}",
            f"--network={limits.network}",
            f"--memory={limits.memory}",
            f"--cpus={limits.cpus}",
            f"--pids-limit={limits.pids}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            # builds need somewhere to write that is not the image
            "--tmpfs=/tmp:rw,exec,nosuid,size=1g",
            f"--user={self.user}",
            "-v",
            f"{cwd.resolve()}:{WORKDIR}:rw",
            "-w",
            WORKDIR,
        ]
        for key, value in _container_env(extra_env).items():
            argv += ["-e", f"{key}={value}"]
        argv += [limits.image, "sh", "-lc", cmd]
        return argv


def _container_env(extra: Mapping[str, str] | None) -> dict[str, str]:
    """What the *container* sees. Nothing is inherited: the image brings its own PATH and
    HOME, and only what this run needs is added."""
    env = {"CI": "1", "HOME": WORKDIR, "LANG": "C.UTF-8"}
    env.update(dict(extra or {}))
    return env


def _timed_out(exc: subprocess.TimeoutExpired, timeout_s: float) -> str:
    out = exc.stdout or ""
    text = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
    return f"{text}\n[timed out after {timeout_s:.0f}s]"


def build_runner(
    name: str | None = None, *, limits: Limits | None = None, env: Mapping[str, str] | None = None
) -> Runner:
    """The runner this installation is configured for.

    An unknown name is an error rather than a fallback: "I asked for isolation and got
    none" must not be something an installation can be in without knowing.
    """
    source = os.environ if env is None else env
    chosen = (name or source.get("SLIPWRIGHT_RUNNER") or "local").strip().lower()
    if chosen == "local":
        return LocalRunner()
    if chosen == "docker":
        return DockerRunner(limits=limits or _limits_from(source))
    raise ValueError(f"unknown runner {chosen!r} (expected 'local' or 'docker')")


def _limits_from(env: Mapping[str, str]) -> Limits:
    return Limits(
        memory=env.get("SLIPWRIGHT_RUNNER_MEMORY", Limits.memory),
        cpus=env.get("SLIPWRIGHT_RUNNER_CPUS", Limits.cpus),
        pids=int(env.get("SLIPWRIGHT_RUNNER_PIDS", Limits.pids)),
        network=env.get("SLIPWRIGHT_RUNNER_NETWORK", Limits.network),
        image=env.get("SLIPWRIGHT_RUNNER_IMAGE", Limits.image),
    )


__all__: Sequence[str] = [
    "DEFAULT_TIMEOUT_S",
    "WORKDIR",
    "CommandResult",
    "DockerRunner",
    "Limits",
    "LocalRunner",
    "Runner",
    "build_runner",
]
