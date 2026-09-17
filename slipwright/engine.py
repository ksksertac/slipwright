"""Engine: drives jobs through the pipeline.

The engine owns nothing the store does not know about. Every phase is a handler keyed by
the state it runs in; ``_run`` executes handlers until the job reaches an approval or
terminal state, and every transition is persisted through the orchestrator before the
next handler starts. That is what makes ``resume`` trivial: reload the job, look at its
state, run the handler for it.

Approval gates are structural: ``approve``/``reject`` are the only calls that leave an
approval state, and no handler is registered for those states.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from slipwright.invoke import DEFAULT_TIMEOUT_S, RoleResult, get_default_provider
from slipwright.orchestrator import IllegalTransitionError, Orchestrator
from slipwright.providers import ModelProvider
from slipwright.roles import analyst
from slipwright.roles.results import AnalystResult
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile
from slipwright.store import JobStore
from slipwright.workspace import Workspace

log = logging.getLogger(__name__)

WORKING_STATES: frozenset[JobState] = frozenset(
    {
        JobState.ANALYZING,
        JobState.PLANNING,
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        JobState.QA,
        JobState.DEVOPS,
    }
)

# approval state -> (state on approve, state on reject)
APPROVAL_EDGES: dict[JobState, tuple[JobState, JobState]] = {
    JobState.AWAITING_PROFILE_APPROVAL: (JobState.PLANNING, JobState.ANALYZING),
    JobState.AWAITING_PLAN_APPROVAL: (JobState.DEVELOPING, JobState.PLANNING),
    JobState.AWAITING_TEST_APPROVAL: (JobState.DEVOPS, JobState.QA),
}

Handler = Callable[[Job], Job]


class NotAwaitingApproval(ValueError):
    def __init__(self, job: Job) -> None:
        super().__init__(f"job {job.id} is not awaiting approval (state: {job.state.value})")
        self.job = job


class Engine:
    def __init__(
        self,
        store: JobStore,
        workspace: Workspace,
        *,
        seed_profile: Profile,
        provider: ModelProvider | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.orchestrator = Orchestrator(store)
        self.seed_profile = seed_profile
        self._provider = provider
        self.timeout_s = timeout_s
        self.handlers: dict[JobState, Handler] = {
            JobState.ANALYZING: self._analyze,
        }
        # ports held by jobs that outlived a previous process must stay taken
        self.workspace.reserve_ports(store.list())

    @property
    def provider(self) -> ModelProvider:
        if self._provider is None:
            self._provider = get_default_provider()
        return self._provider

    # -- public API ----------------------------------------------------------------------

    def create_job(self, request: str, repo_path: Path) -> Job:
        return self.store.create(Job(request=request, repo_path=repo_path))

    def start(self, job_id: str) -> Job:
        job = self.orchestrator.transition(job_id, JobState.ANALYZING, note="job started")
        return self._run(job)

    def approve(self, job_id: str) -> Job:
        job = self.store.get(job_id)
        edges = APPROVAL_EDGES.get(job.state)
        if edges is None:
            raise NotAwaitingApproval(job)
        job.data.feedback = None
        job.data.reject_rounds = 0
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[0], note="approved")
        return self._run(job)

    def reject(self, job_id: str, feedback: str) -> Job:
        job = self.store.get(job_id)
        edges = APPROVAL_EDGES.get(job.state)
        if edges is None:
            raise NotAwaitingApproval(job)
        job.data.feedback = feedback
        job.data.reject_rounds += 1
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[1], note=f"rejected: {feedback}")
        return self._run(job)

    def resume(self, job_id: str) -> Job:
        """Continue a job from its persisted state; a no-op unless it was mid-phase."""
        job = self.store.get(job_id)
        if job.state in WORKING_STATES:
            return self._run(job)
        return job

    def resume_all(self) -> list[Job]:
        return [self.resume(job.id) for job in self.store.list()]

    def message(self, job_id: str, text: str) -> Job:
        """Queue a steering message; the next role invocation will see it."""
        from slipwright.schemas.job import InboxMessage

        job = self.store.get(job_id)
        job.data.inbox.append(InboxMessage(text=text))
        return self.store.save(job)

    # -- driver --------------------------------------------------------------------------

    def _run(self, job: Job) -> Job:
        while job.state in WORKING_STATES:
            handler = self.handlers.get(job.state)
            if handler is None:
                log.warning("no handler for state %s; job %s left as is", job.state, job.id)
                return job
            before = job.state
            job = handler(job)
            if job.state is before:  # a handler must always move the job
                raise RuntimeError(f"handler for {before.value} did not change job {job.id}")
        return job

    def _fail(self, job: Job, note: str, detail: str | None = None) -> Job:
        try:
            return self.orchestrator.transition(job, JobState.FAILED, note=note, detail=detail)
        except IllegalTransitionError:
            return self.store.get(job.id)

    def _ensure_workspace(self, job: Job) -> Job:
        if job.worktree_path is not None and job.worktree_path.is_dir():
            return job
        job.worktree_path = None
        self.workspace.create(job)
        return self.store.save(job)

    def _invocation_failed(self, job: Job, result: RoleResult) -> Job:
        assert result.error is not None
        return self._fail(
            job,
            f"{result.role.value} failed: {result.error.kind.value}",
            detail=result.error.message,
        )

    # -- phase handlers ------------------------------------------------------------------

    def _analyze(self, job: Job) -> Job:
        job = self._ensure_workspace(job)
        result = analyst.run(
            job, seed=self.seed_profile, provider=self.provider, timeout_s=self.timeout_s
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, AnalystResult)
        job.profile = analyst.accepted_profile(result.output, self.seed_profile)
        self.store.save(job)
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_PROFILE_APPROVAL,
            note=f"analyst: {result.output.summary}",
            detail=json.dumps(job.profile.model_dump(mode="json"), indent=2),
        )


def is_approval_state(state: JobState) -> bool:
    return state in APPROVAL_STATES


__all__ = ["APPROVAL_EDGES", "WORKING_STATES", "Engine", "NotAwaitingApproval"]
