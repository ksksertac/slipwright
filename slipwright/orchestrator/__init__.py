from __future__ import annotations

from collections.abc import Callable, Mapping

from slipwright.schemas.job import Job, JobState
from slipwright.store import JobStore

LEGAL_TRANSITIONS: dict[JobState, tuple[JobState, ...]] = {
    JobState.CREATED: (JobState.ANALYZING,),
    JobState.ANALYZING: (JobState.AWAITING_PROFILE_APPROVAL, JobState.FAILED),
    JobState.AWAITING_PROFILE_APPROVAL: (JobState.ANALYZING, JobState.PLANNING),
    JobState.PLANNING: (JobState.AWAITING_PLAN_APPROVAL, JobState.FAILED),
    JobState.AWAITING_PLAN_APPROVAL: (JobState.PLANNING, JobState.DEVELOPING),
    JobState.DEVELOPING: (JobState.BUILD_GATE, JobState.FAILED),
    JobState.BUILD_GATE: (JobState.DEVELOPING, JobState.QA, JobState.FAILED),
    JobState.QA: (JobState.AWAITING_TEST_APPROVAL, JobState.FAILED),
    JobState.AWAITING_TEST_APPROVAL: (JobState.QA, JobState.DEVOPS),
    JobState.DEVOPS: (JobState.DONE, JobState.FAILED),
    JobState.DONE: (),
    JobState.FAILED: (),
}


class IllegalTransitionError(ValueError):
    def __init__(self, from_state: JobState, to_state: JobState) -> None:
        super().__init__(f"illegal state transition: {from_state.value} -> {to_state.value}")
        self.from_state = from_state
        self.to_state = to_state


class Orchestrator:
    """Small state machine for job progression. The store is the source of truth."""

    def __init__(self, store: JobStore) -> None:
        self.store = store

    @staticmethod
    def allowed_transitions(current: JobState) -> tuple[JobState, ...]:
        return LEGAL_TRANSITIONS.get(current, ())

    def can_transition(self, from_state: JobState, to_state: JobState) -> bool:
        return to_state in self.allowed_transitions(from_state)

    def transition(
        self,
        job: Job | str,
        to_state: JobState,
        *,
        note: str | None = None,
        detail: str | None = None,
        side_effect: Callable[[Job], Job | None] | None = None,
    ) -> Job:
        current = self._load_job(job)
        if not self.can_transition(current.state, to_state):
            raise IllegalTransitionError(current.state, to_state)

        updated = self.store.update_state(current.id, to_state, note=note, detail=detail)
        if side_effect is not None:
            result = side_effect(updated)
            if result is not None:
                return result
        return updated

    def advance(
        self,
        job: Job | str,
        to_state: JobState,
        *,
        note: str | None = None,
        detail: str | None = None,
        side_effect: Callable[[Job], Job | None] | None = None,
    ) -> Job:
        return self.transition(job, to_state, note=note, detail=detail, side_effect=side_effect)

    def resume(
        self,
        job: Job | str,
        *,
        handlers: Mapping[JobState, Callable[[Job], Job | None]] | None = None,
    ) -> Job:
        current = self._load_job(job)
        if current.is_terminal:
            return current

        if handlers is None:
            return current

        handler = handlers.get(current.state)
        if handler is None:
            return current

        result = handler(current)
        return current if result is None else result

    def _load_job(self, job: Job | str) -> Job:
        if isinstance(job, str):
            return self.store.get(job)
        return job


def resume(
    orchestrator: Orchestrator,
    job: Job | str,
    *,
    handlers: Mapping[JobState, Callable[[Job], Job | None]] | None = None,
) -> Job:
    return orchestrator.resume(job, handlers=handlers)


__all__ = [
    "IllegalTransitionError",
    "LEGAL_TRANSITIONS",
    "Orchestrator",
    "resume",
]
