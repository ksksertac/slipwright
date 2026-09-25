"""Per-role structured result schemas.

Every role invocation must produce output that validates against the schema registered
for that role here. The invoke layer uses ``RESULT_SCHEMAS`` both to constrain the model's
output format and to validate what comes back. Later phases refine these models; the
registry and the "one schema per role" rule are the contract.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from slipwright.schemas.brief import Category as BriefCategory
from slipwright.schemas.job import Job, new_job_id
from slipwright.schemas.profile import Profile, RoleName


class JiraActionType(StrEnum):
    CREATE_ISSUE = "create_issue"
    TRANSITION = "transition"
    COMMENT = "comment"
    LOG_WORK = "log_work"
    LINK_ISSUES = "link_issues"


class JiraAction(BaseModel):
    """One thing an agent wants done in Jira. Fields depend on ``action``."""

    model_config = ConfigDict(extra="forbid")

    action: JiraActionType
    issue: str | None = Field(
        default=None, description="Issue key for transition/comment/log_work."
    )
    issue_type: str | None = Field(
        default=None, description="create_issue: Task, Bug, Subtask, ..."
    )
    summary: str | None = Field(default=None, description="create_issue: title.")
    description: str | None = Field(default=None, description="create_issue: body.")
    parent: str | None = Field(default=None, description="create_issue: parent issue key.")
    to: str | None = Field(default=None, description="transition: target transition/status name.")
    body: str | None = Field(default=None, description="comment: text.")
    minutes: int | None = Field(default=None, ge=1, description="log_work: time spent.")
    note: str | None = Field(default=None, description="log_work: what was done.")
    target: str | None = Field(default=None, description="link_issues: the other issue key.")
    link_type: str = Field(default="Relates", description="link_issues: Relates, Blocks, ...")

    @model_validator(mode="after")
    def _required_fields(self) -> JiraAction:
        need = {
            JiraActionType.CREATE_ISSUE: ("issue_type", "summary"),
            JiraActionType.TRANSITION: ("issue", "to"),
            JiraActionType.COMMENT: ("issue", "body"),
            JiraActionType.LOG_WORK: ("issue", "minutes"),
            JiraActionType.LINK_ISSUES: ("issue", "target"),
        }[self.action]
        missing = [f for f in need if getattr(self, f) in (None, "")]
        if missing:
            raise ValueError(f"{self.action.value} needs {', '.join(missing)}")
        return self

    def idempotency_key(self, role: RoleName, job: Job) -> str:
        payload = json.dumps(
            {
                "role": role.value,
                "phase": job.data.phase_index,
                "qa_stage": job.data.qa_stage,
                "ci": job.data.ci_attempts,
                "attempt": job.data.build_attempts,
                **self.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class RoleOutput(BaseModel):
    """Base for all role outputs. ``extra="forbid"`` keeps the JSON Schema closed."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, description="One-paragraph account of what was done.")
    jira_actions: list[JiraAction] = Field(
        default_factory=list,
        description="Jira actions to perform on the role's behalf (needs the jira permission).",
    )


class PlanPhase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list, description="Files expected to change.")
    task_id: str | None = Field(
        default=None, description="The backlog task this phase implements (one phase per task)."
    )
    domain: Literal["backend", "web", "mobile", "infra", "docs", "general"] = Field(
        default="general",
        description="Which specialist implements the phase: backend, web, mobile, infra "
        "(DevOps), docs or general (the generic developer).",
    )


class StackChoice(BaseModel):
    """What one part of the product is written in (T11.5).

    The Architect proposes one entry per part it will build — the backend, the web
    front-end, the mobile app, the infrastructure — and the person can change any of it
    at the architecture gate before a specialist writes a line.
    """

    model_config = ConfigDict(extra="forbid")

    domain: Literal["backend", "web", "mobile", "infra"]
    language: str = Field(min_length=1, description="TypeScript, Python, Kotlin, ...")
    framework: str = Field(default="", description="React 19 + Vite, FastAPI, Flutter, ...")
    why: str = Field(default="", description="One sentence: why this, here.")


class BreakdownTask(BaseModel):
    """One unit of work; maps onto exactly one plan phase."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    phase: int | None = Field(
        default=None, ge=1, description="1-based plan phase; set by the Architect's plan."
    )


class BreakdownStory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    tasks: list[BreakdownTask] = Field(min_length=1)


class BreakdownEpic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    stories: list[BreakdownStory] = Field(min_length=1)


class Breakdown(BaseModel):
    """Epics -> stories -> tasks. Every plan phase is exactly one task."""

    model_config = ConfigDict(extra="forbid")

    epics: list[BreakdownEpic] = Field(min_length=1)

    def tasks(self) -> list[BreakdownTask]:
        return [t for e in self.epics for s in e.stories for t in s.tasks]


class POResult(RoleOutput):
    """The Product Owner's backlog. Task ids are generated when the model omits them."""

    breakdown: Breakdown

    @model_validator(mode="after")
    def _unique_ids(self) -> POResult:
        ids = [t.id for t in self.breakdown.tasks()]
        if len(set(ids)) != len(ids):
            raise ValueError("task ids must be unique")
        return self


class ArchitectResult(RoleOutput):
    """The Architect's answer: how the project is built, what was decided, and the
    phases (one per backlog task; the engine checks the mapping against the backlog)."""

    profile: Profile = Field(description="Build/test/run facts; roles come from the seed.")
    stack: list[StackChoice] = Field(
        default_factory=list,
        description="One entry per part of the product: which language and framework.",
    )
    decisions: list[str] = Field(default_factory=list)
    phases: list[PlanPhase] = Field(min_length=1)

    @model_validator(mode="after")
    def _phases_name_tasks(self) -> ArchitectResult:
        seen: set[str] = set()
        for i, phase in enumerate(self.phases, start=1):
            if not phase.task_id:
                raise ValueError(f"phase {i} has no task_id")
            if phase.task_id in seen:
                raise ValueError(f"task {phase.task_id!r} has more than one phase")
            seen.add(phase.task_id)
        return self


MOCK_MAX = 24_000


#: One drawing, under the same cap as ``mock``, and the surface it was drawn for.
MockDocument = Annotated[str, StringConstraints(max_length=MOCK_MAX)]
Surface = Literal["web", "mobile"]


class ScreenDesign(BaseModel):
    """One screen, described so a UI specialist can build it without inventing the shape.

    Words and lists first: the developers write Compose, React or SwiftUI, and most of what
    they are missing is decisions — what the screen is for, what sits where, which states
    exist and what each control does. The mock is the picture beside them, so the person
    approving the design sees the screen rather than reading a description of it, and the
    specialist builds against both.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    task_id: str | None = Field(
        default=None, description="The backlog task this screen belongs to, when it has one."
    )
    name: str = Field(min_length=1, description="What this screen is called, in the UI.")
    platform: Literal["web", "mobile", "both"] = "both"
    purpose: str = Field(min_length=1, description="What a person comes here to do.")
    layout: str = Field(
        min_length=1,
        description="The regions top to bottom, what dominates, what is secondary.",
    )
    components: list[str] = Field(
        default_factory=list, description="The named parts to build, in reading order."
    )
    states: list[str] = Field(
        default_factory=list,
        description="Empty, loading, error, success and anything else this screen has.",
    )
    interactions: list[str] = Field(
        default_factory=list, description="What each control does, and where it leads."
    )
    notes: str = Field(default="", description="Anything the specialist would otherwise guess.")
    mock: str = Field(
        default="",
        max_length=MOCK_MAX,
        description=(
            "A self-contained HTML document showing this screen: one <style> block and "
            "markup, no scripts, no network requests, no external fonts or images. "
            "For a screen drawn on one platform; a screen on both uses `mocks`."
        ),
    )
    mocks: dict[Surface, MockDocument] = Field(
        default_factory=dict,
        description=(
            "One document per surface, for a screen whose platform is `both`: `web` "
            "drawn at desktop width and `mobile` in a phone-width frame. Each is a "
            "document of its own, under the same rules as `mock`, so the person "
            "approving looks at one surface at a time instead of both stacked."
        ),
    )

    @model_validator(mode="after")
    def _mock_is_a_document(self) -> ScreenDesign:
        """A mock that is a fragment, a code fence or a picture of JSON is not a screen.

        The model is asked for a document; when it answers with something else the screen
        keeps its words and loses only its picture, rather than the panel rendering a page
        of stray markup. The same goes for each surface of a screen drawn on both.
        """
        mock = self.mock.strip()
        if mock and "<" not in mock:
            object.__setattr__(self, "mock", "")
        drawn = {k: v for k, v in self.mocks.items() if v.strip() and "<" in v}
        if drawn != self.mocks:
            object.__setattr__(self, "mocks", drawn)
        return self


class DesignResult(RoleOutput):
    """The Designer's answer: the screens the UI specialists implement, plus the handful
    of decisions that must hold across all of them."""

    principles: list[str] = Field(
        default_factory=list,
        description="What holds across every screen: spacing, tone, navigation, density.",
    )
    screens: list[ScreenDesign] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_screen_names(self) -> DesignResult:
        names = [s.name.strip().lower() for s in self.screens]
        if len(set(names)) != len(names):
            raise ValueError("screen names must be unique")
        return self


class FileChange(BaseModel):
    """Full new contents of one file; ``content: null`` deletes it."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, description="Path relative to the worktree root.")
    content: str | None = Field(description="Complete file contents, or null to delete.")


class DeveloperResult(RoleOutput):
    changes: list[FileChange] = Field(default_factory=list)
    phase_complete: bool = Field(
        default=True,
        description="Whether the assigned plan phase is finished; omitted means yes.",
    )


class TestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class Violation(BaseModel):
    """One breach of a standards section found in a phase diff (T9.5)."""

    model_config = ConfigDict(extra="forbid")

    section: str = Field(min_length=1, description="Heading of the section breached.")
    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    severity: Literal["blocking", "advisory"] = "advisory"
    message: str = Field(min_length=1)
    fix: str = Field(default="", description="How to bring the change in line.")


class QAResult(RoleOutput):
    test_cases: list[TestCase] = Field(
        default_factory=list, description="Stage one: proposed test cases."
    )
    changes: list[FileChange] = Field(
        default_factory=list, description="Stage two: test files to write."
    )
    violations: list[Violation] = Field(
        default_factory=list, description="Standards review: breaches found in the diff."
    )
    gate_verdict: Literal["", "test_is_wrong", "code_is_wrong"] = Field(
        default="",
        description="Gate triage: which side of a failed build gate was wrong. "
        "``test_is_wrong`` comes with the corrected test files in ``changes``.",
    )


class BriefDraft(BaseModel):
    """One line of the project brief as an agent proposes it; ids are added on save."""

    model_config = ConfigDict(extra="forbid")

    category: BriefCategory = "architecture"
    title: str = Field(min_length=1, description="The fact itself, in one line.")
    detail: str = Field(default="", description="One or two sentences of substance, or empty.")


class AnalysisResult(RoleOutput):
    """The Architect's reading of an existing checkout (T11.2): what this project is."""

    items: list[BriefDraft] = Field(min_length=1)


class IntakeQuestionDraft(BaseModel):
    """One question to put to the person who is starting an empty project."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    why: str = Field(default="", description="Why the answer changes what gets built.")
    hint: str = Field(default="", description="An example answer, shown as a placeholder.")


class IntakeResult(RoleOutput):
    """The Product Owner interviewing the person (T11.3): either the next round of
    questions, or ``ready`` with the story the first development starts from."""

    questions: list[IntakeQuestionDraft] = Field(default_factory=list)
    ready: bool = Field(
        default=False, description="True when the answers are enough to start building."
    )
    story: str = Field(default="", description="Ready: the first development's request.")
    items: list[BriefDraft] = Field(
        default_factory=list, description="Ready: the project brief drawn from the answers."
    )

    @model_validator(mode="after")
    def _answer_or_ask(self) -> IntakeResult:
        if self.ready:
            if not self.story.strip():
                raise ValueError("ready needs a story")
            if not self.items:
                raise ValueError("ready needs the brief items drawn from the answers")
        elif not self.questions:
            raise ValueError("ask at least one question, or set ready with a story")
        return self


class DeployScript(BaseModel):
    """One file the deployment folder will hold, named before it is written (T11.6)."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, description="Path under the project's deployment folder.")
    purpose: str = Field(min_length=1, description="What it does, in one line.")


class DeployPlan(RoleOutput):
    """DevOps proposing how this project gets deployed, for a person to approve."""

    target: Literal["aws", "azure", "none"] = Field(
        description="Where it is deployed; none when the architecture does not warrant it."
    )
    services: list[str] = Field(
        default_factory=list, description="The target's services this uses (ECS, App Service, ...)."
    )
    scripts: list[DeployScript] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list, description="What the person must supply: accounts, secrets, DNS."
    )

    @model_validator(mode="after")
    def _scripts_unless_none(self) -> DeployPlan:
        if self.target != "none" and not self.scripts:
            raise ValueError("name the scripts you will write, or answer with target 'none'")
        return self


class DevOpsResult(RoleOutput):
    pr_title: str = Field(min_length=1)
    pr_body: str = Field(min_length=1)


class SupervisorResult(RoleOutput):
    """Recommendation at a human gate (T9.8), or the choice on a failed build gate
    (T9.7): ``fix`` (the same specialist tries again), ``replan`` (the architect
    re-plans) or ``ask_human`` (the job waits at the decision gate)."""

    decision: Literal["approve", "reject", "fix", "replan", "ask_human"]
    confidence: float = Field(ge=0.0, le=1.0)
    risk: Literal["low", "medium", "high"]
    reasons: list[str] = Field(default_factory=list)
    feedback: str = Field(default="", description="What to change, when rejecting.")


RESULT_SCHEMAS: dict[RoleName, type[RoleOutput]] = {
    RoleName.PO: POResult,
    RoleName.ARCHITECT: ArchitectResult,
    RoleName.BACKEND: DeveloperResult,
    RoleName.WEB_UI: DeveloperResult,
    RoleName.MOBILE_UI: DeveloperResult,
    RoleName.DESIGNER: DesignResult,
    RoleName.QA: QAResult,
    RoleName.DEVOPS: DevOpsResult,
    RoleName.SUPERVISOR: SupervisorResult,
}


def result_schema_for(role: RoleName) -> type[RoleOutput]:
    return RESULT_SCHEMAS[role]


__all__ = [
    "RESULT_SCHEMAS",
    "AnalysisResult",
    "ArchitectResult",
    "BriefDraft",
    "DeployPlan",
    "DeployScript",
    "IntakeQuestionDraft",
    "IntakeResult",
    "Breakdown",
    "BreakdownEpic",
    "BreakdownStory",
    "BreakdownTask",
    "POResult",
    "DesignResult",
    "DevOpsResult",
    "DeveloperResult",
    "FileChange",
    "JiraAction",
    "JiraActionType",
    "PlanPhase",
    "QAResult",
    "ScreenDesign",
    "RoleOutput",
    "StackChoice",
    "SupervisorResult",
    "TestCase",
    "result_schema_for",
]
