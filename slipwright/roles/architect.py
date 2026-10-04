"""Software Architect: from the approved backlog and the repository, decide how.

Produces three things in one go: the project profile (how it is built, tested and run),
architecture decisions worth writing down, and the ordered, domain-tagged phases — one
per backlog task — that the specialists will implement. Model routing (``roles``) always
comes from the seed profile; the Architect never chooses models (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from slipwright.gates import toolchains
from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, project_facts, require_worktree, scan_worktree
from slipwright.roles.results import ArchitectResult, PlanPhase, ReadmeResult
from slipwright.roles.specialists import Domain
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
You are the Software Architect. Read the repository (`worktree`) and the approved
`backlog`, then return:
1. `profile` — the project's language, package manager and the exact shell commands to
   build, test and run it. `run_cmd` must start the project listening on the literal
   placeholder `{port}`. Prefer the commands the repository's CI already runs. Keep the
   `roles` map exactly as given in `seed_profile`.
   `build_cmd` and `test_cmd` run on a bare checkout, as an ordinary user who cannot
   install system packages, with no device, emulator or simulator attached. Nothing is
   installed beforehand beyond git, curl, Python with uv, Node with npm, and whatever
   `toolchains` lists; use those as they are and never write a step that downloads an SDK
   or a JDK or calls a system package manager. An Android project builds with the
   installed `gradle` (not `./gradlew`, unless the repository already commits
   `gradle/wrapper/gradle-wrapper.jar`: that file is binary and cannot be written), on an
   Android Gradle Plugin version that runs on that Gradle, with a `compileSdk` among the
   listed platforms. A React Native or Expo app compiles native code: pin its
   `ndkVersion` (and the CMake version, where the project names one) to the ones
   `toolchains` lists, in the Android project's own Gradle files, rather than leaving
   the framework's default -- a default that is not installed stops every build. Flutter
   is not installed: a new mobile app is written in React Native unless the repository
   already holds a Flutter one. If what the project needs is not there, say so in
   `summary` rather than working around it. Write commands that can survive all that. In particular:
   install with the command that creates a lock
   file (`npm install`, not `npm ci`) unless the repository already has one committed,
   because a project being written for the first time does not; and leave out anything
   that needs a device (`connectedAndroidTest`, a simulator test run) or a service this
   checkout does not start itself. These commands are yours alone: no specialist can
   change them later, so a command that cannot run makes the development unfixable.
   A mobile app's own build goes in `profile.platforms`, one entry per platform (`ios`,
   `android`) with its `build_cmd` and `test_cmd`, never in the project's `build_cmd` and
   `test_cmd`: those must build and test everything else -- the backend, the web app, the
   code a React Native or Flutter app shares between platforms -- without Xcode or an
   Android SDK. iOS is built with `xcodebuild` (a simulator destination for the build, no
   test that needs a booted device), Android as described above. `can_build_here` lists
   the platforms this machine can build; the others are built on a Mac lent to it later,
   so write their commands for that Mac all the same.
2. `stack` — one entry for each part of the product this project needs (`backend`,
   `web`, `mobile`, `infra`), naming the language and the framework it is written in and
   one sentence of why. For a repository that already holds code, report what is there
   rather than what you would have chosen; propose something new only for a part that
   does not exist yet. Leave out a part the project does not have. The person reads this
   at the approval gate and may change it before anything is written.
3. `decisions` — the architecture decisions this work needs (components touched, data
   model changes, contracts between backend and front-ends, error handling, anything a
   reviewer must know). One sentence each; omit the obvious.
4. `phases` — ordered implementation phases. Every phase implements exactly one backlog
   task (`task_id`), names its `domain` (`backend`, `web`, `mobile`, `infra`, `docs`,
   `general`) so the right specialist gets it, and lists the files it will create or
   change. A phase is one model call: everything it lists has to be written in a single
   answer, so keep it to a handful of files. A phase that names dozens does not come back
   slowly, it does not come back at all -- and the attempt is charged for in full, twice,
   before the development stops. If a task is larger than that, say so in `summary` so the
   Product Owner can split it rather than writing one phase that cannot be answered.
   Backend contracts come before the front-ends that use them. A phase must not mix
   domains; if a task needs two domains, say so in `summary` so the Product Owner can
   split it. A `mobile` phase that writes one platform's native app names it in
   `platform` (`ios` or `android`) and is built with that platform's commands, so that
   platform must be in `profile.platforms`; mobile code both platforms share has no
   `platform`. A platform phase may wait until last for a machine that can build it, so
   nothing may depend on one: put platform phases after everything they use, and never
   make a later phase need what a platform phase wrote.
   A `web` or `mobile` phase says in `new_screens` whether a person will see a screen
   that is new or laid out differently (`true`), or whether it only wires, fixes or moves
   code behind screens that already exist (`false`). The Designer draws, and the person
   approves, only the screens of the phases that say `true`; leave it out on every other
   domain.
   Every phase must say what it needs in `depends_on` (a plan without it is refused): the
   numbers of the earlier phases it builds on. A phase needs another only when it changes
   a file the other writes, or calls code, a contract or a schema the other writes;
   reading a file for orientation is not a need, and neither is coming later in the
   story. `[]` when it needs none. Two phases that change the same file are never
   independent: the later one depends on the earlier. A phase never depends on a later
   one.
   Plan for phases that are built side by side: those that need none of each other are
   written at the same time, and that is where a development's hours go -- a plan where
   every phase needs the one before runs one at a time. So put each endpoint, screen,
   job or module in a file of its own; put what several phases share -- an API schema,
   the types, the data model -- in one early phase they all depend on, and let them
   depend on that phase alone; and leave the few lines that wire them together (routes,
   the app's entry point, navigation) to one late phase that depends on them, rather than
   having every phase edit the same file. Never add a dependency that is not real, and
   never leave out one that is.
   Every backlog task gets a phase, with no exception: a task that mixes domains or looks
   unnecessary still gets its phase (the closest fit you can write), and the concern goes
   in `summary`. A task too large for one answer may take several consecutive phases, each
   a part of it with the same `task_id`. A plan that leaves a task out is not reviewable
   and is thrown away.
   The project's `README.md` is yours, and you write it after the last phase is built:
   no phase lists it among its files, and no phase is a report. Findings, audits and
   checklists a task asks for go in their own files under `docs/`, never in the README.
5. `diagram` — the architecture as a Mermaid `flowchart TD` (top to bottom: it is shown
   in a narrow panel, where a long left-to-right chain shrinks to nothing): one
   node per part of the product (the app, its screens or modules, services, stores,
   external systems and devices), labelled in the project's language with what it is
   written in, and an arrow for each thing that talks to another, labelled with how
   (HTTP, Bluetooth, a queue, a file). Group a part's insides in a `subgraph`. Draw what
   this plan will build, not a generic picture; a dozen nodes is plenty. Give the source
   only, without a code fence. It is shown at the approval gate and in the README.
If `feedback` is present, a human rejected your previous plan (`previous_plan`); address
every point in it. If a `jira` section is present you may add Jira actions for existing
issues. If a `standards` section is present its sections are binding unless they
contradict the core rules."""


REPLAN = """
This is a re-plan from phase {start}: phases 1 to {kept} are built and committed, and stay
(`kept_phases`). Number `depends_on` by the place in the whole plan: your first phase is
phase {start}, and it may depend on kept ones. `feedback` says what failed and what to try
instead. Return in `phases` only the phases from {start} on -- they replace the old ones
from there -- and every task the kept phases do not implement still needs one. Never
repeat a kept phase. If the cause is in a kept phase's code, add a phase here that changes
it, and say so in `summary`."""


def run(
    job: Job,
    *,
    seed: Profile,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
    attachments: dict[str, Any] | None = None,
    problem: str | None = None,
) -> RoleResult:
    worktree = require_worktree(job)
    instructions = INSTRUCTIONS
    if problem:
        instructions += (
            "\nYour previous plan was rejected (`previous_answer_problem`); answer again "
            "with the whole plan and fix exactly that."
        )
    context = base_context(
        job, instructions=instructions, feedback=job.data.feedback, jira=jira, standards=standards
    )
    if attachments:
        # what the files said, as the reading summed them up: the backlog already
        # carries what is to be built from them, this is what it should look like
        context["attachments"] = attachments
    if problem:
        context["previous_answer_problem"] = problem
    context["seed_profile"] = seed.model_dump(mode="json")
    context["backlog"] = job.data.backlog
    context["domains"] = [d.value for d in Domain]
    context["previous_plan"] = job.data.plan
    kept = kept_phases(job)
    if job.data.replan_from is not None:
        context["kept_phases"] = kept
        context["instructions"] += REPLAN.format(start=len(kept) + 1, kept=len(kept))
    context["previous_profile"] = (
        None if job.profile is None else job.profile.model_dump(mode="json")
    )
    context["worktree"] = scan_worktree(worktree)
    # what the machine brings, so the commands use it instead of fetching their own
    context["toolchains"] = toolchains.installed()
    context["can_build_here"] = toolchains.buildable()
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.ARCHITECT, seed, context, provider=provider, **kwargs)


README_INSTRUCTIONS = """\
You are the Software Architect, and the development you planned is built. Write the
project's `README.md` -- the page a person sees first when they open the repository. It
describes the product as it now stands, for somebody who has never seen it: what it is,
what it looks like inside, and how to run it. It is not a report of this development, an
audit, a checklist or a log of what was verified; nothing about agents, phases, Jira keys
or what could not be confirmed belongs in it.

Read `worktree` (the tree and the manifests), `plan`, `project` and `existing_readme`, and
write, in this order:
1. A title and a one-line tagline, then a row of shields.io badges for the language, the
   framework(s) in `plan.stack` and the license if the tree has one
   (`![React Native](https://img.shields.io/badge/React_Native-0.74-61DAFB?logo=react)`).
2. A short paragraph on what the product does and for whom, then its features as a
   bulleted list, each with a fitting emoji -- taken from what the code does, never from
   what was only planned.
3. `## Architecture`: `plan.diagram` in a ```mermaid block (correct it if it no longer
   matches the tree, draw one if there is none), then a few sentences on how the parts
   fit together.
4. A tech stack table: the part, what it is written in, and why.
5. The project structure: the main folders as a short annotated tree, not every file.
   Leave out build output (`dist/`, `build/`) as if it were not there.
6. Getting started: prerequisites, then the exact commands to install, build, test and
   run from `project` (the run command's `{port}` filled with a real port), each in a
   fenced block. A mobile app says how to start it on a device or an emulator.
7. Anything a person must set themselves (environment variables, keys, permissions), and
   a link to `deployment/README.md` if the tree has it.
Headings are in the project's language like the rest of the prose. Use headings, tables
and fenced blocks so it reads well on GitHub, and keep to what is true of this
repository. If `existing_readme` holds something a person wrote that is still true -- a
license, credits, contact -- keep it."""


def write_readme(
    job: Job,
    profile: Profile,
    *,
    existing: str = "",
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    """The README, once every phase is built: the Architect knows what the parts are and
    why, and it is the one role that sees the whole of it. Left to the phases, the README
    became whatever the last docs task needed -- a project's front page that read as an
    audit of what could not be verified, with nothing about what the app is."""
    worktree = require_worktree(job)
    context = base_context(job, instructions=README_INSTRUCTIONS, standards=standards)
    plan = job.data.plan or {}
    context["plan"] = {
        "summary": plan.get("summary", ""),
        "stack": plan.get("stack", []),
        "decisions": plan.get("decisions", []),
        "diagram": plan.get("diagram", ""),
    }
    context["project"] = project_facts(profile)
    context["worktree"] = scan_worktree(worktree)
    context["existing_readme"] = existing
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(
        RoleName.ARCHITECT,
        profile,
        context,
        provider=provider,
        output_schema_cls=ReadmeResult,
        **kwargs,
    )


def accepted_profile(result: ArchitectResult, seed: Profile) -> Profile:
    """The profile the job will carry: the Architect's project facts, the seed's roles."""
    return result.profile.model_copy(update={"roles": seed.roles})


def kept_phases(job: Job) -> list[dict[str, Any]]:
    """The phases a re-plan keeps: built and committed before the one it starts from."""
    if job.data.replan_from is None:
        return []
    phases = (job.data.plan or {}).get("phases", [])
    return list(phases[: job.data.replan_from])


def dependency_problem(phases: Sequence[PlanPhase], built: int = 0) -> str | None:
    """Why the phases' `depends_on` cannot be built from, or None (T16.2).

    A phase depends only on earlier ones -- so the plan's own order is always one that
    respects them, and nothing can wait for itself. Two phases that change the same file
    must be ordered by a dependency: built side by side they would each write it, and
    one would lose. A phase with no `depends_on` at all (an older plan) needs every
    earlier phase, which is the order it always ran in.

    The first ``built`` phases are built and committed (a re-plan's kept ones): every
    later phase comes after them whatever it says, so sharing a file with one is no
    conflict -- the rule is about phases that could be written side by side."""
    needs: list[set[int]] = []
    for number, phase in enumerate(phases, start=1):
        if phase.depends_on is None or number <= built:
            direct = set(range(1, number))
        else:
            direct = set(phase.depends_on)
            ahead = sorted(d for d in direct if not 1 <= d < number)
            if ahead:
                return (
                    f"phase {number} depends on phase {ahead[0]}, which does not come before "
                    "it: a phase may depend only on earlier ones"
                )
        # everything it needs, through what those need -- and what is built already
        closure = set(direct) | set(range(1, min(built, number - 1) + 1))
        for d in direct:
            closure |= needs[d - 1]
        needs.append(closure)
    owner: dict[str, int] = {}
    for number, phase in enumerate(phases, start=1):
        for name in phase.files:
            key = name.strip().replace("\\", "/").removeprefix("./")
            first = owner.get(key)
            if first is not None and first not in needs[number - 1]:
                return (
                    f"phases {first} and {number} both change {name} but phase {number} does "
                    f"not depend on phase {first}"
                )
            owner[key] = number
    return None


def phase_task_map(phases: Sequence[PlanPhase], task_ids: list[str]) -> dict[str, int] | str:
    """Map task id -> 1-based phase number, or a readable reason the plan is invalid.

    A task may take several phases -- one too large for an answer is split into parts --
    and is mapped to its last: the board calls it done when every part is."""
    mapping: dict[str, int] = {}
    known = set(task_ids)
    for number, phase in enumerate(phases, start=1):
        if phase.task_id not in known:
            return f"phase {number} names unknown task {phase.task_id!r}"
        mapping[phase.task_id] = number
    missing = [t for t in task_ids if t not in mapping]
    if missing:
        return f"no phase implements task(s) {missing}"
    return mapping


__all__ = [
    "INSTRUCTIONS",
    "README_INSTRUCTIONS",
    "accepted_profile",
    "dependency_problem",
    "kept_phases",
    "phase_task_map",
    "run",
    "write_readme",
]
