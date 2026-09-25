"""Specialist developer roles: backend, web UI, mobile UI.

The Architect tags every phase with a ``domain``; the engine hands the phase to the
specialist for that domain. All specialists share the Developer's contract (one phase per
invocation, full file contents back) and differ only in scope and hand-off rules, which
live here as instructions. ``developer`` stays the generic fallback.
"""

from __future__ import annotations

from enum import StrEnum

from slipwright.schemas.profile import RoleName


class Domain(StrEnum):
    BACKEND = "backend"
    WEB = "web"
    MOBILE = "mobile"
    INFRA = "infra"
    DOCS = "docs"
    GENERAL = "general"


# domain -> the role that implements phases of that domain
SPECIALIST_FOR: dict[Domain, RoleName] = {
    Domain.BACKEND: RoleName.BACKEND,
    Domain.WEB: RoleName.WEB_UI,
    Domain.MOBILE: RoleName.MOBILE_UI,
    Domain.INFRA: RoleName.DEVOPS,
    Domain.DOCS: RoleName.BACKEND,  # no specialist of its own: the backend agent writes it
    Domain.GENERAL: RoleName.BACKEND,
}

# roles that implement phases (share DeveloperResult and the developer prompt shape)
DEVELOPER_ROLES: frozenset[RoleName] = frozenset(
    {RoleName.BACKEND, RoleName.WEB_UI, RoleName.MOBILE_UI}
)

# the standards domain each role reads (T9.4); "*" means a little of everything
STANDARDS_DOMAIN: dict[RoleName, str] = {
    RoleName.PO: "product",
    RoleName.ARCHITECT: "architecture",
    RoleName.BACKEND: "backend",
    RoleName.DESIGNER: "design",
    RoleName.WEB_UI: "web",
    RoleName.MOBILE_UI: "mobile",
    RoleName.QA: "testing",
    RoleName.DEVOPS: "devops",
    RoleName.SUPERVISOR: "*",
}

# friendly names for the UI and history notes
LABEL: dict[RoleName, str] = {
    RoleName.PO: "Product Owner",
    RoleName.ARCHITECT: "Architect",
    RoleName.BACKEND: "Backend Developer",
    RoleName.DESIGNER: "Designer",
    RoleName.WEB_UI: "Web Developer",
    RoleName.MOBILE_UI: "Mobile Developer",
    RoleName.QA: "QA",
    RoleName.DEVOPS: "DevOps",
    RoleName.SUPERVISOR: "Supervisor",
}

SCOPE: dict[RoleName, str] = {
    RoleName.PO: "Turns a request into epics, stories and tasks — the backlog that goes to Jira.",
    RoleName.ARCHITECT: "From backlog and repository: build/test/run profile, decisions, phases.",
    RoleName.BACKEND: "Services, APIs, data models, migrations, background jobs.",
    RoleName.DESIGNER: "Designs the screens the two UI specialists build: purpose, "
    "layout, states, interactions.",
    RoleName.WEB_UI: "Web front-end: pages, components, state, styling, accessibility.",
    RoleName.MOBILE_UI: "Mobile apps: screens, navigation, platform APIs, offline state.",
    RoleName.QA: "Proposes test cases; writes unit, integration and end-to-end tests.",
    RoleName.DEVOPS: "Infrastructure phases, pull requests, CI, deployment.",
    RoleName.SUPERVISOR: "Reads what waits at a gate and recommends approve or reject.",
}

_SHARED = """\
Implement the plan phase named in `current_phase` and nothing beyond it. Return the
complete new contents of every file you create or change (`content: null` deletes a
file); paths are relative to the project root. Keep changes minimal and consistent with
the existing code. Set `phase_complete` to true when the phase's goal is met.
If `build_failure` is present, the build or tests failed after your previous attempt on
this phase: read the output, fix the cause, and return the corrected files.
If a `jira` section is present, transition `current_task_key` to in progress and add a
short comment (and `log_work` with a realistic estimate) describing what you changed.
If a `standards` section is present its sections are binding unless they contradict the
core rules; say in `summary` when one could not be followed and why."""

INSTRUCTIONS: dict[RoleName, str] = {
    RoleName.BACKEND: _SHARED
    + """
You are the BACKEND specialist: services, HTTP/RPC APIs, data models and migrations,
background jobs, integrations. Stay out of front-end code. If the phase needs a UI change
or a mobile change, do not do it: finish the backend part, describe the missing piece in
`summary` so the Architect can add a phase for the right specialist.""",
    RoleName.WEB_UI: _SHARED
    + """
You are the WEB UI specialist: pages, components, client state, styling, accessibility,
front-end tests. Do not add or change server endpoints. If the phase needs an endpoint that
does not exist, build against the contract described in the plan, keep the call isolated
in one client module, and say in `summary` exactly which endpoint is missing so the Architect
can add a backend phase.
If a `design` section is present it is the approved design for this phase's screens: build
those screens, with the states and interactions it names, and follow its `principles`. It
says what the screen is and does, never how to write it -- the code is yours. Where it is
silent, decide and say so in `summary`; where you cannot build what it asks, say why.""",
    RoleName.DEVOPS: _SHARED
    + """
You are the DEVOPS specialist for this phase: Dockerfiles, compose files, CI workflows,
deployment and environment configuration, README setup steps. Do not change application
code beyond what packaging needs (an entrypoint, a health endpoint wiring); never commit
secrets — use environment variables and an example env file. Say in `summary` what a
person must do by hand (create a secret, open a port).""",
    RoleName.MOBILE_UI: _SHARED
    + """
You are the MOBILE UI specialist: screens, navigation, platform APIs, offline and sync
state, mobile tests. Do not change server code. Prefer platform conventions over web
patterns. Say in `summary` which backend contracts you relied on and which are missing.
If a `design` section is present it is the approved design for this phase's screens: build
those screens, with the states and interactions it names, and follow its `principles`. It
says what the screen is and does, never how to write it -- the code is yours. Where it is
silent, decide and say so in `summary`; where you cannot build what it asks, say why.""",
}


def specialist_for(domain: str | None) -> RoleName:
    try:
        return SPECIALIST_FOR[Domain(domain or Domain.GENERAL)]
    except ValueError:
        return RoleName.BACKEND


__all__ = [
    "DEVELOPER_ROLES",
    "INSTRUCTIONS",
    "LABEL",
    "SCOPE",
    "SPECIALIST_FOR",
    "STANDARDS_DOMAIN",
    "Domain",
    "specialist_for",
]
