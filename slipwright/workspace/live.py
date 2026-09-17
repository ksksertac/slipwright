"""Live environment: the project under test, running from the job's worktree on its port.

``up`` starts ``profile.run_cmd`` (with ``{port}`` substituted) as a detached process
group, streams its output to a per-job log file and returns only once the port answers.
``down`` kills the whole process tree. The PID is written next to the log so a restarted
server can still tear the environment down.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from slipwright.gates import project_env
from slipwright.schemas.job import Job
from slipwright.schemas.profile import PORT_PLACEHOLDER

_IS_WINDOWS = sys.platform == "win32"


class LiveEnvError(RuntimeError):
    def __init__(self, message: str, log_tail: str = "") -> None:
        self.log_tail = log_tail
        super().__init__(f"{message}\n--- log tail ---\n{log_tail}" if log_tail else message)


def log_path(logs_root: Path, job: Job) -> Path:
    return logs_root / f"{job.id}.log"


def pid_path(logs_root: Path, job: Job) -> Path:
    return logs_root / f"{job.id}.pid"


def render_run_cmd(run_cmd: str, port: int) -> str:
    return run_cmd.replace(PORT_PLACEHOLDER, str(port))


def port_answers(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _tail(path: Path, lines: int = 40) -> str:
    if not path.exists():
        return ""
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def up(job: Job, logs_root: Path, health_timeout: float = 30.0) -> int:
    """Start the environment; return the PID once the job's port accepts connections."""
    if job.profile is None:
        raise LiveEnvError(f"job {job.id} has no profile; cannot run")
    if job.worktree_path is None or job.port is None:
        raise LiveEnvError(f"job {job.id} has no worktree/port; call Workspace.create first")

    logs_root.mkdir(parents=True, exist_ok=True)
    log = log_path(logs_root, job)
    cmd = render_run_cmd(job.profile.run_cmd, job.port)

    with log.open("ab") as log_file:
        log_file.write(f"$ {cmd}\n".encode())
        log_file.flush()
        proc = subprocess.Popen(  # noqa: S603 - command comes from the approved profile
            cmd,
            shell=True,
            cwd=job.worktree_path,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=project_env({"PORT": str(job.port)}),
            # each flag is a no-op on the other platform; together they give us a
            # process group we can kill as a unit
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if _IS_WINDOWS else 0,
            start_new_session=not _IS_WINDOWS,
        )
    pid: int = proc.pid
    pid_path(logs_root, job).write_text(str(pid), encoding="utf-8")

    deadline = time.monotonic() + health_timeout
    while time.monotonic() < deadline:
        if port_answers(job.port):
            return pid
        if proc.poll() is not None:
            _forget_pid(logs_root, job)
            raise LiveEnvError(
                f"run_cmd exited with {proc.returncode} before port {job.port} answered",
                _tail(log),
            )
        time.sleep(0.1)

    kill_tree(pid)
    _forget_pid(logs_root, job)
    raise LiveEnvError(f"port {job.port} did not answer within {health_timeout:.0f}s", _tail(log))


def down(job: Job, logs_root: Path, grace: float = 5.0) -> None:
    """Stop the environment and wait until the port is free. No-op if nothing is running."""
    pidfile = pid_path(logs_root, job)
    if not pidfile.exists():
        return
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except ValueError:
        pid = None
    if pid is not None:
        kill_tree(pid)
    _forget_pid(logs_root, job)

    if job.port is not None:
        deadline = time.monotonic() + grace
        while port_answers(job.port) and time.monotonic() < deadline:
            time.sleep(0.1)
        if port_answers(job.port):
            raise LiveEnvError(f"port {job.port} still answering {grace:.0f}s after down()")


def is_running(job: Job, logs_root: Path) -> bool:
    return pid_path(logs_root, job).exists() and job.port is not None and port_answers(job.port)


def kill_tree(pid: int) -> None:
    """Kill a process and everything it spawned (the shell and the server behind it)."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    os.killpg(pgid, signal.SIGTERM)
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGKILL)


def _forget_pid(logs_root: Path, job: Job) -> None:
    pid_path(logs_root, job).unlink(missing_ok=True)
