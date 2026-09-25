"""Designer: the screens, before anyone writes a screen.

It sits between the approved plan and the UI phases. The Product Owner's backlog says
what the product does; the Architect's plan says in what order it gets built; neither
says what a screen is *for*, what sits where, or which states it has. Without that the
Web and Mobile specialists each invent their own answer, and the two halves of the same
product stop looking like the same product.

So this role reads the approved backlog and plan, applies the project's design standards,
and writes one entry per screen: purpose, layout, the parts to build, the states, and what
each control does. The specialists then build against it rather than against a guess. It
writes no files — the design is a decision, not code.
"""

from __future__ import annotations

from typing import Any

from slipwright.invoke import RoleResult, invoke_role
from slipwright.providers import ModelProvider
from slipwright.roles.common import base_context, plan_outline
from slipwright.schemas.job import Job
from slipwright.schemas.profile import Profile, RoleName

INSTRUCTIONS = """\
Design the screens this development needs. `backlog` is what the Product Owner had
approved and `plan` is the order it gets built in; the screens you describe are the ones
the Web and Mobile specialists will implement from, so describe every screen a person
will actually see, and nothing that is not in the backlog.

One entry per screen. `purpose` is what a person comes there to do, in one sentence.
`layout` is the regions top to bottom, saying what dominates and what is secondary --
words, not pixels, and never a framework's component names. `components` are the parts
to build, in reading order. `states` must cover what really happens: empty, loading,
error, and any state this screen has of its own; a screen that lists something has an
empty state, a screen that saves has a failure state. `interactions` say what each
control does and where it leads. `platform` is `web`, `mobile` or `both` -- take it from
the phases in the plan, and where both build the same screen say `both` once rather than
describing it twice.

`principles` are the few decisions that hold across every screen: navigation, density,
spacing, tone of the words, how errors are shown. Keep them to what a specialist would
otherwise decide differently on each screen.

The screen as a picture, so the person approving the design sees it instead of reading
about it: a self-contained HTML document, a single `<style>` block and the markup, and
nothing else -- no `<script>`, no network request, no external font, stylesheet or image
(a placeholder is a coloured block or an inline SVG). Use the real words the screen will
show, not `lorem ipsum`, and draw the screen's ordinary state; the other states are
described in `states`. Keep each document under 20,000 characters.

Where it goes depends on the platform. A screen on one platform puts its document in
`mock` -- a mobile screen drawn in a phone-width frame, a web screen at a desktop width.
A screen whose platform is `both` is drawn twice instead, into `mocks`: `mocks.web` at a
desktop width and `mocks.mobile` in a phone-width frame, each a document of its own and
each showing the whole screen. Do not stack a browser and a phone inside one document:
the person approving looks at one surface at a time, and a drawing that has to share its
page with another is the smaller and the poorer for it. Leave `mock` empty when you fill
`mocks`.

If `redesign` is present, only the screens it names are being drawn again and the reason
each was sent back is with it. Answer with every screen as before -- the ones not named
exactly as they were, from `previous_design` -- and change only what the reason asks for.

Design only. You write no files and no code: the specialists do that from what you write
here. If the backlog leaves a screen genuinely undecided, say so in `notes` rather than
inventing a requirement.
If a `standards` section is present its sections are binding unless they contradict the
core rules; say in `summary` when one could not be followed and why."""


def run(
    job: Job,
    profile: Profile,
    *,
    provider: ModelProvider | None = None,
    timeout_s: float | None = None,
    jira: dict[str, Any] | None = None,
    standards: dict[str, Any] | None = None,
) -> RoleResult:
    context = base_context(
        job,
        instructions=INSTRUCTIONS,
        feedback=job.data.feedback,
        jira=jira,
        standards=standards,
    )
    context["backlog"] = (job.data.plan or {}).get("breakdown") or job.data.backlog
    context["plan"] = plan_outline(job.data.plan)
    context["ui_phases"] = ui_phases(job)
    if job.data.design:
        context["previous_design"] = job.data.design
    sent_back = rejected(job)
    if sent_back:
        context["redesign"] = sent_back
    kwargs = {} if timeout_s is None else {"timeout_s": timeout_s}
    return invoke_role(RoleName.DESIGNER, profile, context, provider=provider, **kwargs)


def ui_phases(job: Job) -> list[dict[str, Any]]:
    """The phases a screen could belong to. A plan with none of these needs no design, and
    the engine skips the step rather than asking for screens nobody will build."""
    phases = (job.data.plan or {}).get("phases", [])
    return [
        {
            "number": i + 1,
            "goal": p.get("goal"),
            "domain": p.get("domain"),
            "task_id": p.get("task_id"),
        }
        for i, p in enumerate(phases)
        if p.get("domain") in ("web", "mobile")
    ]


def rejected(job: Job) -> list[dict[str, Any]]:
    """The screens sent back, each with what the person asked for. Empty on a first run and
    on a plan whose screens have never been looked at."""
    feedback = job.data.design_feedback or {}
    screens = {s.get("id"): s for s in (job.data.design or {}).get("screens") or []}
    return [
        {"id": screen_id, "name": (screens.get(screen_id) or {}).get("name"), "asked_for": text}
        for screen_id, text in feedback.items()
        if text
    ]


def approved_ids(job: Job) -> set[str]:
    return {sid for sid, ok in (job.data.design_approvals or {}).items() if ok}


def pending_screens(job: Job) -> list[dict[str, Any]]:
    """The screens still waiting for a yes. A design with none of these is signed off."""
    done = approved_ids(job)
    return [s for s in (job.data.design or {}).get("screens") or [] if s.get("id") not in done]


def needed(job: Job) -> bool:
    """Whether this development has any screen at all: a backend-only change does not."""
    return bool(ui_phases(job))


def for_phase(job: Job, phase: dict[str, Any]) -> dict[str, Any] | None:
    """The part of the design a specialist needs for one phase: the screens of its own
    platform that belong to the phase's task, plus the principles that hold everywhere.
    A specialist is never handed the whole design -- the other platform's screens are
    noise it would have to read past."""
    design = job.data.design or {}
    screens = design.get("screens") or []
    domain = phase.get("domain")
    if domain not in ("web", "mobile"):
        return None  # "both" means web and mobile, not every phase there is
    task_id = phase.get("task_id")
    mine = [
        s
        for s in screens
        if s.get("platform") in (domain, "both")
        and (task_id is None or s.get("task_id") in (None, task_id))
    ]
    if not mine:
        return None
    return {"principles": design.get("principles") or [], "screens": mine}


__all__ = [
    "INSTRUCTIONS",
    "approved_ids",
    "for_phase",
    "needed",
    "pending_screens",
    "rejected",
    "run",
    "ui_phases",
]
