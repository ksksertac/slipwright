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
import threading
import traceback
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from slipwright.gates import GateResult, build_gate
from slipwright.invoke import DEFAULT_TIMEOUT_S, RoleResult, get_default_provider
from slipwright.orchestrator import IllegalTransitionError, Orchestrator
from slipwright.providers import ModelProvider
from slipwright.roles import analyst, developer, planner
from slipwright.roles.common import apply_changes, require_worktree
from slipwright.roles.results import AnalystResult, DeveloperResult, PlannerResult
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState
from slipwright.schemas.profile import Profile, RoleName
from slipwright.store import JobStore
from slipwright.workspace import Workspace
from slipwright.workspace import git as g

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
        max_reject_rounds: int = 3,
        max_build_attempts: int = 3,
        gate_timeout_s: float | None = None,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.orchestrator = Orchestrator(store)
        self.seed_profile = seed_profile
        self._provider = provider
        self.timeout_s = timeout_s
        self.max_reject_rounds = max_reject_rounds
        self.max_build_attempts = max_build_attempts
        self.gate_timeout_s = gate_timeout_s
        self.handlers: dict[JobState, Handler] = {
            JobState.ANALYZING: self._analyze,
            JobState.PLANNING: self._plan,
            JobState.DEVELOPING: self._develop,
            JobState.BUILD_GATE: self._build_gate,
        }
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
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

    def start(self, job_id: str, *, run: bool = True) -> Job:
        """Move a new job into analysis. With ``run=False`` only the transition happens;
        call ``resume`` later (e.g. from a background worker) to execute the phase."""
        job = self.orchestrator.transition(job_id, JobState.ANALYZING, note="job started")
        return self._run(job) if run else job

    def approve(self, job_id: str, *, run: bool = True) -> Job:
        job = self.store.get(job_id)
        edges = APPROVAL_EDGES.get(job.state)
        if edges is None:
            raise NotAwaitingApproval(job)
        job.data.feedback = None
        job.data.reject_rounds = 0
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[0], note="approved")
        return self._run(job) if run else job

    def reject(self, job_id: str, feedback: str, *, run: bool = True) -> Job:
        job = self.store.get(job_id)
        edges = APPROVAL_EDGES.get(job.state)
        if edges is None:
            raise NotAwaitingApproval(job)
        job.data.feedback = feedback
        job.data.reject_rounds += 1
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[1], note=f"rejected: {feedback}")
        return self._run(job) if run else job

    def resume(self, job_id: str) -> Job:
        """Continue a job from its persisted state; a no-op unless it was mid-phase."""
        return self._run(self.store.get(job_id))

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
        """Run phase handlers until the job stops at a gate or ends.

        One job runs in one thread at a time; a second caller waits, then re-reads the
        persisted state so it never acts on a stale view.
        """
        with self._locks[job.id]:
            job = self.store.get(job.id)
            while job.state in WORKING_STATES:
                handler = self.handlers.get(job.state)
                if handler is None:
                    log.warning("no handler for state %s; job %s left as is", job.state, job.id)
                    return job
                before = job.state
                try:
                    job = handler(job)
                except Exception as exc:  # noqa: BLE001 - a crashed phase fails the job
                    log.exception("job %s: %s phase crashed", job.id, before.value)
                    return self._fail(
                        job,
                        f"{before.value} crashed: {type(exc).__name__}: {exc}",
                        detail=traceback.format_exc(),
                    )
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
        if job.worktree_path is not None:  # recorded but gone from disk: start clean
            self.workspace.destroy(job)
        self.workspace.create(job)
        return self.store.save(job)

    def _invocation_failed(self, job: Job, result: RoleResult) -> Job:
        assert result.error is not None
        return self._fail(
            job,
            f"{result.role.value} failed: {result.error.kind.value}",
            detail=result.error.message,
        )

    @staticmethod
    def _profile(job: Job) -> Profile:
        if job.profile is None:
            raise RuntimeError(f"job {job.id} has no approved profile")
        return job.profile

    def _run_gate(self, job: Job) -> GateResult:
        kwargs = {} if self.gate_timeout_s is None else {"timeout_s": self.gate_timeout_s}
        return build_gate(self._profile(job), require_worktree(job), **kwargs)

    @staticmethod
    def _phases(job: Job) -> list[dict[str, Any]]:
        plan = job.data.plan or {}
        phases: list[dict[str, Any]] = plan.get("phases", [])
        return phases

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

    def _plan(self, job: Job) -> Job:
        if job.data.reject_rounds > self.max_reject_rounds:
            return self._fail(
                job,
                f"plan rejected {job.data.reject_rounds} times; giving up",
                detail=job.data.feedback,
            )
        result = planner.run(
            job, self._profile(job), provider=self.provider, timeout_s=self.timeout_s
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, PlannerResult)
        job.data.plan = result.output.model_dump(mode="json")
        job.data.phase_index = 0
        job.data.build_attempts = 0
        job.data.last_build_output = None
        self.store.save(job)
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_PLAN_APPROVAL,
            note=f"planner: {result.output.summary} ({len(result.output.phases)} phases)",
            detail=json.dumps(job.data.plan, indent=2),
        )

    def _develop(self, job: Job) -> Job:
        profile = self._profile(job)
        phases = self._phases(job)
        index = job.data.phase_index
        if index >= len(phases):
            return self._fail(job, f"no plan phase {index + 1} to develop")
        result = developer.run(job, profile, provider=self.provider, timeout_s=self.timeout_s)
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, DeveloperResult)

        worktree = require_worktree(job)
        touched = apply_changes(job, profile, RoleName.DEVELOPER, result.output.changes)
        g.stage_all(worktree)
        diff = g.staged_diff(worktree)
        attempt = f", fix attempt {job.data.build_attempts}" if job.data.build_attempts else ""
        return self.orchestrator.transition(
            job,
            JobState.BUILD_GATE,
            note=(
                f"developer phase {index + 1}/{len(phases)}{attempt}: "
                f"{result.output.summary} ({len(touched)} files)"
            ),
            detail=diff or "(no changes)",
        )

    def _build_gate(self, job: Job) -> Job:
        phases = self._phases(job)
        index = job.data.phase_index
        gate = self._run_gate(job)
        if gate.ok:
            worktree = require_worktree(job)
            g.stage_all(worktree)
            goal = phases[index].get("goal", "") if index < len(phases) else ""
            g.commit(worktree, f"slipwright: phase {index + 1}: {goal}")
            job.data.phase_index = index + 1
            job.data.build_attempts = 0
            job.data.last_build_output = None
            self.store.save(job)
            done = job.data.phase_index >= len(phases)
            return self.orchestrator.transition(
                job,
                JobState.QA if done else JobState.DEVELOPING,
                note=f"build gate passed for phase {index + 1}/{len(phases)}",
                detail=gate.tail,
            )

        job.data.build_attempts += 1
        job.data.last_build_output = gate.tail
        self.store.save(job)
        if job.data.build_attempts >= self.max_build_attempts:
            return self._fail(
                job,
                f"build gate failed {job.data.build_attempts} times on phase {index + 1}",
                detail=gate.tail,
            )
        return self.orchestrator.transition(
            job,
            JobState.DEVELOPING,
            note=(
                f"build gate failed on phase {index + 1} "
                f"(attempt {job.data.build_attempts}/{self.max_build_attempts})"
            ),
            detail=gate.tail,
        )


def is_approval_state(state: JobState) -> bool:
    return state in APPROVAL_STATES


__all__ = ["APPROVAL_EDGES", "WORKING_STATES", "Engine", "NotAwaitingApproval"]
