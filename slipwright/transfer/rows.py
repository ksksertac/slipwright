"""What a transfer carries, and the shape it travels in.

Shared by both sides so they cannot disagree on it. The account is what moves -- its
projects and everything hanging off them, its settings, its own standards pages -- and
the people do not: users, sessions, tokens and memberships stay where they are, and on
the other side everything belongs to whoever opened it there.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

#: In the order they are sent and written: parents before the rows that point at them.
TABLES = (
    "projects",
    "project_briefs",
    "jobs",
    "job_history",
    "job_messages",
    "test_runs",
    "attachments",
    "standards_pages",
    "translations",
    "settings",
)

#: What the two sides speak. A sender asks the receiver's ``hello`` first and goes no
#: further on a different number: version 1 sent rows as JSON lists, two hundred at a
#: time, and two hundred rows of agent transcripts were more than a part may be.
#: Version 3 carries what people said to a development's agents (``job_messages``).
PROTOCOL = 3
#: The largest piece of anything in one part: a run of rows, a slice of a checkout. Rows
#: are a stream of JSON lines cut at this size, wherever the cut falls, so neither a long
#: history nor a fifty-megabyte attachment is ever more than one part can carry.
CHUNK = 4 * 1024 * 1024

#: Settings that describe the machine rather than the account, so are never carried: the
#: address a Mac was told to call, and bookkeeping the receiver keeps for itself.
MACHINE_SETTINGS = frozenset({"workers.address", "jira.last_sweep", "prices.last_fetch"})
MACHINE_PREFIXES = ("transfer.",)

#: The steps a person watches, on both screens: (key, what is counted).
STEPS = ("pair", "projects", "jobs", "settings", "attachments", "standards", "repos", "finish")
#: Which step each table's rows count towards.
STEP_OF = {
    "projects": "projects",
    "project_briefs": None,
    "jobs": "jobs",
    "job_history": None,
    "job_messages": None,
    "test_runs": None,
    "attachments": "attachments",
    "standards_pages": "standards",
    "translations": None,
    "settings": "settings",
}


def carried(name: str) -> bool:
    return name not in MACHINE_SETTINGS and not name.startswith(MACHINE_PREFIXES)


def encode(row: dict[str, Any]) -> dict[str, Any]:
    """A row as JSON can carry it: bytes become ``{"$b": base64}``."""
    return {
        k: {"$b": base64.b64encode(v).decode("ascii")} if isinstance(v, bytes | memoryview) else v
        for k, v in row.items()
    }


def decode(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: base64.b64decode(v["$b"]) if isinstance(v, dict) and set(v) == {"$b"} else v
        for k, v in row.items()
    }


@dataclass
class Step:
    key: str
    total: int = 0
    done: int = 0
    state: str = "waiting"  # waiting | doing | done | skipped


@dataclass
class Progress:
    """Where a transfer is, as either screen shows it."""

    steps: list[Step] = field(default_factory=lambda: [Step(k) for k in STEPS])

    def step(self, key: str) -> Step:
        for step in self.steps:
            if step.key == key:
                return step
        raise KeyError(key)

    def begin(self, key: str, total: int | None = None) -> None:
        step = self.step(key)
        step.state = "doing"
        if total is not None:
            step.total = total

    def advance(self, key: str, n: int = 1) -> None:
        step = self.step(key)
        if step.state == "waiting":
            step.state = "doing"
        step.done += n

    def finish(self, key: str) -> None:
        step = self.step(key)
        step.state = "done"
        step.done = max(step.done, step.total)

    def add(self, key: str) -> None:
        """An extra step at the end (deleting what was sent, on the sender)."""
        if all(s.key != key for s in self.steps):
            self.steps.append(Step(key))


__all__ = [
    "CHUNK",
    "MACHINE_SETTINGS",
    "PROTOCOL",
    "STEPS",
    "STEP_OF",
    "TABLES",
    "Progress",
    "Step",
    "carried",
    "decode",
    "encode",
]
