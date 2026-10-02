"""Build gate: the profile's build and test commands, run in the job's worktree.

Deterministic and model-free. A non-zero exit from either command fails the gate and the
combined output is what the Developer gets back for a fix attempt.

*Where* they run is the runner's business (``gates/runner.py``): on the server for a
local installation, in a throwaway container for a hosted one. This module only decides
what to run and what a failure means.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from slipwright.gates.env import ALLOWED, OWN_ENVIRONMENT, project_env
from slipwright.gates.runner import (
    DEFAULT_TIMEOUT_S,
    CommandResult,
    Runner,
    build_runner,
)
from slipwright.schemas.profile import Profile

MAX_OUTPUT_CHARS = 20_000
#: What of a failed build a model is sent, on every retry (T15.8). Most of a build's
#: output is progress; the errors are a few lines in it.
MAX_MODEL_CHARS = 6_000
#: A line that reports a failure: a word that says so, a test runner's cross, or a
#: compiler's ``file.ext:line`` (Kotlin's ``e: file:///…/App.kt:12:5``, tsc's
#: ``src/a.ts(3,7)``, Python's ``File "x.py", line 4``).
_ERROR_LINE = re.compile(
    r"(?i)\b(error|errors|failed|failure|exception|traceback|cannot find|unresolved"
    r"|undefined|not found)\b|[✕✗×]|^\s*e: |\w\.\w+(:\d+|\(\d+,\d+\))|, line \d+"
)
_AROUND = 3


@dataclass(frozen=True)
class GateResult:
    ok: bool
    output: str
    seconds: float = 0.0  # how long the commands took, for the run this is recorded as

    @property
    def tail(self) -> str:
        return self.output[-MAX_OUTPUT_CHARS:]

    @property
    def for_model(self) -> str:
        """What a role fixing this failure is sent: its error lines, then its last lines.
        The person still sees ``tail`` in the run's detail."""
        return condensed(self.output)


def condensed(output: str, limit: int = MAX_MODEL_CHARS) -> str:
    """A build's output cut to ``limit``: every line that reports a failure with a few
    around it, earliest first (the first error is usually the cause), then the end of
    the run. Output with no such line is its tail, as before."""
    if len(output) <= limit:
        return output
    lines = output.splitlines()
    hits = [i for i, line in enumerate(lines) if _ERROR_LINE.search(line)]
    if not hits:
        return f"(the first {len(output) - limit:,} characters were cut)\n{output[-limit:]}"
    tail = output[-(limit // 3) :]
    keep: set[int] = set()
    for i in hits:
        keep.update(range(max(0, i - _AROUND), min(len(lines), i + _AROUND + 1)))
    pieces: list[str] = []
    previous = -2
    for i in sorted(keep):
        if i != previous + 1:
            pieces.append("...")
        pieces.append(lines[i][:400])
        previous = i
    errors = "\n".join(pieces)
    room = limit - len(tail) - 200
    if len(errors) > room:
        errors = errors[:room] + "\n..."
    return (
        f"(the build's error lines, then its last lines; {len(output):,} characters in all)"
        f"\n{errors}\n\n--- the end of the run ---\n{tail}"
    )


def run_command(
    cmd: str,
    cwd: Path,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: Runner | None = None,
) -> tuple[int, str]:
    """One command, wherever this installation runs them."""
    result: CommandResult = (runner or build_runner()).run(cmd, cwd, timeout_s=timeout_s)
    return result.exit_code, result.output


def build_gate(
    profile: Profile,
    worktree: Path,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: Runner | None = None,
    platform: str | None = None,
) -> GateResult:
    """Run ``build_cmd`` then ``test_cmd``; stop at the first failure.

    With a ``platform``, that platform's own pair instead (``Profile.platforms``), labelled
    with its name so a failure says which app it was.
    """
    chosen = runner or build_runner()
    chunks: list[str] = []
    started = time.monotonic()
    build_cmd, test_cmd = profile.commands_for(platform)
    prefix = f"{platform} " if platform else ""
    for label, cmd in ((f"{prefix}build", build_cmd), (f"{prefix}test", test_cmd)):
        code, output = run_command(cmd, worktree, timeout_s, chosen)
        chunks.append(f"$ {cmd}\n{output.rstrip()}\n[{label}: exit {code}]")
        if code != 0:
            return GateResult(
                ok=False, output="\n\n".join(chunks), seconds=time.monotonic() - started
            )
    return GateResult(ok=True, output="\n\n".join(chunks), seconds=time.monotonic() - started)


__all__ = [
    "ALLOWED",
    "DEFAULT_TIMEOUT_S",
    "OWN_ENVIRONMENT",
    "GateResult",
    "build_gate",
    "project_env",
    "run_command",
]
