"""Project brief: what the agents know about the project before any work starts.

A development tells an agent *what to do*; the brief tells it *what it is working on* —
the stack, the shape of the code, the conventions the repository already follows, where
it is deployed. It is written once per project: by the Architect reading an existing
checkout (the analysis), or by the Product Owner asking the person questions when the
repository is empty (the intake). Either way a person edits and approves the items
before any agent reads them.

The brief lives in Slipwright's own database, never in the user's repository, and is
handed to every role as one context section. Items are small and separately editable on
purpose: a wrong line is deleted or corrected without redoing the analysis.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.job import new_job_id, utcnow


class BriefState(StrEnum):
    EMPTY = "empty"  # nothing has been written yet
    RUNNING = "running"  # the analysis (or an intake round) is working
    PROPOSED = "proposed"  # items are waiting for the person to approve them
    READY = "ready"  # approved: the agents read it
    FAILED = "failed"  # the last attempt failed; ``error`` says why


# The categories an item can fall under. Fixed so the UI can group them and the model
# cannot invent a taxonomy of its own.
Category = Literal[
    "product",  # what the project is for, who uses it
    "stack",  # languages, frameworks, package managers, services
    "architecture",  # how the pieces fit together
    "modules",  # the parts of the code and what each is responsible for
    "conventions",  # how this repository writes things
    "testing",  # how it is tested and run
    "deployment",  # where it runs and how it gets there
    "risks",  # what an agent should be careful with
]
CATEGORIES: tuple[str, ...] = (
    "product",
    "stack",
    "architecture",
    "modules",
    "conventions",
    "testing",
    "deployment",
    "risks",
)

Source = Literal["analysis", "intake", "human"]


class BriefItem(BaseModel):
    """One fact about the project. Short enough to judge at a glance and delete if wrong."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    category: Category = "architecture"
    title: str = Field(min_length=1)
    detail: str = ""
    source: Source = "analysis"


class IntakeQuestion(BaseModel):
    """One question the Product Owner asked, and the person's answer to it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=new_job_id, min_length=1)
    question: str = Field(min_length=1)
    why: str = Field(default="", description="Why the answer matters, for the person.")
    hint: str = Field(default="", description="An example answer, shown as a placeholder.")
    answer: str = ""


class IntakeRound(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)
    questions: list[IntakeQuestion] = Field(default_factory=list)
    at: datetime = Field(default_factory=utcnow)


class Intake(BaseModel):
    """The conversation that turns an empty repository into a first development.

    The Product Owner asks a round of questions, reads the answers, and either asks
    another round or declares itself ready and writes ``story`` — the request the first
    development starts from.
    """

    model_config = ConfigDict(extra="forbid")

    rounds: list[IntakeRound] = Field(default_factory=list)
    done: bool = False
    story: str = Field(default="", description="The first development's request, once ready.")
    max_rounds: int = Field(default=3, ge=1, description="Rounds before the PO must finish.")

    @property
    def current(self) -> IntakeRound | None:
        return self.rounds[-1] if self.rounds else None

    @property
    def answered(self) -> bool:
        round_ = self.current
        return round_ is not None and all(q.answer.strip() for q in round_.questions)


class ProjectBrief(BaseModel):
    """Everything Slipwright knows about a project, and how it came to know it."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    state: BriefState = BriefState.EMPTY
    items: list[BriefItem] = Field(default_factory=list)
    summary: str = Field(default="", description="The analysis write-up, in one paragraph.")
    error: str = Field(default="", description="Why the last analysis or intake failed.")
    intake: Intake | None = Field(
        default=None, description="Set for an empty repository: the questions and answers."
    )
    updated_at: datetime = Field(default_factory=utcnow)
    approved_at: datetime | None = None

    @property
    def ready(self) -> bool:
        return self.state is BriefState.READY and bool(self.items)

    def context(self) -> list[dict[str, str]]:
        """The brief as the agents receive it: category, title, detail — nothing else."""
        return [
            {"category": i.category, "title": i.title, "detail": i.detail}
            for i in self.items
            if i.title.strip()
        ]


class BriefEdit(BaseModel):
    """What a person may change: the items themselves, nothing about how they were found."""

    model_config = ConfigDict(extra="forbid")

    items: list[BriefItem]
    approve: bool = Field(
        default=True, description="Mark the brief ready for the agents (the usual case)."
    )


__all__ = [
    "CATEGORIES",
    "BriefEdit",
    "BriefItem",
    "BriefState",
    "Category",
    "Intake",
    "IntakeQuestion",
    "IntakeRound",
    "ProjectBrief",
    "Source",
]
