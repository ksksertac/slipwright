"""A ChatGPT subscription, through OpenAI's own Codex CLI.

Somebody with a ChatGPT plan can run the agents on it instead of buying API credit. The
way that is done matters more than anything else in this module: **Slipwright never
speaks to ChatGPT itself.** It runs ``codex exec``, the command OpenAI ships for exactly
this -- a program driving Codex non-interactively -- signed in with the person's own
ChatGPT account through ``codex login --device-auth``. OpenAI's client talks to OpenAI;
nothing here borrows its credentials or pretends to be it.

The sign-in lives in a ``CODEX_HOME`` of its own per account, under the state directory
(never the work directory: a job's commands must not find a live session by relative
path). One is used by one account and by nobody else, and the whole feature is for an
installation somebody runs for themselves -- a hosted one, where strangers would be
spending their plans on a shared machine, has it switched off (``config.py``).

Each call is one ``codex exec --json`` with the system text and the prompt on stdin, in a
throwaway empty directory with a read-only sandbox. The answer is the last
``agent_message``; the tokens are in ``turn.completed``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slipwright.providers import (
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from slipwright.schemas.profile import ThinkingDepth

log = logging.getLogger(__name__)

#: What the model is told first. Codex is an agent that can run commands; here it is only
#: to answer, and everything it needs is in the prompt.
PREAMBLE = (
    "You are answering one request for an automated system. Everything you need is in "
    "this message. Do not run commands, read or write files, or browse: reply with the "
    "answer only, exactly in the format the request asks for.\n\n"
)

_EFFORT = {
    ThinkingDepth.LOW: "low",
    ThinkingDepth.MEDIUM: "medium",
    ThinkingDepth.HIGH: "high",
    ThinkingDepth.MAX: "high",
}

#: Words Codex uses when the plan, not the request, is the problem: nothing to gain from
#: asking again until the window resets or the person signs in again.
_REFUSED = re.compile(
    r"usage limit|rate limit|quota|not logged in|log ?in|unauthori[sz]ed|401|403|plan",
    re.I,
)


def codex_command() -> list[str] | None:
    """How to run the installed ``codex``, or ``None``. ``SLIPWRIGHT_CODEX_BIN`` overrides
    the lookup (a path, or a command line such as ``python fake_codex.py``)."""
    override = os.environ.get("SLIPWRIGHT_CODEX_BIN", "").strip()
    if override:
        # Windows keeps a token's quotes in non-POSIX mode; a quoted path is still a path
        return [t.strip('"') for t in shlex.split(override, posix=os.name != "nt")]
    found = shutil.which("codex")
    return [found] if found else None


def _env(home: Path) -> dict[str, str]:
    """What the CLI sees: its own home, and the path to find itself. Nothing else of the
    server's environment -- no provider keys, no Slipwright secrets."""
    env = {"CODEX_HOME": str(home), "PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    for name in ("SYSTEMROOT", "TEMP", "TMP", "LANG", "SSL_CERT_FILE"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def signed_in(home: Path) -> bool:
    return (home / "auth.json").is_file()


def _events(stdout: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            out.append(event)
    return out


def read_answer(stdout: str) -> tuple[str, int | None, int | None, str | None]:
    """(answer, input tokens, output tokens, error) from ``codex exec --json`` output."""
    text = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    for event in _events(stdout):
        kind = str(event.get("type") or "")
        if kind == "item.completed":
            item = event.get("item") or {}
            if item.get("type") in ("agent_message", "assistant_message") and item.get("text"):
                text = str(item["text"])
        elif kind == "turn.completed":
            usage = event.get("usage") or {}
            if usage.get("input_tokens") is not None:
                tokens_in = int(usage["input_tokens"])
            if usage.get("output_tokens") is not None:
                tokens_out = int(usage["output_tokens"]) + int(
                    usage.get("reasoning_output_tokens") or 0
                )
        elif kind in ("error", "turn.failed"):
            detail = event.get("message") or (event.get("error") or {}).get("message")
            error = str(detail or kind)
    return text, tokens_in, tokens_out, error


def _own_group() -> dict[str, Any]:
    """Popen arguments that start a process at the head of a group of its own, so that
    everything it starts can be ended with it (see ``_kill_tree``)."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(process: subprocess.Popen[str]) -> None:
    """End ``process`` and everything it started.

    ``codex`` on the PATH is a Node script that starts the real, native binary as its
    child. Killing only the process we started killed the wrapper; the binary was handed
    to PID 1 and went on thinking -- on the person's plan -- for an answer nobody was
    waiting for any more. A development whose calls kept timing out left one of these
    behind every ten minutes, each still spending, and stopping the development did not
    touch them."""
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603 - our own argv, no shell
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],  # noqa: S607
            capture_output=True,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):  # already gone
            os.killpg(process.pid, signal.SIGKILL)
    process.kill()  # whatever the group kill missed, the head at least


def _run_tree(
    args: list[str], stdin: str, *, cwd: str, env: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """``subprocess.run`` with a timeout that ends the whole tree, not only its head."""
    with subprocess.Popen(  # noqa: S603 - our own argv, no shell
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env=env,
        **_own_group(),
    ) as process:
        try:
            out, err = process.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            raise
        except BaseException:
            _kill_tree(process)  # the server stopping mid-call leaves nothing behind either
            raise
    return subprocess.CompletedProcess(args, process.returncode, out, err)


class CodexProvider:
    """Runs one ``codex exec`` per request, signed in as one account."""

    def __init__(self, home: Path, *, command: list[str] | None = None) -> None:
        self.home = Path(home)
        found = command or codex_command()
        if not found:
            raise ProviderUnavailableError(
                "the Codex CLI is not installed here (npm install -g @openai/codex)"
            )
        self.command = found

    def complete(self, request: ModelRequest) -> ModelResponse:
        if not signed_in(self.home):
            raise ProviderRejectedError(
                "ChatGPT is not signed in: Settings → Models → ChatGPT subscription → Sign in"
            )
        args = [
            *self.command,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
        ]
        if request.model and request.model != "default":
            args += ["-m", request.model]
        if request.thinking_depth is not ThinkingDepth.OFF:
            args += ["-c", f'model_reasoning_effort="{_EFFORT[request.thinking_depth]}"']
        stdin = f"{PREAMBLE}{request.system}\n\n{request.prompt}"
        with (
            tempfile.TemporaryDirectory(prefix="slipwright-codex-") as empty,
            tempfile.TemporaryDirectory(prefix="slipwright-codex-img-") as pictures,
        ):
            if request.images:
                # the CLI takes pictures as files. One ``--image=a,b`` rather than
                # ``--image a b``: the flag takes several values and would swallow the
                # ``-`` that says the prompt is on stdin
                paths = _write_images(Path(pictures), request)
                args.append("--image=" + ",".join(str(p) for p in paths))
                stdin = _labels(request) + stdin
            args.append("-")  # the prompt comes on stdin: far longer than a command line allows
            try:
                done = _run_tree(
                    args, stdin, cwd=empty, env=_env(self.home), timeout=request.timeout_s
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderTimeoutError(f"codex exec timed out after {exc.timeout}s") from exc
            except OSError as exc:
                raise ProviderUnavailableError(f"could not run the Codex CLI: {exc}") from exc
        text, tokens_in, tokens_out, error = read_answer(done.stdout)
        spent = {"input_tokens": tokens_in, "output_tokens": tokens_out}
        if error or (done.returncode != 0 and not text):
            why = error or (done.stderr or done.stdout).strip()[-400:] or f"exit {done.returncode}"
            if _REFUSED.search(why):
                raise ProviderRejectedError(f"ChatGPT refused: {why}", **spent)
            raise ProviderError(f"codex exec failed: {why}", **spent)
        if not text:
            raise ProviderError("codex exec gave no answer", **spent)
        return ModelResponse(
            text=text,
            model=request.model,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            stop_reason="stop",
        )

    def list_models(self) -> list[str]:
        """``default`` -- whatever the plan gives Codex -- and the models Codex has seen,
        when it keeps a cache of them. There is no listing to ask for."""
        if not signed_in(self.home):
            raise ProviderRejectedError("ChatGPT is not signed in")
        found: list[str] = []
        cache = self.home / "models_cache.json"
        try:
            data: Any = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        models = data.get("models") if isinstance(data, dict) else data
        for m in models or []:
            if isinstance(m, dict):
                slug = m.get("slug") or m.get("id") or m.get("model")
                if slug:
                    found.append(str(slug))
            elif isinstance(m, str):
                found.append(m)
        return ["default", *sorted(set(found))]


def _write_images(folder: Path, request: ModelRequest) -> list[Path]:
    paths: list[Path] = []
    for n, image in enumerate(request.images, start=1):
        ext = "png" if image.media_type == "image/png" else "jpg"
        path = folder / f"image-{n}.{ext}"
        path.write_bytes(image.data)
        paths.append(path)
    return paths


def _labels(request: ModelRequest) -> str:
    """The CLI shows the pictures without their labels, so the prompt says which is which."""
    named = [f"Image {n}: {i.label}" for n, i in enumerate(request.images, start=1) if i.label]
    return ("\n".join(named) + "\n\n") if named else ""


# -- signing in ----------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_URL = re.compile(r"https://\S+")
_CODE = re.compile(r"\b([A-Z0-9]{4,5}-[A-Z0-9]{4,6})\b")


@dataclass
class Login:
    """One ``codex login --device-auth`` in progress."""

    process: subprocess.Popen[str]
    url: str | None = None
    code: str | None = None
    lines: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    @property
    def running(self) -> bool:
        return self.process.poll() is None


class Logins:
    """The sign-ins in progress, one per ``CODEX_HOME``. The CLI prints a link and a code,
    then waits for the person to approve it in a browser; the page shows the two and asks
    here until ``auth.json`` appears."""

    #: A code nobody enters is dropped; OpenAI's own device codes expire in about as long.
    TTL_S = 15 * 60

    def __init__(self, command: list[str] | None = None) -> None:
        self.command = command
        self._lock = threading.Lock()
        self._running: dict[Path, Login] = {}

    def start(self, home: Path, *, wait_s: float = 20.0) -> Login:
        home = Path(home)
        home.mkdir(parents=True, exist_ok=True)
        with self._lock:
            current = self._running.get(home)
            if current and current.running and current.code:
                return current
            if current and current.running:
                _kill_tree(current.process)
            command = self.command or codex_command()
            if not command:
                raise ProviderUnavailableError(
                    "the Codex CLI is not installed here (npm install -g @openai/codex)"
                )
            process = subprocess.Popen(  # noqa: S603 - our own argv, no shell
                [*command, "login", "--device-auth"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_env(home),
                cwd=str(home),
                **_own_group(),
            )
            login = Login(process)
            self._running[home] = login
        threading.Thread(target=self._read, args=(login,), daemon=True).start()
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline and login.running and not (login.url and login.code):
            time.sleep(0.1)
        if not (login.url and login.code):
            said = " ".join(login.lines)[-400:]
            if login.running:
                _kill_tree(login.process)
            raise ProviderError(f"codex login gave no code: {said or 'no output'}")
        return login

    @staticmethod
    def _read(login: Login) -> None:
        assert login.process.stdout is not None
        for raw in login.process.stdout:
            line = _ANSI.sub("", raw).strip()
            if not line:
                continue
            login.lines.append(line)
            if login.url is None and (m := _URL.search(line)):
                login.url = m.group(0).rstrip(".,)")
            if login.code is None and (m := _CODE.search(line)):
                login.code = m.group(1)
            # the CLI keeps running until approved; nothing more to do here

    def status(self, home: Path) -> str:
        """``signed_in``, ``waiting`` (a code is out) or ``signed_out``."""
        home = Path(home)
        if signed_in(home):
            return "signed_in"
        with self._lock:
            login = self._running.get(home)
            if login and login.running and time.monotonic() - login.started > self.TTL_S:
                _kill_tree(login.process)
            if login and login.running:
                return "waiting"
        return "signed_out"

    def sign_out(self, home: Path) -> None:
        home = Path(home)
        with self._lock:
            login = self._running.pop(home, None)
        if login and login.running:
            _kill_tree(login.process)
        (home / "auth.json").unlink(missing_ok=True)


__all__ = [
    "CodexProvider",
    "Login",
    "Logins",
    "codex_command",
    "read_answer",
    "signed_in",
]
