"""A machine an account lends its developments, and what it is asked for: a build (T14.3)
or a model call made on its own plan (T17.1). docs/machines-protocol.md is the contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Where a machine says it runs, when it can tell (docs/machines-protocol.md §1): the
#: three clouds that lend machines by the hour, and Amazon's Macs, which are told apart
#: because they are the ones that build iOS. Anything else is shown as nothing.
HOSTS = ("aws-ec2", "ec2-mac", "azure-vm", "gcp")


class MachineAbout(BaseModel):
    """What a machine says it is: drawn on its card while it writes a development, so a
    person can tell the EC2 box from the laptop. Only shown, never trusted -- nothing is
    routed on it, which is what capabilities are for."""

    # ignored, not refused: an app newer than this server may say more about itself
    model_config = ConfigDict(extra="ignore")

    os: str | None = Field(default=None, max_length=60, description="Ubuntu 24.04, macOS 15")
    host: str | None = Field(default=None, description="One of HOSTS; anything else is none.")
    size: str | None = Field(
        default=None, max_length=40, description="The cloud's name for it: c7i.xlarge."
    )
    writers: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="What writes on it: each tool and its model, as the machine names them.",
    )

    @field_validator("host")
    @classmethod
    def _known_host(cls, value: str | None) -> str | None:
        return value if value in HOSTS else None

    @field_validator("writers")
    @classmethod
    def _short(cls, value: list[str]) -> list[str]:
        return [w.strip()[:60] for w in value if w.strip()]


class Worker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner_id: str | None = Field(description="The account it builds for; none on a local install.")
    name: str
    capabilities: list[str] = Field(
        default_factory=list,
        description="What it said at its last poll it can do: platforms it builds "
        "(ios, android) and domains it writes (write:backend, ...).",
    )
    paired_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    online: bool = Field(default=False, description="Seen recently enough to be given work.")
    lent_by: str | None = Field(
        default=None, description="The person on the account who lent it; none is the owner."
    )
    lent_by_name: str | None = None
    writing: bool = Field(default=False, description="It is writing a phase right now.")
    doing_phase: int | None = Field(default=None, description="The phase it is writing.")
    doing: str | None = Field(
        default=None, description="What it last said it was doing, in its own words."
    )
    about: MachineAbout | None = Field(
        default=None, description="What it said it is; none from a machine that never said."
    )


class WorkerTask(BaseModel):
    """A build as the worker is given it: which commands, for how long. The worktree
    itself is fetched separately, being the one part that can be large."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["build"] = "build"
    id: str
    job_id: str
    platform: str
    commands: list[tuple[str, str]] = Field(description="(label, command), run in order.")
    timeout_s: float


class CallImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: str
    data: str = Field(description="base64")
    label: str = ""


class CallRepo(BaseModel):
    """Where the code the call was written from is. Never credentials: a machine reads it
    with its own, or not at all."""

    model_config = ConfigDict(extra="forbid")

    url: str
    branch: str | None = None
    commit: str | None = None


class WorkerCall(BaseModel):
    """One model call as a machine is given it: the request the server would have sent its
    own provider, and what the call is for, so the machine can say so."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["write"] = "write"
    id: str
    job_id: str
    project: str | None = None
    phase: int | None = None
    phases: int | None = None
    goal: str | None = None
    role: str
    domain: str
    jira_key: str | None = None
    system: str
    prompt: str
    output_schema: dict[str, Any]
    images: list[CallImage] = Field(default_factory=list)
    thinking_depth: str
    timeout_s: float
    repo: CallRepo | None = None


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exit_code: int
    output: str = Field(max_length=2_000_000)
    seconds: float = Field(ge=0)


class CallProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=500)


class CallAnswer(BaseModel):
    """The model's text exactly as it came: the server parses it as it would its own."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=4_000_000)
    model: str | None = Field(default=None, max_length=200)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    seconds: float = Field(default=0, ge=0)


class CallFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(max_length=4000)
    kind: Literal["rejected", "error", "timeout"] = "error"


__all__ = [
    "CallAnswer",
    "CallFailure",
    "CallImage",
    "CallProgress",
    "CallRepo",
    "HOSTS",
    "MachineAbout",
    "TaskResult",
    "Worker",
    "WorkerCall",
    "WorkerTask",
]
