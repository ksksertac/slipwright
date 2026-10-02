"""Moving an account to another Slipwright: what the page is told and what it sends."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

StepKey = Literal[
    "pair", "projects", "jobs", "settings", "attachments", "standards", "repos", "finish", "delete"
]


class TransferPeer(BaseModel):
    """A Slipwright on this network, as it describes itself."""

    model_config = ConfigDict(extra="forbid")

    address: str = Field(description="Where it answers, as this server reached it.")
    instance: str = Field(description="Which installation: the same one seen twice is one.")
    name: str
    version: str = Field(description="Empty for a release from before moving existed.")
    revision: str | None = Field(description="Its database schema; a transfer needs the same.")
    compatible: bool = Field(description="On the same schema as this one, so a transfer works.")
    database: str | None = Field(default=None, description="sqlite or postgresql.")
    projects: int | None = Field(default=None, description="How many projects it holds.")
    os: str | None = Field(default=None, description="macos, windows or linux: how it is drawn.")
    this_one: bool = Field(
        default=False, description="This installation, found at an address of its own."
    )
    legacy: bool = Field(
        default=False, description="A Slipwright from before moving existed: update it first."
    )


class TransferHere(BaseModel):
    """This installation, for its own card."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(description="Off on a hosted installation (SLIPWRIGHT_TRANSFER).")
    instance: str
    name: str
    version: str
    revision: str | None
    addresses: list[str] = Field(
        description="Where another machine may reach this one, to type in when it is not "
        "found by looking."
    )
    projects: int = Field(description="This account's projects: what a transfer would send.")
    admin: bool = Field(description="Whether the installation's own settings go too.")
    database: str = Field(description="sqlite or postgresql.")
    networks: list[str] = Field(description="What looking around the network looks at.")
    os: str = Field(description="macos, windows or linux: how its card is drawn.")


class TransferHello(BaseModel):
    """What any installation says about itself to anybody on its network."""

    model_config = ConfigDict(extra="forbid")

    app: Literal["slipwright"] = "slipwright"
    instance: str
    name: str
    version: str
    revision: str | None
    database: str
    projects: int = Field(description="How many projects it holds, the worked example aside.")
    os: str = Field(description="macos, windows or linux.")
    protocol: int = Field(description="What a transfer to it must speak.")


class TransferCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    shown_s: int = Field(description="Seconds until the next one; the old one works a while on.")


class TransferSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(
        min_length=4, max_length=300, description="The receiver, http://host:port."
    )
    code: str = Field(min_length=10, max_length=40)
    delete_after: bool = Field(
        default=False, description="Delete the projects here once the receiver has them all."
    )
    projects: list[str] | None = Field(
        default=None, description="Which projects; none given is every one of them."
    )
    checkouts: bool = Field(
        default=True,
        description="Send each checkout whole -- branches and work not committed. Without, "
        "the receiver clones from the remote and only what was pushed arrives.",
    )
    settings: bool = Field(default=True, description="The account's settings and keys.")
    attachments: bool = Field(default=True, description="Attachments and standards pages.")
    installation: bool = Field(
        default=True, description="The installation's settings; an administrator's only."
    )


class TransferPairRequest(BaseModel):
    """The sender's half of the key exchange. Public: the exchange is the proof."""

    model_config = ConfigDict(extra="forbid")

    slot: str = Field(min_length=3, max_length=3)
    message: str = Field(min_length=8, max_length=200, description="SPAKE2, base64.")
    name: str = Field(default="", max_length=120)
    revision: str | None = Field(default=None, max_length=64)
    version: str = Field(default="", max_length=40)
    protocol: int = Field(default=1, description="What the sender speaks (rows.PROTOCOL).")


class TransferPaired(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: str
    message: str = Field(description="The receiver's half of the exchange, base64.")
    confirm: str = Field(description="Proof the receiver derived the same key.")


class TransferStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: StepKey
    total: int
    done: int
    state: Literal["waiting", "doing", "done", "skipped"]


class TransferStatus(BaseModel):
    """A transfer under way, from either end."""

    model_config = ConfigDict(extra="forbid")

    id: str
    direction: Literal["out", "in"]
    peer: str = Field(description="The other machine: its address, or the name it gave.")
    state: Literal["running", "receiving", "importing", "done", "failed"]
    error: str | None = None
    steps: list[TransferStep]
    moved: list[str] = Field(default_factory=list, description="Names of the projects moved.")
    skipped: int = Field(default=0, description="Projects the receiver already had.")
    counts: dict[str, int] = Field(default_factory=dict, description="Rows written, per table.")


__all__ = [
    "TransferHello",
    "TransferHere",
    "TransferPairRequest",
    "TransferPaired",
    "TransferPeer",
    "TransferSendRequest",
    "TransferStep",
    "TransferCode",
    "TransferStatus",
]
