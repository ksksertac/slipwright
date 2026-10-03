"""A machine lent to the account, as a model provider (T17.1).

A machine somebody on the account lent writes phases with a model of its own -- their
Claude Code, their Codex, their key. To the engine it is one more provider: the request
it would have sent its own vendor is put in ``worker_calls``, one of the account's
machines that writes the domain claims it, and the text that comes back is parsed and
validated by ``invoke_role`` exactly like any vendor's. So a machine's wrong answer costs a
retry, never a wrong file, and nothing downstream knows where the answer came from.

What it must never cost is the development. A laptop closes, a train goes into a tunnel,
somebody quits the app halfway through an hour-long phase. So a call is only ever waited
on while somebody is visibly at it: not claimed within ``CLAIM_S``, or claimed and not
heard from for ``QUIET_S``, or failed by the machine, and it is taken back and asked of
``fallback`` -- the account's own provider, as if no machine had been there.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from slipwright.providers import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ProviderTimeoutError,
)
from slipwright.schemas.job import utcnow

log = logging.getLogger(__name__)

#: How long a call waits to be claimed. A machine polls every few seconds and the engine
#: only offers one when a machine that writes the domain is there, so a call still queued
#: after this has nobody coming for it.
CLAIM_S = 45.0
#: How long a claimed call may go unheard of. The machine says something every 15-20 s.
QUIET_S = 60.0
#: How often the wait looks at the row.
TICK_S = 1.0
#: What the cost panel calls an answer a machine wrote: on its own plan, so not the
#: account's bill (``costs.on_a_subscription``).
MACHINE = "machine"


class MachineProvider:
    """Hands one request to a machine of ``owner_id`` that writes ``domain``, and falls back
    to ``fallback`` when none answers.

    ``store`` is the job store (``WorkerStoreMixin``); ``meta`` is what the machine is told
    the call is for (project, phase, goal, repository); ``stopping`` is asked every tick, so
    a development told to stop does not sit out an hour-long phase on a laptop."""

    def __init__(
        self,
        store: Any,
        owner_id: str | None,
        job_id: str,
        *,
        domain: str,
        phase: int | None,
        fallback: ModelProvider,
        meta: dict[str, Any] | None = None,
        stopping: Callable[[], bool] | None = None,
        claim_s: float = CLAIM_S,
        quiet_s: float = QUIET_S,
        tick_s: float = TICK_S,
    ) -> None:
        self.store = store
        self.owner_id = owner_id
        self.job_id = job_id
        self.domain = domain
        self.phase = phase
        self.fallback = fallback
        self.meta = meta or {}
        self.stopping = stopping or (lambda: False)
        self.claim_s = claim_s
        self.quiet_s = quiet_s
        self.tick_s = tick_s
        # the router asks this before the call to say where it is headed; a machine's
        # answer says itself which model wrote it
        self.route = getattr(fallback, "route", None)

    def complete(self, request: ModelRequest) -> ModelResponse:
        call_id = self.store.enqueue_worker_call(
            self.owner_id,
            self.job_id,
            role=request.role.value,
            domain=self.domain,
            phase=self.phase,
            request=self._request(request),
        )
        why = self._wait(call_id, request.timeout_s)
        if why is None:
            row = self.store.worker_call_row(call_id) or {}
            return ModelResponse(
                text=row.get("answer") or "",
                model=row.get("model") or "machine",
                provider=MACHINE,
                input_tokens=row.get("input_tokens"),
                output_tokens=row.get("output_tokens"),
                stop_reason="stop",
            )
        log.info("job %s: %s; the server's own model answers instead", self.job_id, why)
        return self.fallback.complete(request)

    def _wait(self, call_id: str, timeout_s: float) -> str | None:
        """None once the machine answered; otherwise why the call was taken back."""
        started = time.monotonic()
        while True:
            row = self.store.worker_call_row(call_id)
            state = (row or {}).get("state")
            if state == "done":
                return None
            if state in ("failed", "cancelled", None):
                return f"the machine did not write it ({(row or {}).get('error') or state})"
            waited = time.monotonic() - started
            why: str | None = None
            if self.stopping():
                why = "the development was told to stop"
            elif state == "queued" and waited > self.claim_s:
                why = f"no machine took it within {self.claim_s:g}s"
            elif state == "running" and _quiet_for(row) > self.quiet_s:
                why = f"its machine was not heard from for {self.quiet_s:g}s"
            elif waited > timeout_s:
                why = f"it took longer than {timeout_s:g}s"
            if why is not None:
                if self.store.take_back_worker_call(call_id, why):
                    if why.startswith("the development"):
                        # stopping is not the machine's failure: nothing is asked again
                        raise ProviderTimeoutError(why)
                    return why
                continue  # it finished between the look and the take-back: read it
            time.sleep(self.tick_s)

    def _request(self, request: ModelRequest) -> dict[str, Any]:
        """What the machine is given: the request as a vendor would get it, and what the
        call is for. Pictures travel as base64, as the protocol says."""
        return {
            **self.meta,
            "job_id": self.job_id,
            "phase": self.phase,
            "role": request.role.value,
            "domain": self.domain,
            "system": request.system,
            "prompt": request.prompt,
            "output_schema": request.output_schema,
            "images": [
                {
                    "media_type": i.media_type,
                    "data": base64.b64encode(i.data).decode(),
                    "label": i.label,
                }
                for i in request.images
            ],
            "thinking_depth": request.thinking_depth.value,
            "timeout_s": request.timeout_s,
        }


def _quiet_for(row: dict[str, Any] | None) -> float:
    heard = (row or {}).get("heard_at") or (row or {}).get("claimed_at")
    if not heard:
        return 0.0
    return (utcnow() - datetime.fromisoformat(heard)).total_seconds()


__all__ = ["CLAIM_S", "MACHINE", "QUIET_S", "MachineProvider"]
