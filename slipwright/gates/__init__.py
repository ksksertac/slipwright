"""Build gate: the profile's build and test commands, run in the job's worktree.

Deterministic and model-free. A non-zero exit from either command fails the gate and the
combined output is what the Developer gets back for a fix attempt.

*Where* they run is the runner's business (``gates/runner.py``): on the server for a
local installation, in a throwaway container for a hosted one. This module only decides
what to run and what a failure means.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class GateResult:
    ok: bool
    output: str
    seconds: float = 0.0  # how long the commands took, for the run this is recorded as

    @property
    def tail(self) -> str:
        return self.output[-MAX_OUTPUT_CHARS:]


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
