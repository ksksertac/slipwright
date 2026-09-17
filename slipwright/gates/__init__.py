"""Build gate: the profile's build and test commands, run in the job's worktree.

Deterministic and model-free. A non-zero exit from either command fails the gate and the
combined output is what the Developer gets back for a fix attempt.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from slipwright.schemas.profile import Profile

DEFAULT_TIMEOUT_S = 900.0
MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True)
class GateResult:
    ok: bool
    output: str

    @property
    def tail(self) -> str:
        return self.output[-MAX_OUTPUT_CHARS:]


def run_command(cmd: str, cwd: Path, timeout_s: float = DEFAULT_TIMEOUT_S) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S602 - the command comes from the approved profile
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        text = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        return 124, f"{text}\n[timed out after {timeout_s:.0f}s]"
    return proc.returncode, proc.stdout + proc.stderr


def build_gate(
    profile: Profile, worktree: Path, timeout_s: float = DEFAULT_TIMEOUT_S
) -> GateResult:
    """Run ``build_cmd`` then ``test_cmd``; stop at the first failure."""
    chunks: list[str] = []
    for label, cmd in (("build", profile.build_cmd), ("test", profile.test_cmd)):
        code, output = run_command(cmd, worktree, timeout_s)
        chunks.append(f"$ {cmd}\n{output.rstrip()}\n[{label}: exit {code}]")
        if code != 0:
            return GateResult(ok=False, output="\n\n".join(chunks))
    return GateResult(ok=True, output="\n\n".join(chunks))


__all__ = ["DEFAULT_TIMEOUT_S", "GateResult", "build_gate", "run_command"]
