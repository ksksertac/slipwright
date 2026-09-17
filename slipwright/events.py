"""In-process event bus feeding ``GET /api/events`` (server-sent events).

The store publishes here on every persisted change; subscribers (one per open SSE
connection) get their own queue. Nothing is buffered for absent subscribers: the feed
is a wake-up signal, the API is the source of truth.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from slipwright.schemas.job import utcnow

MAX_QUEUE = 1000


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str  # job.state | job.data | test_run.state | activity | project
    at: datetime = Field(default_factory=utcnow)
    project_id: str | None = None
    job_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def sse(self, event_id: int) -> str:
        data = self.model_dump(mode="json")
        return f"id: {event_id}\nevent: {self.type}\ndata: {json.dumps(data)}\n\n"


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[Event]] = []
        self._seq = 0

    def publish(self, event: Event) -> None:
        with self._lock:
            self._seq += 1
            subscribers = list(self._subscribers)
        for q in subscribers:
            with contextlib.suppress(queue.Full):  # a stalled reader loses events
                q.put_nowait(event)

    def emit(self, type_: str, **kw: Any) -> None:
        payload = kw.pop("payload", {})
        self.publish(Event(type=type_, payload=payload, **kw))

    @contextmanager
    def subscribe(self) -> Iterator[queue.Queue[Event]]:
        q: queue.Queue[Event] = queue.Queue(maxsize=MAX_QUEUE)
        with self._lock:
            self._subscribers.append(q)
        try:
            yield q
        finally:
            with self._lock:
                self._subscribers.remove(q)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


__all__ = ["Event", "EventBus"]
