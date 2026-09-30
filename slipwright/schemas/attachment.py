"""A file a person gave the agents, as everything but the file itself.

The bytes stay in the database and leave it only through the download endpoint; what
travels in lists, events and job context is this: what the file is, how far it has been
read, and what a model made of it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from slipwright.roles.results import ScreenSeen

Scope = Literal["project", "job", "draft"]
ReadingState = Literal["pending", "reading", "done", "failed"]


class Reading(BaseModel):
    """What a model made of the file. Written once, when it was read; agents after that
    read this rather than the file."""

    kind: Literal["screens", "document", "other"] = "other"
    summary: str = ""
    screens: list[ScreenSeen] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    # why there is no reading, or why it was made without looking at the pictures: the
    # model could not see them, there was no model to ask. Shown beside the file.
    note: str = ""
    # what reading it cost, one entry per call, in the shape of a job's invocation log --
    # a reading belongs to no job, and the project's costs add these to its developments'
    calls: list[dict[str, Any]] = Field(default_factory=list)


class Attachment(BaseModel):
    id: str
    project_id: str
    job_id: str | None = None
    scope: Scope
    name: str
    media_type: str
    size: int
    pages: int = Field(default=0, description="Pages of a PDF; 0 for anything else.")
    text_chars: int = Field(default=0, description="How much text could be taken out of it.")
    reading_state: ReadingState = "pending"
    reading: Reading | None = None
    created_at: datetime

    @property
    def is_picture(self) -> bool:
        return self.media_type.startswith("image/")


__all__ = ["Attachment", "Reading", "ReadingState", "Scope"]
