"""Developer: implements exactly one plan phase per invocation.

The Developer sees the whole plan for orientation but is told which phase is its own.
It returns full contents for every file it touches; the engine writes them into the
worktree and records the diff. When a build gate failed, the captured output is passed
back so the next invocation is a fix attempt on the same phase.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import (
    base_context,
    list_tree,
    plan_outline,
    project_facts,
    read_files,
    require_worktree,
    where_it_runs,
)
from slipwright.roles.results import DeveloperResult
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Implement the plan phase named in `current_phase` and nothing beyond it. Return the
complete new contents of every file you create or change (`content: null` deletes a
file); paths are relative to the project root. Keep changes minimal and consistent with
the existing code. Set `phase_complete` to true when the phase's goal is met.
If `build_failure` is present, the build or tests failed after your previous attempt on
this phase: read the output, fix the cause, and return the corrected files. When
`qa_diagnosis` is there too, QA has already read that failure and says the code is the
side that is wrong and what it must do instead: start from that reading, and do not
change the test it names to make the failure go away.
If a `jira` section is present you are expected to keep the tracker current: transition
`current_task_key` to in progress, and add a short comment on it (and `log_work` with a
realistic estimate) describing what you changed.
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""

REVIEW_FIX = """
If `standards_review` is present, your previous change for this phase passed the build
but the standards review found the listed `violations` (each names the section, the file
and a fix); the phase already committed, so return only the files that change to resolve
every violation, and set `phase_complete` to true."""

IN_PARTS = """
Work in parts. If `output_was_truncated` is present, your previous answer was cut off at
the output limit and was thrown away: return only the most important files now (a few
files, complete contents) and set `phase_complete` to false — you will be called again
for the rest. If `continuation` is present, the files listed in `files_so_far` are
already written from your earlier parts (do not repeat them unless they must change);
continue with the next files and set `phase_complete` to true only when the phase's goal
is fully met. If `continuation.new_instruction` is present, a person wrote to you while
you were writing the files so far: `messages_from_human` has what they said. Change what
is already written where it no longer follows it, then carry on."""

CUT_FILES = """
A file listed in `files_cut` was too large to be sent whole: you see only its start. Never
return its whole contents -- they would replace the part you did not see. Change it with
`edits` instead, `content: null`: each an exact `find` copied from the file, long enough to
occur in it once, and its `replace`."""

EDIT_FAILED = """
If `continuation.edit_failed` is present, your previous answer was not applied: it names
the change that did not fit and shows the file's real lines; return your changes again,
with any `find` copied from those lines."""

# A specialist changes a file by returning all of it, so a file it may change has to reach
# it whole: cut at 12,000 characters, App.tsx arrived without the line the build failed on,
# the specialist rightly returned nothing, and the development stopped as if the machine
# were broken. Files it is only reading for orientation keep the small cut (MAX_FILE_BYTES).
EDITABLE_FILE_BYTES = 100_000
# ... and all of them together stay inside a prompt that still has to hold the plan, the
# tree, the standards and the build output
EDITABLE_TOTAL_BYTES = 300_000
# how many files a build failure may add: a failure naming forty files is a broken
# toolchain, not forty things to edit
MAX_FAILURE_FILES = 8

# a path in a compiler's or a test runner's output: "App.tsx(225,11)", "src/a.ts:12:3",
# "e: file:///work/x/app/src/Main.kt:12:3", "  at Object.<anonymous> (src/x.test.ts:4:9)"
_PATH_IN_OUTPUT = re.compile(
    r"(?:file://)?((?:[A-Za-z]:)?[\w./\\@+-]*[\w-]\.[A-Za-z]\w{0,7})(?=[(:\s,)'\"]|$)"
)


def files_in_output(worktree: Path, output: str, limit: int = MAX_FAILURE_FILES) -> list[str]:
    """The project's own files a build or test failure names, in the order it names them.

    Only paths that are files in this worktree count, so a library's path, a URL or a
    version number never turn into something the specialist is told to edit."""
    root = worktree.resolve()
    found: list[str] = []
    for match in _PATH_IN_OUTPUT.finditer(output):
        raw = match.group(1).replace("\\", "/")
        candidate = Path(raw)
        try:
            # rooted ("/work/...", "C:/...") means somewhere on the machine: it counts only
            # when it is inside this worktree
            if candidate.is_absolute() or raw.startswith("/"):
                rel = candidate.resolve().relative_to(root).as_posix()
            else:
                rel = Path(raw.removeprefix("./")).as_posix()
        except (ValueError, OSError):
            continue
        if rel in found or rel.startswith("../") or not (root / rel).is_file():
            continue
        found.append(rel)
        if len(found) >= limit:
            break
    return found


def editable_files(job: Job, worktree: Path) -> list[str]:
    """The files this call may change: the phase's own, then what its failure names."""
    plan = job.data.plan or {}
    phases: list[dict[str, Any]] = plan.get("phases", [])
    index = job.data.phase_index
    phase = phases[index] if index < len(phases) else {}
    names = [str(f) for f in phase.get("files", [])]
    if job.data.last_build_output:
        names += files_in_output(worktree, job.data.last_build_output)
    for violation in job.data.review_violations or []:
        if isinstance(violation, dict) and violation.get("file"):
            names.append(str(violation["file"]))
    return list(dict.fromkeys(names))


def too_large(worktree: Path, names: list[str]) -> list[str]:
    """Which of these files cannot be sent whole, by the same budget ``run`` sends them by."""
    cut: list[str] = []
    budget = EDITABLE_TOTAL_BYTES
    for name in names:
        path = worktree / name
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > EDITABLE_FILE_BYTES or size > budget:
            cut.append(name)
        else:
            budget -= size
    return cut


FIX_INSTRUCTIONS = """\
The change set on this branch is complete but `ci_failure` shows the continuous
integration run failed. Read the log, fix the cause, and return the corrected files
(complete contents; paths relative to the project root). Set `phase_complete` to true.
If a `standards` section is present its sections are binding unless they contradict
the core rules; say in `summary` when one could not be followed and why."""


def run(
    job: Job,
    profile: Profile,
    *,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    ci_failure: str | None = None,
    jira: dict[str, Any] | None = None,
    as_role: RoleName = RoleName.BACKEND,
    standards: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    truncated: str | None = None,
    continuation: dict[str, Any] | None = None,
) -> RoleResult:
    """Run the generic developer or, with ``role``, one of the specialists."""
    from slipwright.roles import designer
    from slipwright.roles.specialists import INSTRUCTIONS as SPECIALIST_INSTRUCTIONS

    plan = job.data.plan or {}
    phases: list[dict[str, Any]] = plan.get("phases", [])
    worktree = require_worktree(job)
    instructions = SPECIALIST_INSTRUCTIONS.get(as_role, INSTRUCTIONS)
    if review:
        instructions += REVIEW_FIX
    if truncated or continuation:
        instructions += IN_PARTS

    if ci_failure is not None:
        context = base_context(job, instructions=FIX_INSTRUCTIONS, jira=jira, standards=standards)
        context["ci_failure"] = ci_failure
        wanted = sorted({f for phase in phases for f in phase.get("files", [])})
    else:
        index = job.data.phase_index
        phase = phases[index] if index < len(phases) else {}
        context = base_context(job, instructions=instructions, jira=jira, standards=standards)
        context["current_phase"] = {"number": index + 1, "of": len(phases), **phase}
        # a UI phase builds the Designer's screens rather than inventing its own; only
        # this phase's screens are handed over, not the whole design
        screens = designer.for_phase(job, phase)
        if screens is not None:
            context["design"] = screens
        if job.data.last_build_output:
            context["build_failure"] = job.data.last_build_output
        if job.data.qa_diagnosis:
            context["qa_diagnosis"] = job.data.qa_diagnosis
        if review:
            context["standards_review"] = review
        wanted = editable_files(job, worktree)

    context["project"] = project_facts(profile)
    # its own build and tests run there too: it must not write what can never pass there
    context["where_it_runs"] = where_it_runs()
    # a CI fix touches the whole branch and keeps every phase whole; a phase sees its own
    context["plan"] = plan_outline(plan, None if ci_failure is not None else job.data.phase_index)
    if truncated:
        context["output_was_truncated"] = truncated
    if continuation:
        context["continuation"] = continuation
    context["tree"] = list_tree(worktree, first=wanted)
    cut = too_large(worktree, wanted)
    context["files"] = {
        **read_files(worktree, [n for n in wanted if n not in cut], max_bytes=EDITABLE_FILE_BYTES),
        **read_files(worktree, cut),
    }
    if cut:
        # said outright, not left to a "(truncated" marker at the end of a long file
        context["files_cut"] = cut
        context["instructions"] = f"{context['instructions']}{CUT_FILES}"
    if (continuation or {}).get("edit_failed"):
        context["instructions"] = f"{context['instructions']}{EDIT_FAILED}"

    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        as_role,
        profile,
        context,
        provider=provider,
        output_schema_cls=DeveloperResult,  # whoever implements a phase answers with changes
        **kwargs,
    )


__all__ = [
    "FIX_INSTRUCTIONS",
    "INSTRUCTIONS",
    "editable_files",
    "files_in_output",
    "run",
    "too_large",
]
