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
import time
import traceback
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from slipwright.gates import GateResult, build_gate
from slipwright.githost import CiState, CiStatus, GitHost, GitHostError
from slipwright.invoke import DEFAULT_TIMEOUT_S, RoleResult, get_default_provider
from slipwright.orchestrator import IllegalTransitionError, Orchestrator
from slipwright.providers import ModelProvider
from slipwright.roles import analyst, developer, devops, planner, qa
from slipwright.roles.common import apply_changes, require_worktree
from slipwright.roles.results import (
    AnalystResult,
    DeveloperResult,
    DevOpsResult,
    PlannerResult,
    QAResult,
)
from slipwright.schemas.job import APPROVAL_STATES, Job, JobState, utcnow
from slipwright.schemas.profile import Permission, Profile, RoleName
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
    # stage 1 (test list) approved -> QA writes the tests; stage 2 approved -> DevOps
    JobState.AWAITING_TEST_APPROVAL: (JobState.DEVOPS, JobState.QA),
}


def approval_edges(job: Job) -> tuple[JobState, JobState] | None:
    edges = APPROVAL_EDGES.get(job.state)
    if (
        edges is not None
        and job.state is JobState.AWAITING_TEST_APPROVAL
        and job.data.qa_stage == 1
    ):
        return (JobState.QA, JobState.QA)
    return edges


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
        max_ci_attempts: int = 3,
        gate_timeout_s: float | None = None,
        git_host: GitHost | None = None,
        ci_poll_s: float = 15.0,
        ci_timeout_s: float = 3600.0,
    ) -> None:
        self.store = store
        self.workspace = workspace
        self.orchestrator = Orchestrator(store)
        self.seed_profile = seed_profile
        self._provider = provider
        self.timeout_s = timeout_s
        self.max_reject_rounds = max_reject_rounds
        self.max_build_attempts = max_build_attempts
        self.max_ci_attempts = max_ci_attempts
        self.gate_timeout_s = gate_timeout_s
        self._git_host = git_host
        self.ci_poll_s = ci_poll_s
        self.ci_timeout_s = ci_timeout_s
        self.handlers: dict[JobState, Handler] = {
            JobState.ANALYZING: self._analyze,
            JobState.PLANNING: self._plan,
            JobState.DEVELOPING: self._develop,
            JobState.BUILD_GATE: self._build_gate,
            JobState.QA: self._qa,
            JobState.DEVOPS: self._devops,
        }
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        # ports held by jobs that outlived a previous process must stay taken
        self.workspace.reserve_ports(store.list())

    @property
    def provider(self) -> ModelProvider:
        if self._provider is None:
            self._provider = get_default_provider()
        return self._provider

    @property
    def git_host(self) -> GitHost:
        if self._git_host is None:
            from slipwright.githost import GhHost

            self._git_host = GhHost()
        return self._git_host

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
        edges = approval_edges(job)
        if edges is None:
            raise NotAwaitingApproval(job)
        note = "approved"
        if job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage == 1:
            job.data.qa_stage = 2
            job.data.build_attempts = 0
            job.data.last_build_output = None
            note = f"approved {len(job.data.test_cases)} test cases"
        job.data.feedback = None
        job.data.reject_rounds = 0
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[0], note=note)
        return self._run(job) if run else job

    def reject(self, job_id: str, feedback: str, *, run: bool = True) -> Job:
        job = self.store.get(job_id)
        edges = approval_edges(job)
        if edges is None:
            raise NotAwaitingApproval(job)
        job.data.feedback = feedback
        job.data.reject_rounds += 1
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[1], note=f"rejected: {feedback}")
        return self._run(job) if run else job

    def set_test_cases(self, job_id: str, cases: list[dict[str, Any]]) -> Job:
        """Replace the proposed test list while the job waits for its approval."""
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_TEST_APPROVAL or job.data.qa_stage != 1:
            raise NotAwaitingApproval(job)
        job.data.test_cases = qa.normalise_cases(cases)
        return self.store.save(job)

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
        job.data.base_commit = g.head_commit(require_worktree(job))
        return self.store.save(job)

    def _branch_diff(self, job: Job) -> str:
        worktree = require_worktree(job)
        base = job.data.base_commit
        if base is None:
            return "(base commit unknown)"
        return g.run(worktree, "diff", "--no-color", base, "HEAD").stdout or "(no changes)"

    def _invocation_failed(self, job: Job, result: RoleResult) -> Job:
        assert result.error is not None
        return self._fail(
            job,
            f"{result.role.value} failed: {result.error.kind.value}",
            detail=result.error.message,
        )

    def _invoke(
        self, role: RoleName, run: Callable[..., RoleResult], job: Job, **kw: Any
    ) -> RoleResult:
        """Every model call goes through here: run the role, then drain the inbox.

        Messages pending at call time were injected into the role's context by
        ``base_context``; afterwards they are marked consumed and the fact is recorded in
        the job's history, so a message is delivered exactly once.
        """
        pending = job.pending_messages
        result = run(job, provider=self.provider, timeout_s=self.timeout_s, **kw)
        if pending:
            now = utcnow()
            for message in pending:
                message.consumed_at = now
                message.consumed_by = role.value
            self.store.save(job)
            self.store.update_state(
                job.id,
                job.state,
                note=f"inbox: {len(pending)} message(s) consumed by {role.value}",
                detail="\n\n".join(f"[{m.id}] {m.text}" for m in pending),
            )
            job.history = self.store.get(job.id).history
        return result

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
        result = self._invoke(RoleName.ANALYST, analyst.run, job, seed=self.seed_profile)
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
        result = self._invoke(RoleName.PLANNER, planner.run, job, profile=self._profile(job))
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
        result = self._invoke(RoleName.DEVELOPER, developer.run, job, profile=profile)
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

    def _qa(self, job: Job) -> Job:
        return self._qa_propose(job) if job.data.qa_stage == 1 else self._qa_write(job)

    def _qa_propose(self, job: Job) -> Job:
        profile = self._profile(job)
        result = self._invoke(
            RoleName.QA, qa.run, job, profile=profile, branch_diff=self._branch_diff(job)
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, QAResult)
        job.data.test_cases = [c.model_dump() for c in result.output.test_cases]
        job.data.feedback = None
        self.store.save(job)
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_TEST_APPROVAL,
            note=f"qa: {len(job.data.test_cases)} test cases proposed — {result.output.summary}",
            detail=json.dumps(job.data.test_cases, indent=2),
        )

    def _qa_write(self, job: Job) -> Job:
        """Stage two: write tests for the approved list, then pass the same build gate."""
        profile = self._profile(job)
        worktree = require_worktree(job)
        diff = self._branch_diff(job)
        while True:
            result = self._invoke(RoleName.QA, qa.run, job, profile=profile, branch_diff=diff)
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, QAResult)
            touched = apply_changes(job, profile, RoleName.QA, result.output.changes)
            g.stage_all(worktree)
            test_diff = g.staged_diff(worktree)
            gate = self._run_gate(job)
            if gate.ok:
                g.commit(worktree, "slipwright: tests")
                job.data.feedback = None
                job.data.build_attempts = 0
                job.data.last_build_output = None
                self.store.save(job)
                return self.orchestrator.transition(
                    job,
                    JobState.AWAITING_TEST_APPROVAL,
                    note=(
                        f"qa: tests written and green ({len(touched)} files) — "
                        f"{result.output.summary}"
                    ),
                    detail=(test_diff or "(no changes)") + "\n\n" + gate.tail,
                )
            job.data.build_attempts += 1
            job.data.last_build_output = gate.tail
            self.store.save(job)
            if job.data.build_attempts >= self.max_build_attempts:
                return self._fail(
                    job,
                    f"qa tests failed the build gate {job.data.build_attempts} times",
                    detail=gate.tail,
                )

    def _devops(self, job: Job) -> Job:
        profile = self._profile(job)
        worktree = require_worktree(job)
        if Permission.GIT_PUSH not in profile.roles[RoleName.DEVOPS].permissions:
            return self._fail(job, "devops role lacks the git_push permission")

        if job.data.pr_url is None:
            result = self._invoke(
                RoleName.DEVOPS,
                devops.run,
                job,
                profile=profile,
                branch_diff=self._branch_diff(job),
            )
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, DevOpsResult)
            try:
                self.git_host.push(worktree, job.branch)
                job.data.pr_url = self.git_host.open_pr(
                    worktree, job.branch, result.output.pr_title, result.output.pr_body
                )
            except GitHostError as exc:
                return self._fail(job, f"devops: {exc}")
            self.store.save(job)

        while True:
            status = self._poll_ci(job)
            if status.state is CiState.PENDING:
                return self._fail(
                    job, f"CI still pending after {self.ci_timeout_s:.0f}s", detail=status.summary
                )
            if status.state in (CiState.SUCCESS, CiState.NONE):
                return self.orchestrator.transition(
                    job,
                    JobState.DONE,
                    note=f"PR {job.data.pr_url} ({status.state.value})",
                    detail=status.summary,
                )
            job.data.ci_attempts += 1
            self.store.save(job)
            if job.data.ci_attempts > self.max_ci_attempts:
                return self._fail(
                    job,
                    f"CI red after {self.max_ci_attempts} fix attempts",
                    detail=status.log or status.summary,
                )
            fix = self._invoke(
                RoleName.DEVELOPER,
                developer.run,
                job,
                profile=profile,
                ci_failure=status.log or status.summary,
            )
            if not fix.ok:
                return self._invocation_failed(job, fix)
            assert isinstance(fix.output, DeveloperResult)
            apply_changes(job, profile, RoleName.DEVELOPER, fix.output.changes)
            g.stage_all(worktree)
            g.commit(worktree, f"slipwright: CI fix {job.data.ci_attempts}: {fix.output.summary}")
            try:
                self.git_host.push(worktree, job.branch)
            except GitHostError as exc:
                return self._fail(job, f"devops: {exc}")

    def _poll_ci(self, job: Job) -> CiStatus:
        worktree = require_worktree(job)
        assert job.data.pr_url is not None
        deadline = time.monotonic() + self.ci_timeout_s
        while True:
            status = self.git_host.ci_status(worktree, job.branch, job.data.pr_url)
            if status.terminal or time.monotonic() >= deadline:
                return status
            time.sleep(self.ci_poll_s)


def is_approval_state(state: JobState) -> bool:
    return state in APPROVAL_STATES


__all__ = ["APPROVAL_EDGES", "WORKING_STATES", "Engine", "NotAwaitingApproval"]
