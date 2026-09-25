"""In-process event bus feeding ``GET /api/events`` (server-sent events).

The store publishes here on every persisted change; subscribers (one per open SSE
connection) get their own queue. The last ``HISTORY`` events are also kept with their
ids, so a reader whose connection dropped can ask for what it missed (``?since=``);
older than that, the API is the source of truth, as it always is.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.job import utcnow

MAX_QUEUE = 1000
HISTORY = 500  # events kept for a reader that reconnects


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str  # job.state | job.data | test_run.state | activity | project
    at: datetime = Field(default_factory=utcnow)
    project_id: str | None = None
    job_id: str | None = None
    owner_id: str | None = Field(
        default=None,
        description="Who may see this. Events carry the request text and every "
        "transition note, so the bus filters on it rather than trusting the reader.",
    )
    payload: dict[str, Any] = Field(default_factory=dict)

    def sse(self, event_id: int) -> str:
        # owner_id never leaves the server: it decides who is sent the event, and saying
        # it out loud would hand one tenant another's account id
        data = self.model_dump(mode="json", exclude={"owner_id"})
        return f"id: {event_id}\nevent: {self.type}\ndata: {json.dumps(data)}\n\n"

    def visible_to(self, owner_id: str | None) -> bool:
        """``None`` is an administrator's view of an installation with no owners yet."""
        return self.owner_id is None or owner_id is None or self.owner_id == owner_id


class EventBus:
    def __init__(self, history: int = HISTORY) -> None:
        self._lock = threading.Lock()
        # each subscriber carries who it reads for, so filtering happens on publish
        self._subscribers: list[tuple[queue.Queue[Event], str | None]] = []
        self._seq = 0
        self._history: deque[tuple[int, Event]] = deque(maxlen=history)

    def publish(self, event: Event) -> None:
        with self._lock:
            self._seq += 1
            self._history.append((self._seq, event))
            subscribers = list(self._subscribers)
        for q, owner_id in subscribers:
            # filtered at the source, so one tenant's event never enters another's queue
            if not event.visible_to(owner_id):
                continue
            with contextlib.suppress(queue.Full):  # a stalled reader loses events
                q.put_nowait(event)

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._seq

    def since(self, event_id: int, owner_id: str | None = None) -> list[tuple[int, Event]]:
        """What was published after ``event_id``, oldest first, as far back as the bus
        still remembers. An id it no longer holds returns everything it has.

        A reconnecting reader is filtered the same way a live one is: the backlog would
        otherwise be a way around the filter.
        """
        with self._lock:
            return [
                (i, e) for i, e in self._history if i > event_id and e.visible_to(owner_id)
            ]

    def emit(self, type_: str, **kw: Any) -> None:
        payload = kw.pop("payload", {})
        self.publish(Event(type=type_, payload=payload, **kw))

    @contextmanager
    def subscribe(self, owner_id: str | None = None) -> Iterator[queue.Queue[Event]]:
        """A queue of the events this reader may see. ``None`` sees everything, which is
        what a single-tenant installation and the test suite want."""
        q: queue.Queue[Event] = queue.Queue(maxsize=MAX_QUEUE)
        entry = (q, owner_id)
        with self._lock:
            self._subscribers.append(entry)
        try:
            yield q
        finally:
            with self._lock:
                self._subscribers.remove(entry)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


__all__ = ["Event", "EventBus"]
