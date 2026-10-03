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

import contextlib
import copy
import hashlib
import inspect
import json
import logging
import os
import threading
import time
import traceback
from collections import defaultdict
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from pydantic import ValidationError

from slipwright import attachments as attached
from slipwright import prices, workers
from slipwright.accounts import Accounts
from slipwright.events import EventBus
from slipwright.gates import DEFAULT_TIMEOUT_S as GATE_TIMEOUT_S
from slipwright.gates import GateResult, build_gate, run_command, toolchains
from slipwright.gates.runner import Runner, build_runner
from slipwright.githost import CiState, CiStatus, GitHost, GitHostError, NoRemote
from slipwright.github import GitHubClient, GitHubError, GitHubSettings
from slipwright.hostpaths import HostPaths
from slipwright.invoke import (
    DEFAULT_TIMEOUT_S,
    RETRYABLE,
    InvokeError,
    InvokeErrorKind,
    RoleResult,
    Usage,
    may_be_blind,
)
from slipwright.jira import DEFAULT_ISSUE_TYPES, JiraClient, JiraError, JiraSettings
from slipwright.jiraactions import ActionOutcome, ActionRunner, jira_context
from slipwright.jirasync import JiraSync
from slipwright.mail import Mailer, MailSettings, OutboxMailer, SmtpMailer
from slipwright.notify.core import (
    notify_builder_wait,
    notify_gate,
    notify_outcome,
    settle_prompts,
)
from slipwright.orchestrator import IllegalTransitionError, Orchestrator
from slipwright.pipeline import StepCard, StepStatus, lane_for
from slipwright.providers import ModelProvider, ProviderUnavailableError
from slipwright.providers.codex import Logins
from slipwright.providers.evren import EvrenProvider, Terms
from slipwright.providers.registry import (
    CHATGPT,
    DEFAULT_PROVIDER,
    PROVIDERS,
    Credentials,
    RoutingProvider,
    build_client,
    list_models,
    model_on_default,
)
from slipwright.quota import Quotas
from slipwright.roles import (
    architect,
    designer,
    developer,
    devops,
    discovery,
    po,
    qa,
    reader,
    reconcile,
    review,
    supervisor,
    talk,
)
from slipwright.roles.common import (
    EditMismatch,
    apply_changes,
    read_files,
    require_worktree,
)
from slipwright.roles.results import (
    AgentAnswer,
    AnalysisResult,
    ArchitectResult,
    Breakdown,
    DeployPlan,
    DesignResult,
    DeveloperResult,
    DevOpsResult,
    IntakeResult,
    PlanPhase,
    POResult,
    QAResult,
    Recommendation,
    ReconcileResult,
    StackChoice,
    SupervisorResult,
    unbuilt_platforms,
)
from slipwright.roles.specialists import specialist_for
from slipwright.schemas.attachment import Attachment, Reading, Scope
from slipwright.schemas.brief import (
    BriefEdit,
    BriefItem,
    BriefState,
    Intake,
    IntakeQuestion,
    IntakeRound,
    ProjectBrief,
)
from slipwright.schemas.job import (
    APPROVAL_STATES,
    REDIRECTABLE,
    TITLE_MAX,
    ChangedFile,
    Commit,
    Job,
    JobData,
    JobMessage,
    JobResult,
    JobState,
    branch_name,
    headline,
    new_job_id,
    utcnow,
)
from slipwright.schemas.profile import Permission, Profile, RoleConfig, RoleName
from slipwright.schemas.project import BudgetSettings, Project, SupervisorSettings
from slipwright.schemas.testrun import TestRun, TestRunSource, TestRunStatus
from slipwright.sources import (
    GITHUB,
    SOURCES,
    SourceCredentials,
    SourceError,
    SourceHost,
    build_host,
)
from slipwright.sources.registry import SourceSettings
from slipwright.sources.scrub import scrub
from slipwright.standards import GLOBAL_DIR, PROJECT_SUBDIR, load_corpus, page_from_text
from slipwright.standards.editing import StandardsEditor
from slipwright.standards.index import (
    Embedder,
    HashingEmbedder,
    Hit,
    LocalEmbedder,
    NoEmbedder,
    OpenAIEmbedder,
    StandardsIndex,
    StandardsIndexError,
    corpus_fingerprint,
)
from slipwright.standards.retrieval import Retrieval, core_text, retrieve
from slipwright.steps import step_detail
from slipwright.store import ANY_OWNER, JobInProgress, JobNotFound, JobStore, ProjectNotFound
from slipwright.store.scoped import ScopedStore
from slipwright.support import SupportDesk
from slipwright.teams import Letter, Teams, builder_letter, failed_letter
from slipwright.translate import OTHER_LANGUAGE, strings_of, translate
from slipwright.workspace import Workspace
from slipwright.workspace import git as g
from slipwright.workspace.worktree import rmtree as _rmtree

log = logging.getLogger(__name__)

WORKING_STATES: frozenset[JobState] = frozenset(
    {
        JobState.BACKLOG,
        JobState.ARCHITECTURE,
        JobState.DESIGN,
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        JobState.REVIEW,
        JobState.QA,
        JobState.DEVOPS,
        JobState.RECONCILE,
    }
)

#: Where a development is between an approved plan and its last phase built: pulling in
#: what people pushed here can change which phases are left, so it is read against the
#: plan before anything carries on. Before the plan there are no phases to pass over;
#: after the last one there is nothing left to build.
BUILDING_STATES: frozenset[JobState] = frozenset(
    {
        JobState.DESIGN,
        JobState.AWAITING_DESIGN_APPROVAL,
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        JobState.REVIEW,
        JobState.AWAITING_REVIEW_APPROVAL,
        JobState.AWAITING_BUILDER,
        JobState.RECONCILE,
        JobState.AWAITING_RECONCILE_APPROVAL,
    }
)

# approval state -> (state on approve, state on reject)
APPROVAL_EDGES: dict[JobState, tuple[JobState, JobState]] = {
    JobState.AWAITING_BACKLOG_APPROVAL: (JobState.ARCHITECTURE, JobState.BACKLOG),
    JobState.AWAITING_ARCHITECTURE_APPROVAL: (JobState.DEVELOPING, JobState.ARCHITECTURE),
    # the screens: approving the rest carries on with the phase that was waiting, sending
    # them back puts the Designer to work again
    JobState.AWAITING_DESIGN_APPROVAL: (JobState.DEVELOPING, JobState.DESIGN),
    # accepting the violations continues with the next phase (or QA); rejecting sends the
    # phase back to its specialist
    JobState.AWAITING_REVIEW_APPROVAL: (JobState.DEVELOPING, JobState.DEVELOPING),
    # stage 1 (test list) approved -> QA writes the tests; stage 2 approved -> DevOps
    JobState.AWAITING_TEST_APPROVAL: (JobState.DEVOPS, JobState.QA),
    # the deployment proposal: approved, DevOps writes the scripts; rejected, it proposes
    # again with the feedback
    JobState.AWAITING_DEPLOY_APPROVAL: (JobState.DEVOPS, JobState.DEVOPS),
    # what people did by hand: approved, the first phase they did not finish is built (or
    # QA starts, when they finished them all); rejected, the Architect reads it again
    JobState.AWAITING_RECONCILE_APPROVAL: (JobState.DEVELOPING, JobState.RECONCILE),
}


def approval_edges(job: Job) -> tuple[JobState, JobState] | None:
    edges = APPROVAL_EDGES.get(job.state)
    if (
        edges is not None
        and job.state is JobState.AWAITING_TEST_APPROVAL
        and job.data.qa_stage == 1
    ):
        return (JobState.QA, JobState.QA)
    if edges is not None and job.state is JobState.AWAITING_REVIEW_APPROVAL:
        phases = (job.data.plan or {}).get("phases", [])
        if job.data.phase_index >= len(phases):
            return (JobState.QA, JobState.DEVELOPING)
    # a development with no screen in it needs no design, and skips straight to the first
    # phase rather than asking the Designer for screens nobody will build
    if (
        edges is not None
        and job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
        and designer.needs_drawing(job)
    ):
        return (JobState.DESIGN, edges[1])
    if job.state is JobState.AWAITING_DECISION:
        back = JobState(job.data.resume_state or JobState.DEVELOPING.value)
        return (back, back)
    if edges is not None and job.state is JobState.AWAITING_RECONCILE_APPROVAL:
        resume = int((job.data.reconcile or {}).get("resume_phase", 1)) - 1
        if resume >= len((job.data.plan or {}).get("phases", [])):
            return (JobState.QA, edges[1])
    return edges


def plan_fingerprint(job: Job) -> str:
    """What the plan asks for, as a short digest: the phases in order, each with its domain
    and its goal, and the tasks they cover.

    A step that produced something from the plan — the Designer's screens, say — stores this
    beside it and can then tell whether that work is still about the current plan. Rejecting
    the plan rewrites the phases, so the digest changes and the work is drawn again; a title
    reworded at the gate does not touch a goal or a domain, so it does not.
    """
    plan: dict[str, Any] = job.data.plan or {}
    parts: list[str] = []
    for phase in plan.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        parts.append(f"{phase.get('domain') or 'general'}|{(phase.get('goal') or '').strip()}")
    for task in sorted(str(t) for t in (job.data.backlog or {}).get("task_ids", [])):
        parts.append(task)
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


Handler = Callable[[Job], Job]


class ProjectCloneError(RuntimeError):
    pass


class _Corrected:
    """A provider wrapper for the retry after a malformed answer: the same request with
    the validation problem appended, so the model fixes its output instead of repeating
    it. Generic on purpose — every role goes through ``invoke_role`` the same way."""

    def __init__(self, inner: ModelProvider, problem: str) -> None:
        self._inner = inner
        self._problem = problem

    def complete(self, request: Any) -> Any:
        hint = (
            "\n\nYour previous answer was rejected and discarded: "
            f"{self._problem}\nAnswer again as one JSON object matching the schema above, "
            "with every required field present and nothing outside the JSON."
        )
        return self._inner.complete(request.model_copy(update={"prompt": request.prompt + hint}))


# what a specialist is told after each truncated answer, each step smaller than the last
TRUNCATION_STEPS: tuple[str, ...] = (
    "Return only a few files now (complete contents) and set phase_complete to false; "
    "you will be called again for the rest.",
    "Return exactly ONE file now, the most important one, complete, and set "
    "phase_complete to false; the rest comes in later calls.",
    "Return exactly ONE file, the smallest useful one, with no comments or blank lines "
    "beyond what the language needs, and set phase_complete to false.",
)


class NotAwaitingApproval(ValueError):
    def __init__(self, job: Job) -> None:
        super().__init__(f"job {job.id} is not awaiting approval (state: {job.state.value})")
        self.job = job


class JobIsRunning(ValueError):
    """A step cannot be re-run under a development that is still working."""

    def __init__(self, job: Job) -> None:
        super().__init__(f"job {job.id} is still running (state: {job.state.value})")
        self.job = job


def _by(who: str | None) -> str:
    return f" by {who}" if who else ""


class _Stopped(Exception):
    """Somebody stopped or paused the development while a step was still running it;
    raised before the step's next model call, caught by the run loop."""


@dataclass(frozen=True)
class _Halt:
    """What somebody asked of a development that was running at the time: to stop for
    good, to pause -- and whether to push the branch once it has -- or to plan again from
    the phase it is on (``message`` is the request, in ``job_messages``)."""

    kind: Literal["cancel", "pause", "redirect"]
    by: str | None = None
    push: bool = False
    message: str | None = None


class NothingToAsk(ValueError):
    """The step written to has no agent on it: a gate, or a step the lane does not have."""


#: How many earlier answers on the same step an agent is shown when asked again: enough
#: for "and why that?" to make sense, not a transcript.
ANSWERS_REMEMBERED = 6


class CannotSync(ValueError):
    """The branch cannot be pushed or pulled: no checkout yet, no remote, no token, or
    nothing there. The message is for the person who asked."""


class RemoteMoved(ValueError):
    """Commits were pushed to the branch while it was paused, and carrying on without
    them would build beside them -- and the next push would be refused, or worse."""


class PullConflict(ValueError):
    """What was pushed and what the development had not pushed touch the same lines."""

    def __init__(self, files: list[str]) -> None:
        super().__init__("the pull conflicts in: " + ", ".join(files))
        self.files = files


class BuilderLost(Exception):
    """The machine a build was sent to went away and did not come back in time. Not a
    failed build -- nothing was learnt about the code -- so it spends no attempt: the
    development goes back to waiting for a builder (T14.3)."""


class BriefIsRunning(ValueError):
    """The analysis (or an intake round) is working; a second one would race it."""

    def __init__(self, project_id: str) -> None:
        super().__init__(f"project {project_id} is already being analysed")
        self.project_id = project_id


class EmptyApproval(ValueError):
    """A gate whose material is empty cannot be approved (nothing would happen next)."""


class UnknownScreen(ValueError):
    """A screen id that is not in this development's design."""

    def __init__(self, screen_id: str) -> None:
        super().__init__(f"no screen {screen_id} in this design")
        self.screen_id = screen_id


class InvalidEdit(ValueError):
    """A human edit at a gate does not pass the same checks as the agent's output."""


#: How much of a call's answer the job keeps, for the page that follows it as it runs.
OUTPUT_KEPT = 1500
SUMMARY_KEPT = 400


def _clip(text: object, limit: int) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _env_int(name: str, default: int) -> int:
    """A whole number from the environment, or ``default`` when it is unset or not one."""
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _renumbered(before: list[dict[str, Any]], after: list[Any]) -> list[Any]:
    """A person's edit of the plan with each `depends_on` following its phases to where
    they now stand. The page sends the phases as they are to be, reordered, with the numbers
    they depended on still those of the old order; a phase is recognised by its task and
    goal. A number that names no phase of the old plan is left for the check to refuse."""

    def key(p: Any) -> tuple[str, str] | None:
        if not isinstance(p, dict):
            return None
        return (str(p.get("task_id")), str(p.get("goal")))

    old = {i: key(p) for i, p in enumerate(before, start=1)}
    new = {key(p): i for i, p in enumerate(after, start=1) if key(p) is not None}
    out: list[Any] = []
    for p in after:
        deps = p.get("depends_on") if isinstance(p, dict) else None
        if isinstance(deps, list):
            moved = [new.get(old.get(d)) if isinstance(d, int) else None for d in deps]
            p = {
                **p,
                "depends_on": [m if m is not None else d for m, d in zip(moved, deps, strict=True)],
            }
        out.append(p)
    return out


def _plan_problem(
    kept: list[PlanPhase], new: list[PlanPhase], task_ids: list[str]
) -> dict[str, int] | str:
    """The task map of a plan the Architect wrote, or why it cannot be built from: a task
    with no phase, or phases whose `depends_on` cannot be followed (T16.2)."""
    phases = [*kept, *new]
    mapping = architect.phase_task_map(phases, task_ids)
    if isinstance(mapping, str):
        return mapping
    return architect.dependency_problem(phases, built=len(kept)) or mapping


class Engine:
    def __init__(
        self,
        store: JobStore,
        workspace: Workspace,
        *,
        seed_profile: Profile,
        provider: ModelProvider | None = None,
        runner: Runner | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_reject_rounds: int = 3,
        max_build_attempts: int = 3,
        max_ci_attempts: int = 3,
        max_review_rounds: int = 2,
        max_qa_gate_fixes: int = 2,
        max_phase_parts: int = 4,
        review: str | None = None,
        supervisor_mode: str | None = None,
        retry_backoff_s: float = 2.0,
        gate_timeout_s: float | None = None,
        git_host: GitHost | None = None,
        ci_poll_s: float = 15.0,
        ci_timeout_s: float = 3600.0,
        repos_root: Path | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.store = store
        self.workspace = workspace
        # clones of remote repositories live next to the worktrees
        self.repos_root = repos_root or workspace.worktrees_root.parent / "repos"
        self.test_runs_root = workspace.worktrees_root.parent / "test-runs"
        self.standards_dir = GLOBAL_DIR
        # where the UI looks for local checkouts to register (None: type a path)
        self.local_repos_root: Path | None = None
        # what the checkouts are called on the person's own machine (Docker: /work is a
        # volume the host sees under another name); empty means they are already there
        self.host_paths = HostPaths()
        # Where each account's ChatGPT sign-in (the Codex CLI's home) is kept. None switches
        # the subscription provider off, which is what a hosted installation is: strangers'
        # plans must not be spent on a shared machine. Under the state directory, never
        # the work directory, so a job's commands cannot find a session by relative path.
        self.codex_root: Path | None = None
        # the sign-ins in progress; one object, shared by every per-account copy, because a
        # sign-in outlives the request that started it
        self.codex_logins = Logins()
        self._standards_index: StandardsIndex | None = None
        self._standards_editor: StandardsEditor | None = None
        self.orchestrator = Orchestrator(store)
        self.seed_profile = seed_profile
        self._provider = provider
        # kept so `for_user` can hand an injected provider (tests, --provider
        # scripted) to every per-account view instead of building a router
        self._injected_provider = provider
        # where a project's own commands run: on this machine, or in a container of
        # their own. A hosted installation must set SLIPWRIGHT_RUNNER=docker.
        self.runner: Runner = runner or build_runner()
        # what one account may take of a shared machine; zeroes mean no limit, which
        # is what a single-team installation wants
        self.quotas = Quotas(self.raw_store, workspace.worktrees_root, self.repos_root)
        # a new account starts with one finished development to read; an installation
        # that would rather people began from nothing sets SLIPWRIGHT_DEMO_PROJECT=0
        self.demo_project = os.environ.get("SLIPWRIGHT_DEMO_PROJECT", "").strip().lower() not in (
            "0",
            "off",
            "no",
            "false",
        )
        self.timeout_s = timeout_s
        self.max_reject_rounds = max_reject_rounds
        self.max_build_attempts = max_build_attempts
        self.max_ci_attempts = max_ci_attempts
        self.max_review_rounds = max_review_rounds
        # how often QA may call the failing test itself wrong on one phase, so a test
        # and the code it tests cannot rewrite each other in circles
        self.max_qa_gate_fixes = max_qa_gate_fixes
        self.max_phase_parts = max_phase_parts  # answers one phase may take (T9.7 follow-up)
        # a forced standards-review mode (off/advisory/blocking); None follows the project
        self.review_override = review
        # a forced gate mode (manual/assisted/auto); None follows the project
        self.supervisor_override = supervisor_mode
        # first retry waits this long, then doubles (T9.7); tests set it to 0
        self.retry_backoff_s = retry_backoff_s
        self.gate_timeout_s = gate_timeout_s
        # how often a build sent to a Mac is looked in on; tests make it quick
        self.worker_poll_s = 1.0
        # whether this installation moves accounts to and from others on its network
        # (slipwright/transfer); build_engine turns it off for a hosted one
        self.transfer_enabled = True
        self._git_host = git_host
        # tests answer GitHub/Jira HTTP locally through a mock transport
        self.http_transport = http_transport
        self.ci_poll_s = ci_poll_s
        self.ci_timeout_s = ci_timeout_s
        self.handlers: dict[JobState, Handler] = {
            JobState.BACKLOG: self._backlog,
            JobState.ARCHITECTURE: self._architecture,
            JobState.DESIGN: self._design,
            JobState.DEVELOPING: self._develop,
            JobState.BUILD_GATE: self._build_gate,
            JobState.REVIEW: self._review,
            JobState.QA: self._qa,
            JobState.DEVOPS: self._devops,
            JobState.RECONCILE: self._reconcile,
        }
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        #: Developments somebody has asked to stop or pause. A running one cannot be
        #: interrupted mid-call -- the model is already answering and the answer is
        #: already paid for -- so the run loop reads this between steps and stops before
        #: the next one.
        self._stopping: dict[str, _Halt] = {}
        # answers being written ahead of their phase's turn (T16.3), by job and phase
        # number. Held here, not on the job: a thread never writes the job, the run loop
        # takes what is ready when the phase comes up
        self._ahead: dict[str, dict[int, Future[RoleResult]]] = {}
        self._ahead_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ahead")
        #: Model calls one account makes at once on one provider, across all its
        #: developments (SLIPWRIGHT_MAX_CALLS_PER_PROVIDER, 0 = no limit). Answers written
        #: side by side multiply the calls on one key, and a provider answers too many at
        #: once with rate-limit errors that cost a retry each -- or, on a subscription,
        #: with the plan's limit for the rest of the day.
        self.max_calls_per_provider = _env_int("SLIPWRIGHT_MAX_CALLS_PER_PROVIDER", 4)
        self._provider_slots: dict[str, threading.BoundedSemaphore] = {}
        self._provider_slots_lock = threading.Lock()
        # one analysis or intake round at a time per project (T11.2)
        self._brief_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        # one test run at a time per checkout, so runs never trample each other's files
        self._checkout_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        # one standards reindex at a time: two jobs starting together both found the
        # index stale, both rebuilt it, and the second insert of the same section failed
        # its UNIQUE constraint and took that job's phase down with it
        self._reindex_lock = threading.RLock()
        # ports held by jobs that outlived a previous process must stay taken
        self.workspace.reserve_ports(store.list())

    @property
    def events(self) -> EventBus:
        return self.store.events

    @property
    def provider(self) -> ModelProvider:
        """The injected provider (tests, ``--provider scripted``), else a router that picks
        a vendor per role from the profile and credentials from settings or environment."""
        if self._provider is None:
            self._provider = RoutingProvider(
                self.provider_credentials,
                default=self.default_provider_name,
                default_model=self.default_model_for,
                role_routing=self.agent_routing,
                transport=self.http_transport,
            )
        return self._provider

    def for_user(self, user_id: str | None) -> Engine:
        """The same engine, reading and writing one account's settings.

        Everything is shared -- the store, the workspace, the locks, the event bus --
        except what depends on whose keys are in play: the router is rebuilt so it
        resolves credentials for this person, and an injected provider (tests,
        ``--provider scripted``) is left exactly as it is.

        ``None`` means the installation's own settings, which is what a local install,
        the CLI and a job created before accounts existed all want.
        """
        if user_id is None and not isinstance(self.store, ScopedStore):
            return self
        if isinstance(self.store, ScopedStore) and self.store.scoped_to == (user_id or ""):
            return self
        mine = copy.copy(self)
        mine.store = ScopedStore(self.raw_store, user_id)  # type: ignore[assignment]
        # an injected provider belongs to the test or the script that supplied it and has
        # no credentials to resolve; only the router is per-account
        mine._provider = self._injected_provider
        return mine

    @property
    def raw_store(self) -> JobStore:
        """The store underneath, whatever account this engine is bound to."""
        store = self.store
        return store._store if isinstance(store, ScopedStore) else store  # noqa: SLF001

    def provider_for(self, user_id: str | None) -> ModelProvider:
        """The router that spends this account's keys."""
        return self.for_user(user_id).provider

    # -- model providers -------------------------------------------------------------------

    def default_provider_name(self) -> str:
        name = self.store.get_setting("providers.default")
        return str(name) if name in PROVIDERS else DEFAULT_PROVIDER

    def default_model_for(self, name: str) -> str | None:
        """The model roles without a provider of their own run on, for ``name``; unset
        means the role's profile model is used as written."""
        data: dict[str, Any] = self.store.get_setting(f"providers.{name}", {}) or {}
        model = data.get("default_model")
        return str(model) if model else None

    def effective_routing(self, cfg: RoleConfig, role: RoleName | None = None) -> tuple[str, str]:
        """(provider, model) a role actually runs on right now: its assignment under
        Agents, else the profile's provider, else the default provider and its model.

        The model is empty when the default provider has none chosen and the profile's
        is another vendor's (``model_on_default``): what is shown and priced is then
        "no model", which is the truth, rather than a Claude name nobody will call."""
        assigned = self.agent_routing(role.value) if role is not None else None
        if assigned is not None:
            return assigned
        if cfg.provider:
            return cfg.provider, cfg.model
        name = self.default_provider_name()
        return name, model_on_default(name, self.default_model_for(name), cfg.model) or ""

    def default_model_missing(self, name: str | None = None) -> bool:
        """Whether an agent that follows the default -- or ``name``, were it the default --
        would stop for want of a model. A provider nobody can call yet is not missing a
        model; it is missing a key, and says so itself."""
        name = name or self.default_provider_name()
        if self.provider_credentials(name) is None:
            return False
        return model_on_default(name, self.default_model_for(name), "") is None

    # -- agent assignments -----------------------------------------------------------------

    def agent_routing(self, role: str) -> tuple[str, str] | None:
        """The (provider, model) an agent was assigned under Agents; None when it follows
        the profile. Applies to every project, whatever the project's profile says."""
        data: dict[str, Any] = self.store.get_setting(f"agents.{role}", {}) or {}
        provider, model = data.get("provider"), data.get("model")
        if not provider or not model or provider not in PROVIDERS:
            return None
        return str(provider), str(model)

    def assign_agent(self, role: RoleName, provider: str | None, model: str | None) -> None:
        """Pin an agent to a provider and model, or clear the pin when both are empty. A
        provider without a key is refused here rather than failing every job later."""
        provider, model = (provider or "").strip(), (model or "").strip()
        if not provider and not model:
            self.store.delete_setting(f"agents.{role.value}")
            return
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider!r}")
        if not model:
            raise ValueError(f"pick a model for {PROVIDERS[provider].label}")
        if self.provider_credentials(provider) is None:
            spec = PROVIDERS[provider]
            raise ProviderUnavailableError(
                f"no API key for {spec.label}: add one under Settings → Models "
                f"or set {spec.env_var}"
            )
        self.store.set_setting(f"agents.{role.value}", {"provider": provider, "model": model})

    def codex_home(self) -> Path | None:
        """This account's own Codex sign-in directory; None when the feature is off."""
        if self.codex_root is None:
            return None
        who = self.store.scoped_to if isinstance(self.store, ScopedStore) else ""
        return self.codex_root / (who or "installation")

    def provider_credentials(self, name: str) -> Credentials | None:
        """Stored key first, else the vendor's environment variable; None when neither."""
        spec = PROVIDERS.get(name)
        if spec is None:
            return None
        if name == CHATGPT:
            home = self.codex_home()
            if home is None or not (home / "auth.json").is_file():
                return None
            return Credentials(name=name, api_key="", base_url="", home=str(home))
        data: dict[str, Any] = self.store.get_setting(f"providers.{name}", {}) or {}
        key = self.store.get_setting(f"providers.{name}.api_key") or os.environ.get(spec.env_var)
        if not key:
            return None
        return Credentials(
            name=name,
            api_key=str(key),
            base_url=data.get("base_url") or spec.default_base_url,
            max_tokens=int(data["max_tokens"]) if data.get("max_tokens") else None,
        )

    def provider_settings(self) -> list[dict[str, Any]]:
        default = self.default_provider_name()
        out: list[dict[str, Any]] = []
        for spec in PROVIDERS.values():
            if spec.name == CHATGPT and self.codex_home() is None:
                continue  # switched off here: not offered at all
            data: dict[str, Any] = self.store.get_setting(f"providers.{spec.name}", {}) or {}
            stored = self.store.get_setting(f"providers.{spec.name}.api_key")
            env = os.environ.get(spec.env_var) if spec.env_var else None
            key = stored or env
            if spec.kind == "subscription":
                # no key: "set" means signed in, and the hint says with what
                key = "ChatGPT" if self.provider_credentials(spec.name) else None
            out.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "env_var": spec.env_var,
                    "docs_url": spec.docs_url,
                    "default_base_url": spec.default_base_url,
                    "base_url": data.get("base_url"),
                    "key_set": bool(key),
                    "key_hint": (
                        (key if spec.kind == "subscription" else f"…{str(key)[-4:]}")
                        if key
                        else None
                    ),
                    "key_from_env": bool(env) and not stored,
                    "is_default": spec.name == default,
                    "needs_model": self.default_model_missing(spec.name),
                    "default_model": data.get("default_model"),
                    "max_tokens": data.get("max_tokens"),
                    "default_max_tokens": spec.max_tokens,
                    "kind": spec.kind,
                    "has_terms": spec.has_terms,
                }
            )
        return out

    def update_provider_settings(
        self,
        name: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        clear_key: bool = False,
        make_default: bool = False,
        default_model: str | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if name not in PROVIDERS:
            raise KeyError(name)
        data: dict[str, Any] = self.store.get_setting(f"providers.{name}", {}) or {}
        if base_url is not None:
            data["base_url"] = base_url.strip().rstrip("/") or None
        if default_model is not None:
            data["default_model"] = default_model.strip() or None
        if max_tokens is not None:
            data["max_tokens"] = max_tokens or None  # 0 clears: back to the vendor default
        self.store.set_setting(f"providers.{name}", data)
        if clear_key:
            self.store.delete_setting(f"providers.{name}.api_key")
        elif api_key is not None and api_key.strip():
            self.store.set_setting(f"providers.{name}.api_key", api_key.strip(), secret=True)
        # A default without a model is allowed: the models are listed from the key, so the
        # key is saved before one can be picked. What is refused is *running* on it
        # (``model_on_default``), and the Models page says so in the meantime.
        if make_default:
            self.store.set_setting("providers.default", name)
        else:
            self.adopt_as_default(name)
        # a changed key or URL must not keep serving from a stale cached client
        if isinstance(self._provider, RoutingProvider):
            self._provider = None

    def adopt_as_default(self, name: str) -> bool:
        """The first provider that can actually answer becomes the default.

        Anthropic is the default before anybody has connected anything, which is a fine
        starting point and a trap the moment somebody connects something else: they sign
        in with a ChatGPT plan, the page says so, and every agent still goes to Anthropic
        and fails with "no API key". Nobody thinks of "default" as a separate decision
        they have to make, because until they have two providers it is not one.

        Only ever while nothing works: once a default can answer, changing it is the
        person's business and the Models page has a button for it.
        """
        if self.provider_credentials(name) is None:
            return False
        if self.provider_credentials(self.default_provider_name()) is not None:
            return False
        self.store.set_setting("providers.default", name)
        log.info("nothing else was connected, so %s is now the default provider", name)
        return True

    def provider_models(self, name: str) -> list[str]:
        creds = self.provider_credentials(name)
        if creds is None:
            spec = PROVIDERS[name]
            raise ProviderUnavailableError(f"no API key for {spec.label}; set it or {spec.env_var}")
        return list_models(creds, transport=self.http_transport)

    def provider_terms(self, name: str) -> Terms:
        """Where this account's key stands with a vendor's terms of use (EVREN's)."""
        return self._terms_client(name).terms()

    def accept_provider_terms(self, name: str, version: int) -> Terms:
        """Accept the version the person was shown. Only ever on their press: see
        ``providers/evren.py`` for why Slipwright never does this by itself."""
        return self._terms_client(name).accept_terms(version)

    def _terms_client(self, name: str) -> EvrenProvider:
        creds = self.provider_credentials(name)
        if creds is None:
            spec = PROVIDERS[name]
            raise ProviderUnavailableError(f"no API key for {spec.label}; set it or {spec.env_var}")
        client = build_client(creds, transport=self.http_transport)
        if not isinstance(client, EvrenProvider):
            raise KeyError(name)
        return client

    @property
    def git_host(self) -> GitHost:
        if self._git_host is None:
            from slipwright.githost import GhHost

            self._git_host = GhHost(token=self.github_token)
        return self._git_host

    # -- GitHub connection -----------------------------------------------------------------

    def github_token(self) -> str | None:
        return self.source_token(GITHUB)

    # -- source hosts (GitHub, Bitbucket, ...) ---------------------------------------------

    def source_settings(self) -> list[SourceSettings]:
        """One row per known host, in registry order, with the default first-class."""
        self._migrate_github_settings()
        default = self.default_source()
        rows: list[SourceSettings] = []
        for name, spec in SOURCES.items():
            data: dict[str, Any] = self.store.get_setting(f"sources.{name}", {}) or {}
            token = self.source_token(name)
            stored = self.store.get_setting(f"sources.{name}.token")
            rows.append(
                SourceSettings(
                    name=name,
                    label=spec.label,
                    token_label=spec.token_label,
                    token_docs_url=spec.token_docs_url,
                    owner_label=spec.owner_label,
                    default_api_url=spec.default_api_url,
                    api_url=data.get("api_url") or None,
                    env_var=spec.env_var,
                    owner=data.get("owner"),
                    base_branch=data.get("base_branch") or "main",
                    token_set=token is not None,
                    token_hint=f"…{token[-4:]}" if token else None,
                    token_from_env=token is not None and not stored,
                    is_default=name == default,
                )
            )
        return rows

    def default_source(self) -> str:
        name = self.store.get_setting("sources.default")
        return str(name) if name in SOURCES else GITHUB

    def source_token(self, name: str) -> str | None:
        """The stored token, else the host's environment variable."""
        self._migrate_github_settings()
        stored = self.store.get_setting(f"sources.{name}.token")
        if stored:
            return str(stored)
        spec = SOURCES.get(name)
        env = os.environ.get(spec.env_var) if spec else None
        return env or None

    def source_credentials(self, name: str) -> SourceCredentials | None:
        token = self.source_token(name)
        if token is None or name not in SOURCES:
            return None
        data: dict[str, Any] = self.store.get_setting(f"sources.{name}", {}) or {}
        return SourceCredentials(
            name=name,
            token=token,
            api_url=data.get("api_url") or SOURCES[name].default_api_url,
            owner=data.get("owner") or None,
        )

    def update_source_settings(
        self,
        name: str,
        *,
        token: str | None = None,
        owner: str | None = None,
        base_branch: str | None = None,
        api_url: str | None = None,
        clear_token: bool = False,
        make_default: bool = False,
    ) -> list[SourceSettings]:
        """Change what is given; an omitted token keeps the stored one."""
        if name not in SOURCES:
            raise ValueError(f"unknown source: {name!r}")
        self._migrate_github_settings()
        current: dict[str, Any] = self.store.get_setting(f"sources.{name}", {}) or {}
        if owner is not None:
            current["owner"] = owner.strip() or None
        if base_branch is not None:
            current["base_branch"] = base_branch.strip() or "main"
        if api_url is not None:
            current["api_url"] = api_url.strip() or None
        self.store.set_setting(f"sources.{name}", current)
        if clear_token:
            self.store.delete_setting(f"sources.{name}.token")
        elif token is not None and token.strip():
            self.store.set_setting(f"sources.{name}.token", token.strip(), secret=True)
        if make_default:
            self.store.set_setting("sources.default", name)
        return self.source_settings()

    def source_host(self, name: str | None = None, *, base_branch: str | None = None) -> SourceHost:
        """A client for the named host (the default when unnamed). Raises when it has no
        token: a job must fail with that reason rather than half-way through a push."""
        chosen = name or self.default_source()
        creds = self.source_credentials(chosen)
        if creds is None:
            spec = SOURCES.get(chosen)
            label = spec.label if spec else chosen
            env = spec.env_var if spec else "?"
            raise SourceError(
                f"no token for {label}: add one under Settings → Sources or set {env}"
            )
        rows = {r.name: r for r in self.source_settings()}
        branch = base_branch or rows[chosen].base_branch
        return build_host(creds, transport=self.http_transport, base_branch=branch)

    def base_branch_of(self, project: Project | None) -> str:
        """The branch this project's work is merged back into.

        Read from the source the project actually names, through its owner. It used to be
        GitHub's setting whatever the project was on, so a Bitbucket project whose trunk
        is called something else was told to merge into a branch that does not exist.
        """
        mine = self.for_user(project.owner_id if project else None)
        rows = {r.name: r for r in mine.source_settings()}
        row = rows.get(project.source if project else mine.default_source())
        return (row.base_branch if row else "") or "main"

    def host_for(self, project: Project | None) -> SourceHost:
        """The host a project belongs to; the default for a project that names none.

        Resolved through the project's owner, because the token that pushes the branch
        and opens the pull request is theirs.
        """
        if self._git_host is not None:
            # injected (tests, or a single-host deployment): it answers push/open_pr/
            # ci_status, which is all a running job asks of a host
            return cast(SourceHost, self._git_host)
        mine = self.for_user(project.owner_id if project else None)
        return mine.source_host(project.source if project else None)

    def _host_of(self, job: Job) -> SourceHost:
        return self.host_for(self._project_of(job))

    def _push(self, job: Job, worktree: Path, what: str) -> None:
        """Put what was just committed on the project's own repository (T16.1).

        Everything was committed step by step and pushed only when DevOps opened the pull
        request at the end: fourteen hours of an Android app, and the repository had none of
        it -- nothing to follow, review or rescue. A push that fails never stops the
        development: it is noted, and the next one carries it. A checkout with nowhere to
        push is the ordinary local case and says nothing. The first push opens the pull
        request as a draft where the host can; DevOps finishes it.
        """
        if not g.has_remote(worktree):
            return
        try:
            host = self._host_of(job)
            host.push(worktree, job.branch)
        except NoRemote:
            return
        # whatever went wrong -- the host refused, its tool is not installed (`gh` missing
        # is a FileNotFoundError, not a host error) -- the work is committed and carries on
        except Exception as exc:  # noqa: BLE001
            self._record_gate_note(job, f"{what}: committed, not pushed", str(exc))
            return
        if job.data.pr_url or job.data.draft_pr_url:
            return
        draft = getattr(host, "open_draft", None)
        if draft is None:
            return  # a host with no draft pull request: DevOps opens it, as before
        title = (job.title or job.request).strip().splitlines()[0][:120]
        body = (
            f"{job.request}\n\n"
            "_Opened as a draft by Slipwright while the development is built; the "
            "description is written when it is done._"
        )
        try:
            job.data.draft_pr_url = str(draft(worktree, job.branch, title, body))
        except Exception as exc:  # noqa: BLE001 -- as above: a draft never stops the work
            self._record_gate_note(job, "draft pull request not opened", str(exc))
            return
        self.store.save(job)
        self._record_gate_note(job, f"draft pull request: {job.data.draft_pr_url}", None)

    def _commit_message(self, job: Job, index: int, goal: str) -> str:
        """The phase, its task and the task's Jira key: what the host's history shows."""
        phases = (job.data.plan or {}).get("phases", [])
        task = phases[index].get("task_id") if index < len(phases) else None
        key = job.data.jira_keys.get(str(task)) if task else None
        head = goal.strip().splitlines()[0] if goal.strip() else f"phase {index + 1}"
        suffix = f" [{key}]" if key else ""
        return f"slipwright: phase {index + 1}/{len(phases)}: {head}{suffix}"

    def _migrate_github_settings(self) -> None:
        """Settings written before the sources page keep working: github.* moves under
        sources.github once, and the old keys are left alone in case of a rollback."""
        if self.store.get_setting("sources.migrated"):
            return
        old: dict[str, Any] = self.store.get_setting("github", {}) or {}
        if old:
            current: dict[str, Any] = self.store.get_setting("sources.github", {}) or {}
            for key in ("owner", "base_branch"):
                if old.get(key) and not current.get(key):
                    current[key] = old[key]
            self.store.set_setting("sources.github", current)
        token = self.store.get_setting("github.token")
        if token and not self.store.get_setting("sources.github.token"):
            self.store.set_setting("sources.github.token", token, secret=True)
        self.store.set_setting("sources.migrated", True)

    def github_settings(self) -> GitHubSettings:
        data: dict[str, Any] = self.store.get_setting("sources.github", {}) or {}
        token = self.github_token()
        return GitHubSettings(
            owner=data.get("owner"),
            base_branch=data.get("base_branch") or "main",
            token_set=token is not None,
            token_hint=f"…{token[-4:]}" if token else None,
        )

    def update_github_settings(
        self,
        *,
        token: str | None = None,
        owner: str | None = None,
        base_branch: str | None = None,
        clear_token: bool = False,
    ) -> GitHubSettings:
        """Change what is given; an omitted token keeps the stored one. The GitHub page
        is the sources page's older door: both write the same settings."""
        self.update_source_settings(
            GITHUB, token=token, owner=owner, base_branch=base_branch, clear_token=clear_token
        )
        return self.github_settings()

    def github_client(self) -> GitHubClient:
        token = self.github_token()
        if token is None:
            raise GitHubError("no GitHub token configured")
        return GitHubClient(token, transport=self.http_transport)

    # -- Jira connection -------------------------------------------------------------------

    # -- email (installation-wide: one sender for everybody) --------------------------------

    def mail_settings(self) -> MailSettings:
        data: dict[str, Any] = self.store.get_setting("mail", {}) or {}
        return MailSettings(
            transport=str(data.get("transport") or "outbox"),
            host=str(data.get("host") or ""),
            port=int(data.get("port") or 587),
            username=str(data.get("username") or ""),
            security=str(data.get("security") or "starttls"),
            from_address=str(data.get("from_address") or ""),
            from_name=str(data.get("from_name") or "Slipwright"),
            base_url=str(data.get("base_url") or ""),
            support_email=str(data.get("support_email") or ""),
        )

    def update_mail_settings(self, **changes: Any) -> MailSettings:
        data: dict[str, Any] = self.store.get_setting("mail", {}) or {}
        password = changes.pop("password", None)
        for key, value in changes.items():
            if value is not None:
                data[key] = value
        self.store.set_setting("mail", data)
        if password is not None:
            if password:
                self.store.set_setting("mail.password", password, secret=True)
            else:
                self.store.delete_setting("mail.password")
        return self.mail_settings()

    def mailer(self) -> Mailer:
        """The transport to use right now. An installation with no SMTP writes to the
        outbox instead of failing, so signing up works before mail is configured."""
        settings = self.mail_settings()
        if not settings.configured:
            return OutboxMailer(self.store)
        password = str(self.store.get_setting("mail.password") or "")
        return SmtpMailer(settings, password)

    def accounts(self) -> Accounts:
        return Accounts(
            self.raw_store,
            self.mailer(),
            self.mail_settings(),
            demo_project=self.demo_project,
        )

    def teams(self) -> Teams:
        """Invitations, acceptance and being taken off an agent."""
        return Teams(self.raw_store, self.mailer(), self.mail_settings())

    def support(self) -> SupportDesk:
        """The support desk, on the same transport as the rest of the mail."""
        return SupportDesk(self.store, self.mailer(), self.mail_settings())

    # -- jira ------------------------------------------------------------------------------

    def jira_settings(self) -> JiraSettings:
        data: dict[str, Any] = self.store.get_setting("jira", {}) or {}
        token = self.store.get_setting("jira.token")
        agent_token = self.store.get_setting("jira.agent_token")
        return JiraSettings(
            site_url=data.get("site_url"),
            email=data.get("email"),
            token_set=bool(token),
            token_hint=f"…{str(token)[-4:]}" if token else None,
            issue_types={**DEFAULT_ISSUE_TYPES, **(data.get("issue_types") or {})},
            agent_email=data.get("agent_email"),
            agent_token_set=bool(agent_token),
            agent_token_hint=f"…{str(agent_token)[-4:]}" if agent_token else None,
        )

    def update_jira_settings(
        self,
        *,
        site_url: str | None = None,
        email: str | None = None,
        token: str | None = None,
        clear_token: bool = False,
        issue_types: dict[str, str] | None = None,
        agent_email: str | None = None,
        agent_token: str | None = None,
        clear_agent_token: bool = False,
    ) -> JiraSettings:
        """Change what is given; omitted tokens keep their stored values."""
        current: dict[str, Any] = self.store.get_setting("jira", {}) or {}
        if site_url is not None:
            current["site_url"] = site_url.strip().rstrip("/") or None
        if email is not None:
            current["email"] = email.strip() or None
        if issue_types is not None:
            current["issue_types"] = {
                k: v.strip()
                for k, v in issue_types.items()
                if k in DEFAULT_ISSUE_TYPES and v.strip()
            }
        if agent_email is not None:
            current["agent_email"] = agent_email.strip() or None
        self.store.set_setting("jira", current)
        if clear_token:
            self.store.delete_setting("jira.token")
        elif token is not None and token.strip():
            self.store.set_setting("jira.token", token.strip(), secret=True)
        if clear_agent_token:
            self.store.delete_setting("jira.agent_token")
        elif agent_token is not None and agent_token.strip():
            self.store.set_setting("jira.agent_token", agent_token.strip(), secret=True)
        return self.jira_settings()

    def jira_client(self, *, agent: bool = False) -> JiraClient:
        """The human connection, or with ``agent=True`` the agent account when one is set
        (falling back to the human connection otherwise)."""
        settings = self.jira_settings()
        site = settings.site_url or ""
        if agent and settings.agent_email and settings.agent_token_set:
            return JiraClient(
                site,
                settings.agent_email,
                str(self.store.get_setting("jira.agent_token")),
                transport=self.http_transport,
            )
        if not settings.configured:
            raise JiraError("Jira is not configured (site URL, e-mail and token are needed)")
        return JiraClient(
            site,
            settings.email or "",
            str(self.store.get_setting("jira.token")),
            transport=self.http_transport,
        )

    def _project_of(self, job: Job) -> Project | None:
        if job.project_id is None:
            return None
        try:
            return self.store.get_project(job.project_id)
        except ProjectNotFound:
            return None

    def _source_of(self, job: Job) -> str:
        """Which host this job's project lives on; the account's default when it has no
        project of its own (the CLI, a job older than projects)."""
        project = self._project_of(job)
        if project is not None:
            return project.source
        return self.for_user(job.owner_id).default_source()

    def _agent_jira_client(self, owner_id: str | None = None) -> JiraClient | None:
        try:
            return self.for_user(owner_id).jira_client(agent=True)
        except JiraError:
            return None

    def _apply_jira_actions(
        self, job: Job, role: RoleName, profile: Profile, project: Project, actions: list[Any]
    ) -> None:
        """Run a role's ``jira_actions`` (permission and confinement checked by the runner)
        and record every outcome, executed or refused, in the job's history."""
        if not actions:
            return
        client = self._agent_jira_client(job.owner_id) if project.jira_project_key else None
        runner = ActionRunner(client, project)
        outcomes = runner.run(job, role, profile, list(actions))
        self._record_jira_outcomes(job, role, outcomes)

    def _retry_jira_queue(self, job: Job) -> Job:
        if not job.data.jira_queue:
            return job
        project = self._project_of(job)
        if project is None:
            return job
        client = self._agent_jira_client(job.owner_id)
        if client is None:
            return job
        outcomes = ActionRunner(client, project).retry_queued(job)
        self._record_jira_outcomes(job, None, outcomes)
        return self.store.get(job.id)

    def _record_jira_outcomes(
        self, job: Job, role: RoleName | None, outcomes: list[ActionOutcome]
    ) -> None:
        if not outcomes:
            return
        self.store.save(job)
        done = sum(1 for o in outcomes if o.status == "done")
        refused = sum(1 for o in outcomes if o.status == "refused")
        queued = sum(1 for o in outcomes if o.status == "queued")
        parts = []
        if done:
            parts.append(f"{done} done")
        if refused:
            parts.append(f"{refused} refused")
        if queued:
            parts.append(f"{queued} queued")
        skipped = len(outcomes) - done - refused - queued
        if skipped:
            parts.append(f"{skipped} skipped")
        who = f" ({role.value})" if role else " (retry)"
        self.store.update_state(
            job.id,
            job.state,
            note=f"jira{who}: {', '.join(parts)}",
            detail="\n".join(o.line() for o in outcomes),
        )
        job.history = self.store.get(job.id).history

    # -- the platform's other language ------------------------------------------------------

    #: How many new strings one page load is allowed to translate. The rest arrive on the
    #: next poll, so opening a large project in the other language fills in rather than
    #: hanging on a single long request.
    max_translations_per_call = 120

    def translations(
        self,
        lang: str,
        *,
        project_id: str | None = None,
        job_id: str | None = None,
        owner_id: str | None = ANY_OWNER,
    ) -> dict[str, str]:
        """``{what an agent wrote: the same thing in ``lang``}`` for a project or one job.

        A development written in ``lang`` already reads correctly and contributes nothing.
        Everything else is served from the cache, and whatever is not cached yet is
        translated now and kept, so this is expensive once and free afterwards. It never
        raises: a provider that is down means missing entries, which the page renders as
        the source text."""
        if lang not in OTHER_LANGUAGE:
            return {}
        jobs = (
            [self.store.get(job_id, owner_id)]
            if job_id is not None
            else self.store.list(project_id=project_id, owner_id=owner_id)
        )
        by_source: dict[str, str] = {}  # source text -> the language it was written in
        for job in jobs:
            written = job.data.language
            if written == lang:
                continue
            for text in strings_of(job):
                by_source.setdefault(text, written)
        if not by_source:
            return {}
        out = self.store.translations(lang, list(by_source))
        missing = [t for t in by_source if t not in out][: self.max_translations_per_call]
        if not missing:
            return out
        profile = self.seed_profile
        payer = None if owner_id == ANY_OWNER else owner_id
        if project_id is not None:
            with contextlib.suppress(ProjectNotFound):
                project = self.store.get_project(project_id)
                profile = self.project_profile(project)
                # the project's prose is translated on the keys its agents wrote it with.
                # The endpoint passes no owner, and ``None`` is the installation's keys: a
                # hosted install has none, so every account read its agents untranslated
                payer = project.owner_id
        try:
            provider = self.provider_for(payer)
        except ProviderUnavailableError:
            return out
        for written in sorted({by_source[t] for t in missing}):
            batch = [t for t in missing if by_source[t] == written]
            fresh = translate(
                batch,
                source=written,
                target=lang,
                provider=provider,
                profile=profile,
                timeout_s=self.timeout_s,
            )
            if fresh:
                self.store.save_translations(lang, fresh)
                out.update(fresh)
        return out

    # -- standards (RAG) -------------------------------------------------------------------

    def standards_settings(self) -> dict[str, Any]:
        data: dict[str, Any] = self.store.get_setting("standards", {}) or {}
        return {
            "embedder": data.get("embedder") or "none",
            "embedding_model": data.get("embedding_model") or "text-embedding-3-small",
            "local_model": data.get("local_model") or "BAAI/bge-m3",
            "top_k": int(data.get("top_k") or 4),
            "token_budget": int(data.get("token_budget") or 2000),
        }

    def update_standards_settings(self, **changes: Any) -> dict[str, Any]:
        data: dict[str, Any] = self.store.get_setting("standards", {}) or {}
        for key, value in changes.items():
            if value is not None:
                data[key] = value
        self.store.set_setting("standards", data)
        self._standards_index = None  # rebuilt with the new embedder on next use
        return self.standards_settings()

    def _build_embedder(self) -> Embedder:
        settings = self.standards_settings()
        name = settings["embedder"]
        if name == "openai":
            creds = self.provider_credentials("openai")
            if creds is None:
                raise StandardsIndexError(
                    "openai embeddings need an OpenAI key (Settings → Models)"
                )
            return OpenAIEmbedder(
                creds.api_key,
                creds.base_url,
                settings["embedding_model"],
                transport=self.http_transport,
            )
        if name == "local":
            return LocalEmbedder(settings["local_model"])
        if name == "hashing":
            return HashingEmbedder()
        return NoEmbedder()

    @property
    def standards_index(self) -> StandardsIndex:
        """The retrieval index, in the installation's own database.

        It used to be a SQLite file of its own beside the job database. It is derived data
        -- rebuilt whenever the corpus fingerprint moves -- so it costs nothing to keep it
        with everything else, and a hosted installation has only one database to run.
        """
        if self._standards_index is None:
            self._standards_index = StandardsIndex(self.store.db, self._build_embedder())
        return self._standards_index

    @property
    def standards_editor(self) -> StandardsEditor:
        if self._standards_editor is None:
            self._standards_editor = StandardsEditor(
                self.standards_dir, self.workspace.worktrees_root.parent / "standards-branches"
            )
        return self._standards_editor

    def standards_repo_for(self, project_id: str | None) -> Path | None:
        """The project checkout whose overrides are edited, or None for the global corpus."""
        if project_id is None:
            return None
        project = self.store.get_project(project_id)
        if project.repo_path is None:
            raise ProjectNotFound(project_id)
        return project.repo_path

    def _standards_paths(self, project: Project | None) -> list[Path]:
        if project is None:
            return sorted(self.standards_dir.rglob("*.md")) if self.standards_dir.is_dir() else []
        if project.repo_path is None:
            return []
        override = project.repo_path / PROJECT_SUBDIR
        return sorted(override.rglob("*.md")) if override.is_dir() else []

    def reindex_standards(
        self,
        project_id: str | None = None,
        *,
        owner_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Index one layer: the shipped corpus, an account's rewritten pages, or a
        project's overrides. Skipped when nothing has changed since the last pass."""
        # the fingerprint is read under the lock, so whoever waited finds the work done
        with self._reindex_lock:
            return self._reindex_standards(project_id, owner_id=owner_id, force=force)

    def _reindex_standards(
        self, project_id: str | None, *, owner_id: str | None, force: bool
    ) -> dict[str, Any]:
        index = self.standards_index
        if owner_id is not None:
            return self._reindex_user_standards(index, owner_id, force=force)
        project = self.store.get_project(project_id) if project_id else None
        paths = self._standards_paths(project)
        stamp = corpus_fingerprint(paths) + ":" + index.embedder.name
        if not force and index.fingerprint(project_id) == stamp:
            return {"skipped": True, "chunks": 0}
        if project is None:
            pages = load_corpus(self.standards_dir)
        else:
            pages = [
                p
                for p in load_corpus(Path("/nonexistent"), project.repo_path)
                if p.scope == "project"
            ]
        result = index.reindex(pages, project_id=project_id)
        index.set_fingerprint(project_id, stamp)
        return {"skipped": False, **result}

    def _reindex_user_standards(
        self, index: StandardsIndex, owner_id: str, *, force: bool = False
    ) -> dict[str, Any]:
        """The pages this account rewrote. They live in the database, not on disk, so the
        fingerprint is over the rows rather than over file mtimes."""
        store = self.raw_store
        stamp = store.pages_fingerprint(owner_id) + ":" + index.embedder.name
        key = f"user:{owner_id}"
        if not force and index.fingerprint(key) == stamp:
            return {"skipped": True, "chunks": 0}
        pages = [
            page_from_text(row["domain"], row["name"], row["body"])
            for row in store.user_pages(owner_id)
        ]
        result = index.reindex(pages, owner_id=owner_id)
        index.set_fingerprint(key, stamp)
        return {"skipped": False, **result}

    def ensure_standards_indexed(
        self, project_id: str | None = None, owner_id: str | None = None
    ) -> None:
        """Cheap change check, then an incremental reindex of whatever moved."""
        try:
            self.reindex_standards(None)
            if owner_id is not None:
                self.reindex_standards(owner_id=owner_id)
            if project_id is not None:
                self.reindex_standards(project_id)
        except StandardsIndexError as exc:
            log.warning("standards index unavailable: %s", exc)

    def search_standards(
        self,
        query: str,
        domain: str | None,
        *,
        project_id: str | None = None,
        owner_id: str | None = None,
        k: int | None = None,
    ) -> list[Hit]:
        self.ensure_standards_indexed(project_id, owner_id)
        return self.standards_index.search(
            query,
            domain,
            k=k or self.standards_settings()["top_k"],
            project_id=project_id,
            owner_id=owner_id,
        )

    def standards_for(self, job: Job, role: RoleName, profile: Profile) -> Retrieval | None:
        """The standards a role reads for this call: ``core`` plus its domain's best
        sections under the role's budget. ``None`` when the index is unavailable — the
        role then runs without standards rather than not at all."""
        project = self._project_of(job)
        settings = self.standards_settings()
        config = profile.roles.get(role)
        budget = settings["token_budget"]
        if config is not None and config.standards_budget is not None:
            budget = config.standards_budget
        # the rules this agent works to are its owner's: the shipped pages, whatever
        # that account rewrote, and finally the project's own overrides
        owner_id = job.owner_id
        try:
            self.ensure_standards_indexed(project.id if project else None, owner_id)
            index = self.standards_index
        except StandardsIndexError as exc:
            log.warning("standards unavailable for %s: %s", role.value, exc)
            return None
        project_id = project.id if project else None

        def search(query: str, domain: str | None, k: int) -> list[Hit]:
            return index.search(query, domain, k=k, project_id=project_id, owner_id=owner_id)

        def browse(domain: str | None, k: int) -> list[Hit]:
            return index.browse(domain, k=k, project_id=project_id, owner_id=owner_id)

        core = core_text(self.standards_dir, project.repo_path if project else None)
        return retrieve(
            search,
            job,
            role,
            core=core,
            budget=budget,
            top_k=int(settings["top_k"]),
            browse=browse,
        )

    def _jira_sync_for(self, job: Job) -> JiraSync | None:
        if job.project_id is None:
            return None
        try:
            project = self.store.get_project(job.project_id)
        except ProjectNotFound:
            return None
        if not project.jira_project_key:
            return None
        # the owner's connection, not the server's: on a hosted installation the Jira
        # site, the account and the token all belong to whoever owns the project
        mine = self.for_user(job.owner_id)
        settings = mine.jira_settings()
        if not settings.configured:
            return None
        return JiraSync(mine.jira_client(), project, settings.issue_types)

    def _jira_reconcile(self, job: Job) -> Job:
        """Mirror the job into Jira (no-op unless the project is linked and Jira is set up).
        Never raises: a Jira outage is recorded on the job and retried next time."""
        job = self._retry_jira_queue(job)
        try:
            sync = self._jira_sync_for(job)
        except JiraError as exc:
            log.warning("job %s: jira unavailable: %s", job.id, exc)
            return job
        if sync is None:
            return job
        report = sync.reconcile(job)
        if not report.changed and report.error is None:
            return job
        job = self.store.save(job)
        if report.error is not None:
            note = "jira: sync failed, will retry"
            detail = report.error
        else:
            note = f"jira: {len(report.notes)} update(s)"
            detail = "\n".join(report.notes)
        if report.notes or report.error:
            self.store.update_state(job.id, job.state, note=note, detail=detail)
        return self.store.get(job.id)

    def jira_sweep(self) -> dict[str, Any]:
        """The PO's round: every development of a Jira-linked project is reconciled —
        missing epics, stories and sub-tasks are created, stories join the sprint (or a
        sprint is started), statuses catch up. Runs at startup and on a timer; safe to
        run any time because ``reconcile`` is idempotent. Never raises."""
        summary: dict[str, Any] = {"jobs": 0, "updated": 0, "errors": 0, "at": utcnow().isoformat()}
        if not self.jira_settings().configured:
            return summary
        for job in self.store.list():
            project = self._project_of(job)
            if project is None or not project.jira_project_key:
                continue
            if job.state is JobState.FAILED and not job.data.jira_keys:
                continue  # never mirrored: nothing to complete
            summary["jobs"] += 1
            with self._locks[job.id]:  # never alongside the job's own handler
                try:
                    before = len(self.store.get(job.id).history)
                    after_job = self._jira_reconcile(self.store.get(job.id))
                    if len(after_job.history) > before:
                        summary["updated"] += 1
                    if after_job.data.jira_last_error:
                        summary["errors"] += 1
                except Exception as exc:  # noqa: BLE001 - one bad job must not stop the round
                    log.warning("jira sweep: job %s: %s", job.id, exc)
                    summary["errors"] += 1
        self.store.set_setting("jira.last_sweep", summary)
        return summary

    # -- public API ----------------------------------------------------------------------

    def create_project(self, project: Project) -> Project:
        """Register a project; clone its remote first when it has no local checkout."""
        # The clone runs on the *owner's* token, exactly as the pushes that follow it
        # will. The sources page writes that token under the account, so an unbound read
        # here finds nothing at all and git falls through to asking for a username.
        mine = self.for_user(project.owner_id)
        if project.repo_path is None:
            url = project.effective_clone_url
            if url is None:
                raise ValueError("project needs a repo_path or a github_repo/clone_url")
            target = self.repos_root / project.id
            target.parent.mkdir(parents=True, exist_ok=True)
            source = project.source or mine.default_source()
            token = mine.source_token(source)
            try:
                g.clone(mine._authenticated(url, source), target)
            except g.GitError as exc:
                # git prints back the URL it was given, token and all; this message is
                # written into the job's history and shown on the page
                detail = scrub(f"could not clone {url}: {exc.stderr}", token)
                if token is None:
                    # a private repository refused an anonymous clone: the missing token
                    # is the cause, and git's own words never say so
                    spec = SOURCES.get(source)
                    detail += (
                        f" -- no token for {spec.label if spec else source}:"
                        " add one under Settings -> Sources"
                    )
                raise ProjectCloneError(detail) from exc
            # git clone keeps the URL it was handed, so the token would live on in
            # .git/config -- readable by `git remote -v` from inside the checkout, which
            # is where a project's own build and test commands run. Push does not need it
            # there (`GhHost._credentials` supplies it per call), so origin is put back to
            # the plain URL at once.
            g.set_remote(target, "origin", url)
            mine._seed_if_empty(target, project)
            project = project.model_copy(update={"repo_path": target})
        elif not project.repo_path.is_dir():
            raise ValueError(f"repo_path is not a directory: {project.repo_path}")
        else:
            self._ensure_git_repository(project.repo_path)
        mine._wire_remote(project)
        return self.store.create_project(project)

    def update_project(self, project: Project) -> Project:
        """Save a changed project; a local checkout that has just been given a GitHub
        repository gets its ``origin`` wired, so the next development pushes its branch
        and opens a pull request instead of finishing in the checkout."""
        self._wire_remote(project)
        return self.store.update_project(project)

    def _wire_remote(self, project: Project) -> None:
        """Give a local checkout an ``origin`` pointing at the project's GitHub
        repository. A checkout that already has one keeps it: the remote the user set up
        themselves is the one to push to, whatever the project names."""
        if project.repo_path is None:
            return
        url = project.effective_clone_url
        if url is None or g.has_remote(project.repo_path):
            return
        try:
            g.set_remote(project.repo_path, "origin", url)
        except g.GitError as exc:
            raise ValueError(f"could not point {project.repo_path} at {url}: {exc.stderr}") from exc

    def _seed_if_empty(self, checkout: Path, project: Project) -> None:
        """A repository the host opened empty has no branch, and a development cannot start
        from nothing: the first commit is written here and pushed, so the checkout and the
        host agree on where the work begins."""
        if g.run(checkout, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0:
            return
        # the branch the *project's* host starts from, which is not always GitHub's: a
        # repository opened on Bitbucket was seeded on whatever GitHub had been set to
        branch = self.base_branch_of(project)
        readme = checkout / "README.md"
        if not readme.exists():
            readme.write_text(f"# {project.name}\n\n{project.description}\n", encoding="utf-8")
        g.run(checkout, "checkout", "-q", "-B", branch)
        g.stage_all(checkout)
        g.commit(checkout, "slipwright: first commit")
        try:
            self.host_for(project).push(checkout, branch)
        except (GitHostError, SourceError) as exc:  # the checkout is usable either way
            log.warning("could not push the first commit of %s: %s", project.name, exc)

    @staticmethod
    def _ensure_git_repository(path: Path) -> None:
        """A plain folder becomes a repository with everything in it committed, so jobs
        can branch from it; an existing repository is left exactly as it is.

        One that has never had a commit is finished the same way as a plain folder. Git
        2.42 and later branch a worktree from nothing without complaint, but the git in
        the image (Debian's 2.39) says "not a valid object name: 'HEAD'", so the first
        development of such a project could never start there."""
        is_repo = (path / ".git").exists()
        has_commit = (
            is_repo
            and g.run(path, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode == 0
        )
        if has_commit:
            return
        try:
            if not is_repo:
                g.run(path, "init", "-q", "-b", "main")
            g.run(path, "add", "-A")
            g.run(
                path,
                "-c",
                "user.name=slipwright",
                "-c",
                "user.email=slipwright@localhost",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "slipwright: initial import",
            )
        except g.GitError as exc:
            raise ValueError(f"could not turn {path} into a git repository: {exc.stderr}") from exc

    def _authenticated(self, url: str, source: str | None = None) -> str:
        """Embed the host's stored token into an HTTPS clone URL; never persisted."""
        try:
            host = self.source_host(source)
        except SourceError:
            return url
        return host.authenticated_url(url)

    def local_repos(self) -> list[dict[str, Any]]:
        """The folders under ``local_repos_root`` a project can be registered from, git
        repositories first; empty when no root is configured."""
        root = self.local_repos_root
        if root is None or not root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for path in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            out.append(
                {
                    "name": path.name,
                    "path": path.as_posix(),
                    "is_git": (path / ".git").exists(),
                }
            )
        out.sort(key=lambda r: (not r["is_git"], r["name"].lower()))
        return out

    def create_job(
        self,
        request: str,
        repo_path: Path | None = None,
        *,
        project_id: str | None = None,
        title: str = "",
    ) -> Job:
        """Create a job inside a project.

        With ``project_id`` the job uses that project's checkout. With only ``repo_path``
        the repository's project is looked up, or created on the spot, so callers that
        predate projects keep working. ``title`` is the short name it is shown by; without
        one (a chat message, the CLI) it is named after the request's first sentence.
        """
        project: Project | None
        if project_id is not None:
            project = self.store.get_project(project_id)
        elif repo_path is not None:
            project = self.store.find_project_by_repo(repo_path)
            if project is None:
                project = self.store.create_project(
                    Project(name=Path(repo_path).resolve().name or "project", repo_path=repo_path)
                )
        else:
            raise ValueError("create_job needs a project_id or a repo_path")
        if project.repo_path is None:
            raise RuntimeError(f"project {project.id} has no checkout")
        brief = self.store.get_brief(project.id)
        # the id is minted here rather than by the default factory: the branch is named
        # after it, and the two have to be the same id
        job_id = new_job_id()
        name = title.strip() or headline(request)
        return self.store.create(
            Job(
                id=job_id,
                title=name,
                project_id=project.id,
                # the job inherits the project's owner: it decides who may see it and,
                # once it runs, whose model keys pay for it
                owner_id=project.owner_id,
                request=request,
                repo_path=project.repo_path,
                data=JobData(
                    language=project.language,
                    plan_gate=project.plan_gate,
                    # after the name a person gave it, which says what it is in far fewer
                    # words than the request's opening does
                    branch_name=branch_name(project.name, name, job_id),
                    # the approved brief only: half-written analysis items never reach an agent
                    brief=brief.context() if brief.ready else [],
                ),
            )
        )

    def delete_project(self, project_id: str, *, purge: bool = False) -> None:
        """Delete a project. ``purge`` gives up on it entirely.

        The ordinary delete refuses while a development is unfinished, which is right
        while the work still matters. It is wrong when it no longer does: a development
        stopped at a gate cannot be failed or finished, so a project somebody has
        abandoned would be undeletable and its worktrees would sit on the disk forever.

        A purge stops caring about state: every worktree and branch goes, and so does the
        checkout -- **but only one Slipwright cloned itself**, which is the one under
        ``repos_root``. A folder the person pointed at is their own work and is left
        exactly as it is, whatever else happens here.
        """
        project = self.store.get_project(project_id)
        if purge:
            for job in self.store.list(project_id):
                with self._locks[job.id]:
                    if job.worktree_path is not None or job.port is not None:
                        # a worktree of a development still running is pulled out from
                        # under it; it has been given up on, so that is the point
                        try:
                            self.workspace.destroy(job)
                        except Exception as exc:  # noqa: BLE001 - one bad worktree must
                            # not stop the purge: whatever is left is still wanted gone
                            log.warning("purge %s: job %s: %s", project_id, job.id, exc)
        self.store.delete_project(project_id, force=purge)
        if purge:
            self._remove_our_checkout(project)

    def _remove_our_checkout(self, project: Project) -> None:
        """Delete the checkout, if it is one Slipwright cloned rather than one it was
        pointed at. Compared by resolved path: a symlink or a relative parent must not be
        able to make somebody's own folder look like ours."""
        path = project.repo_path
        if path is None:
            return
        try:
            here = path.resolve()
            ours = self.repos_root.resolve()
        except OSError:  # already gone, or unreadable: nothing of ours to remove
            return
        if here.parent != ours or not here.is_dir():
            return
        _rmtree(here)

    def delete_job(self, job_id: str) -> None:
        """Remove a finished job: its worktree and branch, its port, its rows."""
        job = self.store.get(job_id)
        if not job.is_terminal:
            raise JobInProgress(job.id, job.state)
        with self._locks[job.id]:
            if job.worktree_path is not None or job.port is not None:
                self.workspace.destroy(job)
            self.store.delete_job(job.id)

    def seed_for(self, job: Job) -> Profile:
        """The seed profile a job starts from: its project's, else the engine's default."""
        if job.project_id is not None:
            try:
                project = self.store.get_project(job.project_id)
            except ProjectNotFound:
                return self.seed_profile
            if project.profile is not None:
                return project.profile
        return self.seed_profile

    def start(self, job_id: str, *, run: bool = True) -> Job:
        """Move a new job into analysis. With ``run=False`` only the transition happens;
        call ``resume`` later (e.g. from a background worker) to execute the phase."""
        job = self.orchestrator.transition(job_id, JobState.BACKLOG, note="job started")
        return self._run(job) if run else job

    def approve(self, job_id: str, *, run: bool = True, by: str | None = None) -> Job:
        job = self.store.get(job_id)
        edges = approval_edges(job)
        if edges is None:
            raise NotAwaitingApproval(job)
        note = "approved"
        if job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage == 1:
            if not job.data.test_cases:
                raise EmptyApproval("there are no test cases to approve; add some or reject")
            job.data.qa_stage = 2
            job.data.build_attempts = 0
            job.data.last_build_output = None
            note = f"approved {len(job.data.test_cases)} test cases"
        if job.state is JobState.AWAITING_REVIEW_APPROVAL:
            # the violations stand as recorded; the phase is accepted as built
            job.data.review_violations = []
            job.data.review_rounds = 0
            note = f"approved phase {job.data.phase_index} despite the review"
        if job.state is JobState.AWAITING_DESIGN_APPROVAL:
            waiting = designer.pending_screens(job)
            if not waiting:
                raise EmptyApproval("every screen is already approved")
            for screen in waiting:
                job.data.design_approvals[str(screen.get("id"))] = True
            job.data.design_feedback = {}
            note = f"approved {len(waiting)} screen(s)"
        if job.state is JobState.AWAITING_DEPLOY_APPROVAL:
            plan = job.data.deploy or {}
            scripts = plan.get("scripts", [])
            if not scripts:
                raise EmptyApproval("there are no deployment scripts to approve; or reject")
            job.data.devops_stage = 2
            note = f"approved {len(scripts)} deployment script(s) for {plan.get('target')}"
        if job.state is JobState.AWAITING_RECONCILE_APPROVAL:
            note = self._accept_reconcile(job)
        if job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL:
            job.data.replan_from = None  # the re-plan is accepted; it is the plan now
        if by:
            note = f"{note} by {by}"
        if job.state is JobState.AWAITING_DECISION:
            if job.data.decision_kind == "phase_budget":
                raise EmptyApproval(
                    "this phase spent its budget: write what to do next, or send QA's "
                    "recommendation as it is"
                )
            note = f"{note}: continue with {edges[0].value}"
            job.data.resume_state = None
        job.data.feedback = None
        job.data.reject_rounds = 0
        job.data.output_hashes = {}  # a human decision is a fresh start for the loop check
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[0], note=note)
        return self._run(job) if run else job

    def skip_tests(self, job_id: str, *, run: bool = True) -> Job:
        """Read the test cases, decide they are not worth writing, and go on without them.

        Rejecting means "not good enough, do it again", at this gate as at every other one,
        and it would be a trap to make it mean "abandon the step" here alone: somebody
        asking for one more case would lose the tests altogether. This is the other answer,
        and it is a deliberate one -- writing the tests is the most expensive step in a
        development, and not every development is worth it.

        Only at the first of QA's two gates. Once the tests exist there is nothing to save
        by throwing them away.
        """
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_TEST_APPROVAL or job.data.qa_stage != 1:
            raise NotAwaitingApproval(job)
        job.data.tests_skipped = True
        job.data.feedback = None
        job.data.reject_rounds = 0
        job.data.output_hashes = {}
        self.store.save(job)
        job = self.orchestrator.transition(
            job,
            JobState.DEVOPS,
            note=f"skipped the tests: {len(job.data.test_cases)} case(s) were not written",
        )
        return self._run(job) if run else job

    def skip_deployment(self, job_id: str, *, run: bool = True) -> Job:
        """Read the deployment proposal and go on without it: the pull request carries the
        code and no ``deployment/`` files.

        The same reasoning as ``skip_tests``. Rejecting means "propose it again", and a
        person who deploys by hand, or does not deploy this at all, has no proposal they
        would accept -- rejecting over and over only pays DevOps to keep proposing. The
        plan stays on the record so the gate shows what was passed over.
        """
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_DEPLOY_APPROVAL:
            raise NotAwaitingApproval(job)
        scripts = (job.data.deploy or {}).get("scripts") or []
        job.data.deploy_skipped = True
        job.data.devops_stage = 2
        job.data.feedback = None
        job.data.reject_rounds = 0
        job.data.output_hashes = {}
        self.store.save(job)
        job = self.orchestrator.transition(
            job,
            JobState.DEVOPS,
            note=f"skipped the deployment: {len(scripts)} script(s) were not written",
        )
        return self._run(job) if run else job

    def reject(self, job_id: str, feedback: str, *, run: bool = True) -> Job:
        job = self.store.get(job_id)
        edges = approval_edges(job)
        if edges is None:
            raise NotAwaitingApproval(job)
        job.data.feedback = feedback
        job.data.reject_rounds += 1
        job.data.output_hashes = {}  # the feedback changes the input: not a loop
        if job.state is JobState.AWAITING_REVIEW_APPROVAL:
            # back to the specialist for another round on the same phase
            job.data.phase_index = max(job.data.phase_index - 1, 0)
            job.data.review_rounds = 0
            job.data.reject_rounds = 0
        if job.state is JobState.AWAITING_DESIGN_APPROVAL:
            # what was said applies to the screens still waiting; the ones already approved
            # keep their yes and the Designer leaves them alone
            for screen in designer.pending_screens(job):
                job.data.design_feedback[str(screen.get("id"))] = feedback
            job.data.reject_rounds = 0
        if job.state is JobState.AWAITING_DECISION:
            from slipwright.schemas.job import InboxMessage

            # the feedback reaches the role that continues, through the inbox
            job.data.inbox.append(InboxMessage(text=feedback))
            job.data.feedback = None
            job.data.reject_rounds = 0
            job.data.resume_state = None
            if job.data.decision_kind == "phase_budget":
                # the person's words are the next attempt's instruction, on a fresh budget
                job.data.phase_calls = 0
                job.data.build_attempts = 0
                job.data.decision_kind = None
                job.data.recommendation = None
                job.data.recommendation_route = None
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[1], note=f"rejected: {feedback}")
        return self._run(job) if run else job

    def review_screen(
        self, job_id: str, screen_id: str, *, ok: bool, feedback: str = "", run: bool = True
    ) -> Job:
        """Sign off one screen, or send it back with what should be different.

        The gate is per screen, not per development: eight of nine screens can be right.
        Saying yes to the last one waiting carries the development on to the phase that was
        stopped; sending one back puts the Designer to work on that screen alone, and the
        screens already approved keep their yes.
        """
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_DESIGN_APPROVAL:
            raise NotAwaitingApproval(job)
        screens = (job.data.design or {}).get("screens") or []
        screen = next((s for s in screens if str(s.get("id")) == screen_id), None)
        if screen is None:
            raise UnknownScreen(screen_id)
        name = str(screen.get("name") or screen_id)
        if ok:
            job.data.design_approvals[screen_id] = True
            job.data.design_feedback.pop(screen_id, None)
        else:
            if not feedback.strip():
                raise EmptyApproval("say what should be different before sending a screen back")
            job.data.design_approvals.pop(screen_id, None)
            job.data.design_feedback[screen_id] = feedback.strip()
        self.store.save(job)
        left = len(designer.pending_screens(job))
        self.store.update_state(
            job.id,
            job.state,
            note=(
                f"design: approved {name} ({left} left)"
                if ok
                else f"design: sent {name} back — {feedback.strip()}"
            ),
        )
        job = self.store.get(job.id)
        if not ok:
            # one screen redrawn is one call to the Designer; the rest are handed back as
            # they are, so nothing already agreed on is spent again
            job.data.output_hashes = {}
            self.store.save(job)
            job = self.orchestrator.transition(
                job, JobState.DESIGN, note=f"design: {name} sent back"
            )
            return self._run(job) if run else job
        if left:
            return job
        job.data.output_hashes = {}
        self.store.save(job)
        job = self.orchestrator.transition(job, JobState.DEVELOPING, note="approved: every screen")
        return self._run(job) if run else job

    def set_profile(self, job_id: str, profile: Profile) -> Job:
        """Replace the proposed profile while the job waits for its approval."""
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_ARCHITECTURE_APPROVAL:
            raise NotAwaitingApproval(job)
        phases = [PlanPhase.model_validate(p) for p in self._phases(job)]
        missing = unbuilt_platforms(phases, profile)
        if missing:
            # the plan still has phases for it: taking its commands away would leave them
            # with nothing to be built by
            raise InvalidEdit(f"the plan has {', '.join(missing)} phases; keep their commands")
        job.profile = profile
        return self.store.save(job)

    def set_backlog(self, job_id: str, breakdown: dict[str, Any]) -> Job:
        """Replace the proposed backlog while the job waits at the backlog gate — or, with
        the combined plan gate, while it waits at the one work list. There the architect has
        already planned around these tasks, so the wording may change but the set of tasks
        may not: adding or dropping one means rejecting the list and having it written again."""
        job = self.store.get(job_id)
        combined = (
            job.state is JobState.AWAITING_ARCHITECTURE_APPROVAL
            and job.data.plan_gate == "combined"
        )
        if job.state is not JobState.AWAITING_BACKLOG_APPROVAL and not combined:
            raise NotAwaitingApproval(job)
        try:
            tree = Breakdown.model_validate(breakdown)
            POResult(summary="edited", breakdown=tree)  # the PO's own checks (unique ids)
        except ValidationError as exc:
            raise InvalidEdit(str(exc)) from exc
        if combined:
            before = {t.id for t in Breakdown.model_validate(job.data.backlog).tasks()}
            after = {t.id for t in tree.tasks()}
            if before != after:
                raise InvalidEdit(
                    "the architect has already planned a phase per task: reword them here, "
                    "or reject the list to have it written again"
                )
            plan = dict(job.data.plan or {})
            if plan.get("breakdown"):
                plan["breakdown"] = _reworded(plan["breakdown"], tree)
                job.data.plan = plan
        job.data.backlog = tree.model_dump(mode="json")
        return self.store.save(job)

    def set_plan(self, job_id: str, plan: dict[str, Any]) -> Job:
        """Replace the proposed plan (phases and breakdown) while the job waits at the
        architecture gate. Checked exactly like the Architect's output: every task has one
        phase, every phase names a task."""
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_ARCHITECTURE_APPROVAL:
            raise NotAwaitingApproval(job)
        current = job.data.plan or {}
        try:
            phases = [
                PlanPhase.model_validate(p)
                for p in _renumbered(current.get("phases", []), plan.get("phases", []))
            ]
            breakdown = Breakdown.model_validate(
                plan.get("breakdown") or current.get("breakdown") or job.data.backlog
            )
            POResult(summary="edited", breakdown=breakdown)
        except ValidationError as exc:
            raise InvalidEdit(str(exc)) from exc
        if not phases:
            raise InvalidEdit("a plan needs at least one phase")
        missing = unbuilt_platforms(phases, job.profile) if job.profile else []
        if missing:
            raise InvalidEdit(
                f"no commands build {', '.join(missing)}: add them to the profile first"
            )
        mapping = architect.phase_task_map(phases, [t.id for t in breakdown.tasks()])
        if isinstance(mapping, str):
            raise InvalidEdit(f"plan does not match the backlog: {mapping}")
        order = architect.dependency_problem(phases)
        if order is not None:
            raise InvalidEdit(order)
        for task in breakdown.tasks():
            task.phase = mapping[task.id]
        decisions = plan.get("decisions", current.get("decisions", []))
        try:
            stack = [
                StackChoice.model_validate(c) for c in plan.get("stack", current.get("stack", []))
            ]
        except ValidationError as exc:
            raise InvalidEdit(str(exc)) from exc
        job.data.plan = {
            "summary": str(plan.get("summary", current.get("summary", ""))),
            "stack": [c.model_dump(mode="json") for c in stack],
            "decisions": [str(d) for d in decisions],
            "phases": [p.model_dump(mode="json") for p in phases],
            "breakdown": breakdown.model_dump(mode="json"),
        }
        job.data.phase_index = job.data.replan_from or 0
        return self.store.save(job)

    def set_test_cases(self, job_id: str, cases: list[dict[str, Any]]) -> Job:
        """Replace the proposed test list while the job waits for its approval."""
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_TEST_APPROVAL or job.data.qa_stage != 1:
            raise NotAwaitingApproval(job)
        job.data.test_cases = qa.normalise_cases(cases)
        return self.store.save(job)

    def set_deploy(self, job_id: str, plan: dict[str, Any]) -> Job:
        """Replace the deployment proposal while the job waits at the deployment gate.

        The person may change the target, drop a script or add one; what comes back is
        validated exactly like the model's own answer, so an edited plan can never be
        something DevOps could not have proposed.
        """
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_DEPLOY_APPROVAL:
            raise NotAwaitingApproval(job)
        current = job.data.deploy or {}
        merged = {**current, **plan}
        merged.setdefault("summary", current.get("summary") or "edited")
        try:
            edited = DeployPlan.model_validate(merged)
        except ValidationError as exc:
            raise InvalidEdit(str(exc)) from exc
        folder = f"{devops.DEPLOY_FOLDER}/"
        outside = [sc.path for sc in edited.scripts if not sc.path.startswith(folder)]
        if outside:
            raise InvalidEdit(f"every script lives under {folder}: {', '.join(outside)}")
        job.data.deploy = edited.model_dump(mode="json")
        return self.store.save(job)

    def resume(self, job_id: str) -> Job:
        """Continue a job from its persisted state; a no-op unless it was mid-phase."""
        return self._run(self.store.get(job_id))

    def resume_all(self) -> list[Job]:
        return [self.resume(job.id) for job in self.store.list()]

    def message(
        self,
        job_id: str,
        text: str,
        *,
        by: str | None = None,
        step: str | None = None,
        phase: int | None = None,
        role: str | None = None,
        reply_to: str | None = None,
    ) -> Job:
        """Queue a steering message; the next role invocation will see it -- the next one
        by ``role`` on ``phase`` when they are given.

        Written as a row of its own and nothing else: saving the job from here would put
        the request's copy of it over whatever the run has written since it was read."""
        job = self.store.get(job_id)
        self.store.add_message(
            JobMessage(
                job_id=job.id,
                kind="steer",
                text=text,
                by=by,
                step=step,
                phase=phase,
                role=role,
                reply_to=reply_to,
                status="pending",
            )
        )
        self.events.emit(
            "job.message", project_id=job.project_id, job_id=job.id, owner_id=job.owner_id
        )
        return self.store.get(job.id)

    # -- talking to the agents on a step -----------------------------------------------------

    def talk_card(self, job: Job, step: str) -> StepCard:
        """The step a person is writing about, when it has an agent to answer them. A
        gate is a person's step and the demo has nobody behind it."""
        card = next((c for c in lane_for(job).steps if c.key == step), None)
        if card is None or card.role is None or card.gate:
            raise NothingToAsk(f"step {step!r} has no agent to write to")
        return card

    def talk(self, job_id: str, step: str) -> list[JobMessage]:
        """What was said on one step, both ways, oldest first."""
        return self.store.list_messages(job_id, step=step)

    def ask(self, job_id: str, step: str, text: str, *, by: str | None = None) -> JobMessage:
        """Write a question to the agent on ``step``. The answer is written by ``answer``,
        which the caller runs in the background: a model call is minutes, not a request."""
        job = self.store.get(job_id)
        card = self.talk_card(job, step)
        text = text.strip()
        if not text:
            raise EmptyApproval("write what you want to ask")
        assert card.role is not None
        message = self.store.add_message(
            JobMessage(
                job_id=job.id,
                kind="question",
                text=text,
                by=by,
                step=card.key,
                phase=card.phase,
                role=card.role.value,
                status="answering",
            )
        )
        self._told(job)
        return message

    def answer(self, message_id: str) -> JobMessage | None:
        """Ask the agent the question and write down what it says.

        A side call: it takes nothing from the run, holds no lock while the model thinks,
        and writes only its own row -- the job's row belongs to the run, which may be in the
        middle of a phase. What it cost is added to the job's spend by whoever holds the job
        next (``_bill_answers``), at once when nobody does."""
        message = self.store.get_message(message_id)
        if message is None or message.kind != "question" or message.status != "answering":
            return message
        job = self.store.get(message.job_id)
        role = RoleName(message.role or RoleName.ARCHITECT.value)
        refused = self._answer_refused(job)
        if refused is not None:
            answered = self.store.answer_message(message.id, answer=None, error=refused)
            self._told(job)
            return answered
        detail = step_detail(job, message.step or "")
        earlier = [
            {"question": m.text, "answer": m.answer or ""}
            for m in self.store.list_messages(job.id, step=message.step, kinds=["question"])
            if m.status == "answered" and m.id != message.id
        ][-ANSWERS_REMEMBERED:]
        started = utcnow().isoformat()
        result = talk.run(
            job,
            job.profile or self.seed_for(job),
            role=role,
            step=talk.step_record(detail) if detail else {"name": message.step},
            question=message.text,
            earlier=earlier,
            phase=message.phase,
            work_in_progress=self._work_in_progress(job, message.phase),
            provider=self.provider_for(job.owner_id),
            timeout_s=self.timeout_s,
        )
        cost = self._answer_cost(job, role, result, message.phase, started)
        if result.ok and isinstance(result.output, AgentAnswer):
            change = (result.output.change or "").strip() or None
            answered = self.store.answer_message(
                message.id, answer=result.output.answer.strip(), change=change, cost=cost
            )
        else:
            why = result.error.message if result.error else "the agent gave no answer"
            answered = self.store.answer_message(
                message.id, answer=None, error=why, cost=cost if result.usage else None
            )
        lock = self._locks[job.id]
        if lock.acquire(blocking=False):
            try:
                # nothing is running it: the spend goes on the job now. A transition between
                # the read and the save refuses the save; the next call bills it instead
                with contextlib.suppress(ValueError, JobNotFound):
                    self._bill_answers(self.store.get(job.id))
            finally:
                lock.release()
        self._told(job)
        return answered

    def steer(
        self,
        job_id: str,
        step: str,
        text: str,
        *,
        by: str | None = None,
        reply_to: str | None = None,
    ) -> Job:
        """An instruction for the agent on ``step``, read by its next call on that step.

        Only for a step still to finish: what a finished phase is told is never read, and
        saying "sent" for that would be a promise nothing keeps. A finished step is changed
        by planning again from where the development is (``redirect``)."""
        job = self.store.get(job_id)
        card = self.talk_card(job, step)
        if job.is_terminal or card.status in (StepStatus.DONE, StepStatus.SKIPPED):
            raise NotAwaitingApproval(job)
        text = text.strip()
        if not text:
            raise EmptyApproval("write the instruction")
        assert card.role is not None
        return self.message(
            job.id,
            text,
            by=by,
            step=card.key,
            phase=card.phase,
            role=card.role.value,
            reply_to=reply_to,
        )

    def redirect(
        self,
        job_id: str,
        note: str,
        *,
        by: str | None = None,
        reply_to: str | None = None,
        run: bool = True,
    ) -> Job:
        """Plan the development again from the phase it is on, with what a person wants
        instead -- while it is being built, not only once it has failed.

        The phases already built stay built: the Architect is handed them as kept and
        replaces the rest (``_replan_from``), and the new plan is approved at the
        architecture gate like any other. A call that is in flight is not thrown away --
        the model is answering and that answer is paid for -- so a running development
        re-plans before its next call."""
        job = self.store.get(job_id)
        if job.state not in REDIRECTABLE or not job.data.plan:
            raise NotAwaitingApproval(job)
        note = note.strip()
        if not note:
            raise EmptyApproval("say what the plan should do instead")
        message = self.store.add_message(
            JobMessage(
                job_id=job.id,
                kind="replan",
                text=note,
                by=by,
                reply_to=reply_to,
                phase=job.data.phase_index + 1,
                step=f"phase:{job.data.phase_index + 1}",
                status="pending",
            )
        )
        lock = self._locks[job.id]
        if lock.acquire(blocking=False):
            try:
                job = self._replan_now(self.store.get(job.id), message, by=by)
            finally:
                lock.release()
            self._told(job)
            return self._run(job) if run else job
        current = self._stopping.get(job.id)
        if current is not None and current.kind == "cancel":
            # stopping for good outranks it; the request is kept, and says it was not acted on
            self.store.set_message_status(message.id, "dropped")
            self._told(job)
            return self.store.get(job.id)
        self._supersede(job.id, _Halt("redirect", by=by, message=message.id))
        self.store.update_state(
            job.id,
            job.state,
            note=f"re-plan asked{_by(by)}: finishing the call it is on",
        )
        self._told(job)
        return self.store.get(job.id)

    def _replan_now(self, job: Job, message: JobMessage, *, by: str | None) -> Job:
        """Send the plan back to the Architect from the phase the development is on."""
        if job.state not in REDIRECTABLE:
            # it moved on while the call finished -- to QA, say, with every phase built.
            # There is no phase left to plan; the request is kept as one not acted on
            self.store.set_message_status(message.id, "dropped")
            return job
        phases = self._phases(job)
        index = min(job.data.phase_index, len(phases))
        parts = [
            f"A person asked for the plan to change while phase {index + 1} of "
            f"{len(phases)} was being built. What they want instead: {message.text}",
        ]
        if index:
            parts.append(f"Phases 1-{index} are built and committed; they are kept as they are.")
        if job.state in (JobState.DEVELOPING, JobState.BUILD_GATE):
            parts.append(
                f"Phase {index + 1} is partly written in the checkout and not committed: "
                "plan from what is there, keeping what still serves the new plan."
            )
        job.data.resume_state = None
        job = self._replan_from(
            job,
            index,
            "\n\n".join(parts),
            note=f"re-plan from phase {index + 1}{_by(by)}: {message.text}",
        )
        self.store.set_message_status(message.id, "applied")
        return job

    def _told(self, job: Job) -> None:
        self.events.emit(
            "job.message", project_id=job.project_id, job_id=job.id, owner_id=job.owner_id
        )

    def _answer_refused(self, job: Job) -> str | None:
        """Why a question is not put to the model. The calls and tokens the development
        may spend bound an answer too -- it is spent on the same keys. Its running time
        does not: asking about a development is not running it."""
        budget = self.budget_for(job)
        if budget.max_invocations is not None and job.data.invocations >= budget.max_invocations:
            return f"{job.data.invocations} model calls (limit {budget.max_invocations})"
        if budget.max_tokens is not None and job.data.tokens_used >= budget.max_tokens:
            return f"{job.data.tokens_used} tokens used (limit {budget.max_tokens})"
        return None

    def _work_in_progress(self, job: Job, phase: int | None) -> str | None:
        """What the phase a question is about has written so far, when it is the one being
        built now. A finished phase is a commit and its record already lists its files."""
        worktree = job.worktree_path
        base = job.data.phase_base_commit
        if (
            phase is None
            or base is None
            or worktree is None
            or not worktree.exists()
            or job.state not in (JobState.DEVELOPING, JobState.BUILD_GATE)
            or phase != job.data.phase_index + 1
        ):
            return None
        try:
            return g.work_in_progress(worktree, base) or None
        except (OSError, g.GitError):
            return None

    def _answer_cost(
        self,
        job: Job,
        role: RoleName,
        result: RoleResult,
        phase: int | None,
        started: str,
    ) -> dict[str, Any]:
        """The call log entry for an answer, as ``_account`` writes one for a step."""
        usage = result.usage
        price = self.price_of(result.provider, result.model)
        cost = (
            price.cost(usage.input_tokens or 0, usage.output_tokens or 0)
            if price and usage
            else None
        )
        return {
            "role": role.value,
            "model": result.model,
            "state": job.state.value,
            "phase": phase,
            "attempts": 1,
            "prompt_chars": result.prompt_chars,
            "provider": result.provider,
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "cost_usd": round(cost, 6) if cost is not None else None,
            "ok": result.ok,
            "error": result.error.kind.value if result.error else None,
            "unreported_attempts": None,
            "started_at": started,
            "summary": "answered a question",
            "output": None,
            "at": utcnow().isoformat(),
        }

    # -- the supervisor at the gates (T9.8) --------------------------------------------------

    def supervisor_settings(self, job: Job) -> SupervisorSettings:
        """The project's gate mode; a job without a project has nowhere to configure
        one and stays manual."""
        project = self._project_of(job)
        settings = SupervisorSettings(mode="manual") if project is None else project.supervisor
        if self.supervisor_override is not None:
            settings = settings.model_copy(update={"mode": self.supervisor_override})
        return settings

    def _is_final_gate(self, job: Job) -> bool:
        """The written-tests approval hands the branch to DevOps: the last human gate."""
        return job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage == 2

    def _supervise(self, job: Job) -> Job:
        """Ask the supervisor at a gate. Assisted: record the recommendation. Auto: turn a
        confident, low-risk approval into an ordinary approve call, within the per-job cap
        and never at the final gate unless the project allows it. Errors leave the gate to
        the human."""
        settings = self.supervisor_settings(job)
        if settings.mode == "manual" or job.state not in APPROVAL_STATES:
            return job
        if job.state is JobState.AWAITING_DECISION:
            return job  # a loop or the supervisor itself stopped here: a person decides
        profile = job.profile or self.seed_for(job)
        gate = supervisor.gate_name(job)
        written = None
        if job.state is JobState.AWAITING_TEST_APPROVAL and job.data.qa_stage == 2:
            written = self._branch_diff(job) if job.worktree_path else None
        record: dict[str, Any] = {
            "gate": gate,
            "mode": settings.mode,
            "at": utcnow().isoformat(),
            "acted": "none",
            "undone": False,
        }
        result = self._invoke(
            RoleName.SUPERVISOR,
            supervisor.run,
            job,
            profile=profile,
            gate_material=supervisor.material(job, written_tests=written),
            jira=None,
        )
        if not result.ok:
            assert result.error is not None
            record.update({"acted": "error", "error": result.error.message})
            job.data.supervision = record
            self.store.save(job)
            self.store.update_state(
                job.id,
                job.state,
                note=f"supervisor failed: {result.error.kind.value}; the gate waits for you",
                detail=result.error.message,
            )
            return self.store.get(job.id)
        assert isinstance(result.output, SupervisorResult)
        out = result.output
        record.update(
            {
                "decision": out.decision,
                "confidence": round(out.confidence, 3),
                "risk": out.risk,
                "reasons": out.reasons,
                "feedback": out.feedback,
                "summary": out.summary,
            }
        )
        reasons = "; ".join(out.reasons) or out.summary
        blockers: list[str] = []
        if out.decision != "approve":
            blockers.append("recommends rejecting")
        if out.risk != "low":
            blockers.append(f"risk {out.risk}")
        if out.confidence < settings.threshold:
            blockers.append(f"confidence {out.confidence:.2f} < {settings.threshold:.2f}")
        if job.data.auto_approvals >= settings.cap:
            blockers.append(f"cap of {settings.cap} automatic approval(s) reached")
        if self._is_final_gate(job) and not settings.allow_final_gate:
            blockers.append("the final gate is never automatic")
        auto = settings.mode == "auto" and not blockers
        if settings.mode != "auto":
            blockers = []  # assisted: the human decides, nothing is "blocked"
        record["blockers"] = blockers
        record["acted"] = "auto" if auto else "none"
        job.data.supervision = record
        self.store.save(job)
        self.store.update_state(
            job.id,
            job.state,
            note=(
                f"supervisor: recommends {out.decision} "
                f"(confidence {out.confidence:.2f}, risk {out.risk})"
                + ("" if auto else (f"; waits for you: {', '.join(blockers)}" if blockers else ""))
            ),
            detail=json.dumps(record, indent=2),
        )
        job = self.store.get(job.id)
        if not auto:
            return job
        job.data.auto_approvals += 1
        self.store.save(job)
        job = self.approve(
            job.id, run=False, by=f"supervisor (confidence {out.confidence:.2f}): {reasons}"
        )
        self.events.emit(
            "supervisor.auto_approved",
            project_id=job.project_id,
            job_id=job.id,
            payload={"gate": gate, "confidence": out.confidence, "reasons": out.reasons},
        )
        self._notify_webhook(job, gate, record)
        return job

    def rerun(self, job_id: str, step: str, *, run: bool = True) -> Job:
        """Run one finished step again, on the work that is already there.

        ``test_cases`` asks QA for the list of scenarios again, from the top: the step
        that proposes them, not the one that runs them. A development whose QA answer came
        back with the cases buried in prose and the list empty has nothing to re-run
        otherwise. ``tests`` runs the build gate: the test command over the current
        worktree, nothing rewritten. ``devops`` runs the DevOps step from the top — the
        write-up, the push and the pull request — which is how a development that finished
        with nowhere to push reaches GitHub once the project names a repository.

        Only a development that has stopped can be re-run; a running one is left alone.
        """
        targets = {
            "test_cases": JobState.QA,
            "tests": JobState.BUILD_GATE,
            "devops": JobState.DEVOPS,
        }
        if step not in targets:
            raise ValueError(f"unknown step {step!r}; expected one of {sorted(targets)}")
        job = self.store.get(job_id)
        if job.state in WORKING_STATES:
            raise JobIsRunning(job)
        if job.state is JobState.PAUSED:
            # the pause can reach every state, a re-run's included; going there from here
            # would skip the check that nobody pushed meanwhile -- carry it on instead
            raise IllegalTransitionError(job.state, targets[step])
        if job.worktree_path is None:
            raise ValueError("this development has no worktree to run anything in")
        back = targets[step]
        # the counters that made the step give up start over, as they do on a retry
        job.data.build_attempts = 0
        job.data.ci_attempts = 0
        job.data.output_hashes = {}
        # a passing gate stops here rather than carrying the whole tail of the pipeline
        # again; a failing one hands over to the specialist, which is the point of asking
        job.data.rerun_only = back is JobState.BUILD_GATE
        if step == "test_cases":
            # stage one proposes the scenarios; stage two is the one that writes tests
            job.data.qa_stage = 1
        if back is JobState.DEVOPS:
            # the pull request is opened again; without this the step would only poll CI
            job.data.pr_url = None
        self.store.save(job)
        job = self.orchestrator.transition(job, back, note=f"re-run by hand: {step}")
        return self._run(job) if run else job

    def cancel(self, job_id: str, *, by: str | None = None) -> Job:
        """Stop a development, wherever it is.

        The answer to "this is not worth what it is spending", which can be true at any
        point: mid-phase, or sitting at a gate nobody is going to answer. It is not a
        failure -- nothing went wrong -- so it does not land in ``failed``, is not offered
        a retry, and does not count against anything.

        What it cannot do is interrupt a call that is already in flight. The model is
        answering and that answer is already paid for, so the stop takes effect before the
        next call -- the next step, or the next call inside this one, a retry included:
        whatever was being answered finishes, and nothing further is asked. A development
        that is not running at all stops here and now.
        """
        job = self.store.get(job_id)
        if job.is_terminal:
            raise NotAwaitingApproval(job)
        note = "stopped" + (f" by {by}" if by else "")
        # free means nothing is running it, so this is the one that has to do the work;
        # busy means the run loop owns the job and will see the flag between steps
        lock = self._locks[job.id]
        if lock.acquire(blocking=False):
            try:
                self._stopping.pop(job.id, None)
                job = self.orchestrator.transition(job, JobState.CANCELLED, note=note)
            finally:
                lock.release()
            return self._notify_outcome(job)
        # stopping for good outranks a pause asked for a moment earlier
        self._supersede(job.id, _Halt("cancel", by=by))
        self.store.update_state(job.id, job.state, note=f"{note}: finishing the call it is on")
        return self.store.get(job.id)

    # -- pausing to work by hand -------------------------------------------------------------

    def pause(self, job_id: str, *, push: bool = False, by: str | None = None) -> Job:
        """Stop a development so people can work on its branch, and keep its place.

        Unlike ``cancel`` it is not over: it waits in ``paused``, holding where it was --
        the state, the phase, the commit -- until the same person says carry on. With
        ``push`` the branch goes to the host as it stands, half-written phase and all, so
        there is something to check out and work on.

        Like a stop, it cannot interrupt a call in flight: a running development pauses
        before its next call, and the push happens then.
        """
        job = self.store.get(job_id)
        if job.is_terminal or job.state in (JobState.PAUSED, JobState.CREATED):
            raise NotAwaitingApproval(job)
        if push:
            self._pushable(job)  # refused now, not after the call it is on has finished
        halt = _Halt("pause", by=by, push=push)
        lock = self._locks[job.id]
        if lock.acquire(blocking=False):
            try:
                self._stopping.pop(job.id, None)
                job = self._enter_pause(job, halt)
            finally:
                lock.release()
            return job
        if self._stopping.get(job.id, halt).kind != "cancel":
            self._supersede(job.id, halt)
        self.store.update_state(
            job.id,
            job.state,
            note=f"pausing{_by(by)}: finishing the call it is on"
            + ("; the branch is pushed then" if push else ""),
        )
        return self.store.get(job.id)

    def carry_on(
        self, job_id: str, *, pull: bool = False, by: str | None = None, run: bool = True
    ) -> Job:
        """Carry a paused development on from where it was paused.

        Without ``pull`` it goes back to exactly that place, as if it had never stopped --
        but not when somebody pushed to its branch meanwhile (``RemoteMoved``): building
        beside commits it has never seen would have its next push refused at the end, or
        undo them. With ``pull`` those commits are merged in first and, while there are
        phases left to build, the Architect reads what they did (``reconcile``) so that
        a phase somebody finished is not built a second time.
        """
        job = self.store.get(job_id)
        if job.state is not JobState.PAUSED:
            raise NotAwaitingApproval(job)
        pause = dict(job.data.pause or {})
        back = JobState(pause.get("from_state") or JobState.DEVELOPING.value)
        with self._locks[job.id]:
            job = self.store.get(job_id)
            if job.state is not JobState.PAUSED:  # pressed twice
                raise NotAwaitingApproval(job)
            brought = self._pull_paused(job) if pull else 0
            if not brought:
                if not pull:
                    self._refuse_if_moved(job)
                self._unwind_pause_commit(job)
            pause = dict(job.data.pause or {})
            pause["resumed_at"] = utcnow().isoformat()
            job.data.pause = pause
            self.store.save(job)
            if brought and self._building(job, back):
                job.data.reconcile = None
                job.data.feedback = None
                job.data.output_hashes = {}
                self.store.save(job)
                job = self.orchestrator.transition(
                    job,
                    JobState.RECONCILE,
                    note=f"carried on{_by(by)}: pulled {brought} commit(s) pushed while it "
                    "was paused; the Architect reads what they did",
                )
            else:
                pulled = f": pulled {brought} commit(s)" if brought else ""
                if pull and not brought:
                    pulled = ": nothing new had been pushed"
                job = self.orchestrator.transition(job, back, note=f"carried on{_by(by)}{pulled}")
        return self._run(job) if run else job

    def sync_status(self, job_id: str) -> dict[str, Any]:
        """What the pause and carry-on dialogs can offer, asked of the host as they open:
        whether the branch can be pushed, and whether somebody pushed to it since the
        development last did. ``moved`` is None when the host could not be asked."""
        job = self.store.get(job_id)
        status: dict[str, Any] = {"can_push": True, "why_not": None, "moved": None}
        try:
            self._pushable(job)
        except CannotSync as exc:
            return {**status, "can_push": False, "why_not": str(exc)}
        worktree = require_worktree(job)
        try:
            head = self._host_of(job).remote_head(worktree, job.branch)
        except (SourceError, GitHostError):
            return status
        status["moved"] = head is not None and not self._have(worktree, head)
        return status

    def _pushable(self, job: Job) -> None:
        if job.worktree_path is None or not job.worktree_path.exists():
            raise CannotSync("nothing has been written yet: there is no branch to push")
        if not g.has_remote(job.worktree_path):
            raise CannotSync(
                "the project's checkout has no remote: set its repository to push the branch"
            )

    @staticmethod
    def _have(worktree: Path, commit: str) -> bool:
        """Whether ``commit`` is already part of this branch -- what it pushed itself, or
        anything before it."""
        return g.known(worktree, commit) and g.contains(worktree, commit, "HEAD")

    def _enter_pause(self, job: Job, halt: _Halt) -> Job:
        worktree = job.worktree_path
        head = g.head_commit(worktree) if worktree is not None and worktree.exists() else None
        job.data.pause = {
            "from_state": job.state.value,
            "phase_index": job.data.phase_index,
            "at": utcnow().isoformat(),
            "by": halt.by,
            "head": head,
            "pushed": None,
            "wip": None,
            "push_error": None,
        }
        self.store.save(job)
        job = self.orchestrator.transition(job, JobState.PAUSED, note=f"paused{_by(halt.by)}")
        return self._push_paused(job) if halt.push else job

    def _pause_commit_message(self, job: Job) -> str:
        phases = self._phases(job)
        if not phases:
            return "slipwright: paused (work in progress)"
        number = min(job.data.phase_index + 1, len(phases))
        return f"slipwright: paused in phase {number}/{len(phases)} (work in progress)"

    def _push_paused(self, job: Job) -> Job:
        """Push the paused branch as it stands. What a phase had written but not yet
        committed -- a phase is committed only once its build passes -- is committed so it
        goes too: people pick up from what there is, not from the last green phase. The
        commit is taken back out when it carries on without a pull, so the phase is built
        and committed as it would have been."""
        pause = dict(job.data.pause or {})
        try:
            self._pushable(job)
            worktree = require_worktree(job)
            g.stage_all(worktree)
            if g.commit(worktree, self._pause_commit_message(job)):
                pause["wip"] = g.head_commit(worktree)
            self._host_of(job).push(worktree, job.branch)
            pause["pushed"] = g.head_commit(worktree)
            note = f"pushed {job.branch} so it can be worked on by hand"
        except (CannotSync, SourceError, GitHostError) as exc:
            pause["push_error"] = str(exc)
            note = f"paused, but the branch was not pushed: {exc}"
        job.data.pause = pause
        self.store.save(job)
        self.store.update_state(job.id, JobState.PAUSED, note=note)
        return self.store.get(job.id)

    def _unwind_pause_commit(self, job: Job) -> None:
        """Take the work-in-progress commit made for the push back out of the branch,
        leaving its changes staged: the phase carries on exactly as it was and is
        committed whole when its build passes. Only when nothing has been built on it."""
        pause = job.data.pause or {}
        wip, head = pause.get("wip"), pause.get("head")
        worktree = job.worktree_path
        if not wip or not head or worktree is None or g.head_commit(worktree) != wip:
            return
        g.reset_soft(worktree, head)
        job.data.pause = {**pause, "wip": None}
        self.store.save(job)

    def _refuse_if_moved(self, job: Job) -> None:
        worktree = job.worktree_path
        if worktree is None or not worktree.exists() or not g.has_remote(worktree):
            return
        try:
            head = self._host_of(job).remote_head(worktree, job.branch)
        except (SourceError, GitHostError):
            return  # the host cannot be asked; that is no reason to keep it paused
        if head is not None and not self._have(worktree, head):
            raise RemoteMoved(
                f"somebody pushed to {job.branch} while it was paused: carry on with a pull"
            )

    def _pull_paused(self, job: Job) -> int:
        """Merge what was pushed to the branch while it was paused. Returns how many
        commits that brought, 0 when nobody pushed anything new; raises ``CannotSync``
        and ``PullConflict`` with the checkout left as it was."""
        try:
            self._pushable(job)
        except CannotSync as exc:
            raise CannotSync(str(exc).replace("push", "pull")) from exc
        worktree = require_worktree(job)
        try:
            remote = self._host_of(job).fetch(worktree, job.branch)
        except (SourceError, GitHostError) as exc:
            raise CannotSync(str(exc)) from exc
        if remote is None:
            raise CannotSync(f"{job.branch} is not on the host: there is nothing to pull")
        if self._have(worktree, remote):
            return 0
        pause = dict(job.data.pause or {})
        before = g.head_commit(worktree)
        # what the paused phase had written and nobody pushed goes in as a commit of its
        # own, so the merge has two sides to put together rather than a dirty checkout
        g.stage_all(worktree)
        committed = g.commit(worktree, self._pause_commit_message(job))
        brought = len(g.commits(worktree, "HEAD", remote))
        conflicts = g.merge(worktree, f"refs/remotes/origin/{job.branch}")
        if conflicts:
            if committed:
                g.reset_soft(worktree, before)
            raise PullConflict(conflicts)
        base = pause.get("head") or before
        pause["wip"] = None
        pause["pulled"] = {"from": base, "to": g.head_commit(worktree), "commits": brought}
        job.data.pause = pause
        self.store.save(job)
        return brought

    def _building(self, job: Job, back: JobState) -> bool:
        """Whether it was paused with phases still to build, which is when what was
        pulled can change where it carries on."""
        if back is JobState.AWAITING_DECISION:
            back = JobState(job.data.resume_state or JobState.DEVELOPING.value)
        start = int((job.data.pause or {}).get("phase_index", job.data.phase_index))
        return back in BUILDING_STATES and start < len(self._phases(job))

    def _accept_reconcile(self, job: Job) -> str:
        """Apply the reading a person approved: the phases finished by hand are recorded
        as theirs and passed over, and the phase it carries on with starts afresh -- its
        specialist told what the people did, so it builds on that rather than over it."""
        from slipwright.schemas.job import InboxMessage

        found = job.data.reconcile or {}
        phases = self._phases(job)
        resume = min(int(found.get("resume_phase", 1)) - 1, len(phases))
        for outcome in found.get("phases", []):
            if int(outcome["phase"]) - 1 < resume:
                job.data.phase_outcomes[str(outcome["phase"])] = {
                    "by": "hand",
                    "evidence": outcome.get("evidence", ""),
                }
        job.data.phase_index = resume
        job.data.build_attempts = 0
        job.data.last_build_output = None
        job.data.review_rounds = 0
        job.data.review_violations = []
        job.data.qa_gate_fixes = 0
        job.data.qa_diagnosis = None
        job.data.phase_calls = 0
        job.data.phase_base_commit = None
        if resume < len(phases):
            current: dict[str, Any] = next(
                (o for o in found.get("phases", []) if int(o["phase"]) == resume + 1), {}
            )
            told = "People worked on this branch by hand while it was paused. " + str(
                found.get("summary", "")
            )
            if current.get("status") == "partial":
                told += (
                    f" Phase {resume + 1} is partly written already ({current.get('evidence')}):"
                    " finish it on what is there rather than writing it again."
                )
            job.data.inbox.append(InboxMessage(text=told.strip()))
        skipped = sorted(int(n) for n in job.data.phase_outcomes)
        if not skipped:
            return "approved: nothing was finished by hand"
        return f"approved: phase(s) {', '.join(map(str, skipped))} finished by hand"

    def _reconcile(self, job: Job) -> Job:
        """The Architect reads what people pushed while it was paused, phase by phase."""
        pause = job.data.pause or {}
        phases = self._phases(job)
        start = min(int(pause.get("phase_index", job.data.phase_index)), len(phases))
        worktree = require_worktree(job)
        base = (pause.get("pulled") or {}).get("from") or pause.get("head")
        if base is None:
            return self._fail(job, "reconcile: the commit it was paused on is not known")

        def outline(index: int) -> dict[str, Any]:
            phase = phases[index]
            return {
                "number": index + 1,
                "goal": phase.get("goal", ""),
                "domain": phase.get("domain"),
                "files": phase.get("files", []),
            }

        result = self._invoke(
            RoleName.ARCHITECT,
            reconcile.run,
            job,
            profile=job.profile or self.seed_for(job),
            finished=[outline(i) for i in range(start)],
            remaining=[outline(i) for i in range(start, len(phases))],
            commits=g.commits(worktree, base),
            diff=g.diff(worktree, base),
            jira=None,
            standards=None,
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, ReconcileResult)
        found = {f.number: f for f in result.output.phases}
        outcomes: list[dict[str, Any]] = []
        for index in range(start, len(phases)):
            finding = found.get(index + 1)
            outcomes.append(
                {
                    "phase": index + 1,
                    "goal": phases[index].get("goal", ""),
                    # a phase the answer left out was not shown to be done
                    "status": finding.status if finding else "untouched",
                    "evidence": finding.evidence if finding else "",
                }
            )
        # Only an unbroken run of finished phases is passed over. A phase somebody finished
        # after one they did not is built again over what is there: the phase before it may
        # yet change what it needs, and its specialist writes little when little is missing.
        resume = start
        while resume < len(phases) and outcomes[resume - start]["status"] == "done":
            resume += 1
        job.data.reconcile = {
            "from_phase": start + 1,
            "resume_phase": resume + 1,
            "phases": outcomes,
            "summary": result.output.summary,
            "commits": (pause.get("pulled") or {}).get("commits", 0),
        }
        self.store.save(job)
        skipped = resume - start
        if resume >= len(phases):
            where = "every phase left is finished; QA is next"
        else:
            where = f"carries on with phase {resume + 1}/{len(phases)}"
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_RECONCILE_APPROVAL,
            note=f"the Architect read what was pushed: {skipped} phase(s) finished by hand; "
            f"{where}",
            detail=json.dumps(job.data.reconcile, indent=2, ensure_ascii=False),
        )

    def retry(self, job_id: str, *, run: bool = True, feedback: str | None = None) -> Job:
        """Continue a failed job from the step it failed in. Counters that made it give up
        (build attempts, retries, review rounds, CI fixes) start over; everything built so
        far stays. Optional feedback reaches the next role through the inbox."""
        job = self.store.get(job_id)
        if job.state is not JobState.FAILED:
            raise NotAwaitingApproval(job)
        failure = next(
            (
                t
                for t in reversed(job.history)
                if t.to_state is JobState.FAILED and t.from_state is not JobState.FAILED
            ),
            None,
        )
        back = failure.from_state if failure is not None else JobState.BACKLOG
        if back in APPROVAL_STATES or back in (JobState.CREATED, JobState.FAILED, JobState.DONE):
            back = JobState.BACKLOG
        if back is JobState.BUILD_GATE:
            back = JobState.DEVELOPING  # the gate needs something new to test
        job.data.build_attempts = 0
        job.data.review_rounds = 0
        job.data.reject_rounds = 0
        job.data.ci_attempts = 0
        job.data.output_hashes = {}
        job.data.last_build_output = None
        if job.profile is not None:
            # roles are a human decision made in the seed profile: a permission or model
            # changed there after the failure is what the retry runs with
            job.profile = job.profile.model_copy(update={"roles": self.seed_for(job).roles})
        if feedback:
            from slipwright.schemas.job import InboxMessage

            job.data.inbox.append(InboxMessage(text=feedback))
        self.store.save(job)
        job = self.orchestrator.transition(
            job,
            back,
            note=f"retried: continuing with {back.value}" + (f" ({feedback})" if feedback else ""),
        )
        return self._run(job) if run else job

    def replan(self, job_id: str, note: str, *, run: bool = True) -> Job:
        """Try a failed development a different way: back to the plan, not to the step.

        ``retry`` continues from the step that failed, with the same plan and the same
        phase; when what failed is the plan itself -- a phase whose scope cannot fix the
        error, a task that was never written down -- retrying walks into the same wall.
        This is the other door. What the person wants tried instead goes to the Product
        Owner with the failure beside it, so the backlog can gain the task it was missing;
        the Architect then plans the phases again and both are approved as usual.

        It is a partial start-over, not a new development: the worktree, the branch and
        every commit already on it stay, and the phases are simply walked again from the
        first.
        """
        job = self.store.get(job_id)
        if job.state is not JobState.FAILED:
            raise NotAwaitingApproval(job)
        note = note.strip()
        if not note:
            raise EmptyApproval("say what should be tried instead")
        failure = next(
            (
                t
                for t in reversed(job.history)
                if t.to_state is JobState.FAILED and t.from_state is not JobState.FAILED
            ),
            None,
        )
        # the agents plan around the failure, so they are handed it: what stopped, where,
        # and the output that goes with it -- trimmed, since a build log is not a brief
        why = "" if failure is None else f"{failure.note or failure.from_state.value}"
        detail = (failure.detail or "")[-2000:] if failure is not None else ""
        parts = [
            "The last attempt failed and a person asked for this to be planned a different "
            "way rather than tried again.",
            f"What they want tried instead: {note}",
        ]
        if why:
            parts.append(f"What failed: {why}")
        if detail:
            parts.append(detail)
        job.data.feedback = "\n\n".join(parts)
        job.data.replan_from = None  # back to the backlog: everything is planned again
        job.data.phase_index = 0
        job.data.build_attempts = 0
        job.data.review_rounds = 0
        job.data.reject_rounds = 0
        job.data.ci_attempts = 0
        job.data.review_violations = []
        job.data.output_hashes = {}
        job.data.last_build_output = None
        job.data.qa_stage = 1
        if job.profile is not None:
            job.profile = job.profile.model_copy(update={"roles": self.seed_for(job).roles})
        self.store.save(job)
        job = self.orchestrator.transition(
            job, JobState.BACKLOG, note=f"planning it a different way: {note}"
        )
        return self._run(job) if run else job

    def undo_auto_approval(self, job_id: str, feedback: str) -> Job:
        """The human overrules the supervisor after the fact: the feedback reaches the
        next role through the inbox and the record shows the approval was undone."""
        job = self.store.get(job_id)
        record = job.data.supervision
        if not record or record.get("acted") != "auto" or record.get("undone"):
            raise NotAwaitingApproval(job)
        record["undone"] = True
        record["undo_feedback"] = feedback
        job.data.supervision = record
        from slipwright.schemas.job import InboxMessage

        job.data.inbox.append(
            InboxMessage(
                text=f"[the human overruled the supervisor's approval of the {record['gate']}] "
                f"{feedback}"
            )
        )
        self.store.save(job)
        self.store.update_state(job.id, job.state, note=f"undo: {feedback}")
        return self.store.get(job.id)

    def _notify_team(self, job: Job, lang: str = "tr") -> Job:
        """Tell the people on this gate's agent that it is theirs now.

        Written once per arrival: the marker carries how many times the job has entered
        this state, so QA's two stages are two letters, a rejected gate reached again is a
        new one, and a server that restarts mid-gate writes none. A job with nobody on the
        agent costs one query and writes nothing.
        """
        if job.state not in APPROVAL_STATES:
            return job
        visits = sum(
            1 for t in job.history if t.to_state is job.state and t.from_state is not job.state
        )
        marker = f"{job.state.value}:{visits}"
        if marker in job.data.notified:
            return job
        # the chat groups, and everybody linked in a chat who may decide this gate. A job
        # with no owner (a local install, the CLI) has nobody to mail but may still have
        # a Telegram group; the marker below keeps both to once per arrival.
        notify_gate(self, job)
        told: list[str] = []
        if job.owner_id is not None:
            project = ""
            if job.project_id:
                try:
                    project = self.store.get_project(job.project_id).name
                except ProjectNotFound:
                    project = ""
            try:
                told = self.teams().notify_gate(job, project_name=project, lang=lang)
            except Exception as exc:  # noqa: BLE001 - a gate must not wait on a mail server
                log.warning("job %s: could not notify the team: %s", job.id, exc)
        job = self.store.get(job.id)
        job.data.notified.append(marker)
        self.store.save(job)
        if told:
            self.store.update_state(job.id, job.state, note=f"waiting for {', '.join(told)}")
            return self.store.get(job.id)
        return job

    def _notify_webhook(self, job: Job, gate: str, record: dict[str, Any]) -> None:
        url = self.store.get_setting("notifications.webhook_url")
        if not url:
            return
        try:
            with httpx.Client(transport=self.http_transport, timeout=10.0) as client:
                client.post(
                    str(url),
                    json={
                        "event": "supervisor.auto_approved",
                        "job_id": job.id,
                        "project_id": job.project_id,
                        "request": job.request,
                        "title": job.title,
                        "gate": gate,
                        "confidence": record.get("confidence"),
                        "reasons": record.get("reasons", []),
                    },
                )
        except httpx.HTTPError as exc:  # a broken webhook never stops a job
            log.warning("webhook %s failed: %s", url, exc)

    # -- project brief (T11.1-T11.3) -------------------------------------------------------

    def brief(self, project_id: str) -> ProjectBrief:
        """What the agents have been told this project is; empty until it is written."""
        self.store.get_project(project_id)  # raises for an unknown project
        return self.store.get_brief(project_id)

    def brief_source(self, project: Project) -> Path | None:
        """The folder the brief is read from, or None when there is nothing to read yet.

        Normally the project's own checkout. But a development works on a branch in a
        worktree of its own and nothing merges it for you: a project opened from an empty
        repository still has only the seeded README on ``main`` after its agents have
        written a whole application. Asked about that project, this said "the repository
        is empty" and offered to interview the person about a product that already
        existed. So when the checkout holds no code, the newest development that has some
        is read instead -- the code that was actually written, not the plan for it.
        """
        here = Path(project.repo_path) if project.repo_path is not None else None
        if here is not None and here.is_dir() and not discovery.repository_is_empty(here):
            return here
        for job in sorted(self.store.list(project.id), key=lambda j: j.created_at, reverse=True):
            tree = job.worktree_path
            if tree is not None and tree.is_dir() and not discovery.repository_is_empty(tree):
                return tree
        return None

    def brief_kind(self, project: Project) -> str:
        """``intake`` when there is no code anywhere to read, else ``analysis``."""
        return "analysis" if self.brief_source(project) is not None else "intake"

    def _brief_failed(self, project_id: str, why: str) -> ProjectBrief:
        brief = self.store.get_brief(project_id)
        brief.state = BriefState.FAILED
        brief.error = why
        return self.store.save_brief(brief)

    def start_analysis(self, project_id: str) -> ProjectBrief:
        """Record that the analysis is working; ``execute_analysis`` does it."""
        self.store.get_project(project_id)
        with self._brief_locks[project_id]:
            brief = self.store.get_brief(project_id)
            if brief.state is BriefState.RUNNING:
                raise BriefIsRunning(project_id)
            brief.state = BriefState.RUNNING
            brief.error = ""
            return self.store.save_brief(brief)

    def execute_analysis(self, project_id: str) -> ProjectBrief:
        """Read the checkout and propose the brief. Never raises: a failure is a state."""
        project = self.store.get_project(project_id)
        checkout = self.brief_source(project)
        if checkout is None:
            return self._brief_failed(project_id, f"project {project_id} has no code to read")
        try:
            result = discovery.analyse(
                checkout,
                self.project_profile(project),
                language=project.language,
                provider=self.provider_for(project.owner_id),
                timeout_s=self.timeout_s,
                attachments=self.project_attachments(project.id),
            )
        except Exception as exc:  # noqa: BLE001 - a broken provider must not kill the request
            log.exception("analysis failed for project %s", project_id)
            return self._brief_failed(project_id, f"{type(exc).__name__}: {exc}")
        if not result.ok:
            assert result.error is not None
            return self._brief_failed(project_id, result.error.message)
        assert isinstance(result.output, AnalysisResult)
        brief = self.store.get_brief(project_id)
        brief.items = [
            BriefItem(category=d.category, title=d.title, detail=d.detail, source="analysis")
            for d in result.output.items
        ]
        brief.summary = result.output.summary
        brief.state = BriefState.PROPOSED
        brief.error = ""
        return self.store.save_brief(brief)

    def start_intake(self, project_id: str, answers: dict[str, str] | None = None) -> ProjectBrief:
        """Record the answers to the round on the table (if any) and claim the next one."""
        self.store.get_project(project_id)
        with self._brief_locks[project_id]:
            brief = self.store.get_brief(project_id)
            if brief.state is BriefState.RUNNING:
                raise BriefIsRunning(project_id)
            intake = brief.intake or Intake()
            if answers:
                round_ = intake.current
                if round_ is None:
                    raise ValueError("there are no questions to answer yet")
                for question in round_.questions:
                    if question.id in answers:
                        question.answer = answers[question.id].strip()
            brief.intake = intake
            brief.state = BriefState.RUNNING
            brief.error = ""
            return self.store.save_brief(brief)

    def execute_intake(self, project_id: str) -> ProjectBrief:
        """Ask the next round, or finish with the story. Never raises."""
        project = self.store.get_project(project_id)
        brief = self.store.get_brief(project_id)
        intake = brief.intake or Intake()
        try:
            result = discovery.interview(
                intake,
                self.project_profile(project),
                project_name=project.name,
                description=project.description,
                language=project.language,
                provider=self.provider_for(project.owner_id),
                timeout_s=self.timeout_s,
                attachments=self.project_attachments(project.id),
            )
        except Exception as exc:  # noqa: BLE001 - a broken provider must not kill the request
            log.exception("intake failed for project %s", project_id)
            return self._brief_failed(project_id, f"{type(exc).__name__}: {exc}")
        if not result.ok:
            assert result.error is not None
            return self._brief_failed(project_id, result.error.message)
        assert isinstance(result.output, IntakeResult)
        output = result.output
        brief = self.store.get_brief(project_id)
        intake = brief.intake or Intake()
        # the last round has to finish, whatever the model would rather do
        forced = len(intake.rounds) >= intake.max_rounds
        if output.ready or (forced and output.items and output.story.strip()):
            intake.done = True
            intake.story = output.story.strip()
            brief.items = [
                BriefItem(category=d.category, title=d.title, detail=d.detail, source="intake")
                for d in output.items
            ]
        else:
            intake.rounds.append(
                IntakeRound(
                    number=len(intake.rounds) + 1,
                    questions=[
                        IntakeQuestion(question=q.question, why=q.why, hint=q.hint)
                        for q in output.questions
                    ],
                )
            )
        brief.intake = intake
        brief.summary = output.summary
        brief.state = BriefState.PROPOSED
        brief.error = ""
        return self.store.save_brief(brief)

    # -- attachments: files the person gave the agents (slipwright/attachments.py) -------

    def attach(
        self, project_id: str, name: str, data: bytes, *, scope: Scope = "project"
    ) -> Attachment:
        """Take a file in: refuse what cannot be read or will not fit, take the text out,
        keep it. Reading it with a model is ``execute_reading``, afterwards."""
        project = self.store.get_project(project_id)
        if len(data) > attached.MAX_BYTES:
            raise attached.TooLarge(len(data))
        self.store.forget_drafts(project_id, attached.DRAFT_TTL)
        if self.store.count_attachments(project_id) >= attached.MAX_PER_PROJECT:
            raise attached.TooMany()
        self.quotas.check_attachment(project.owner_id, len(data))
        media_type = attached.sniff(data, name)
        text, pages = attached.extract(data, media_type)
        return self.store.add_attachment(
            project_id=project_id,
            owner_id=project.owner_id,
            name=attached.clean_name(name),
            media_type=media_type,
            data=data,
            text=text,
            pages=pages or attached.page_count(data, media_type),
            scope=scope,
        )

    def execute_reading(self, attachment_id: str) -> Attachment | None:
        """Have the Product Owner's model read the file once, on its owner's keys. Never
        raises: a file that could not be read is a state, and its text still reaches the
        agents without the reading.

        The pictures go first. A model that cannot see refuses them, and is asked again
        with the text alone -- a document is still worth reading without its figures --
        and the reading says so, so nobody takes a description of a screen nobody looked
        at for one somebody did."""
        try:
            found, data = self.store.attachment_data(attachment_id)
            project = self.store.get_project(found.project_id)
        except KeyError:  # the file, or its project, deleted before it was read
            return None
        self.store.set_reading(attachment_id, "reading")
        try:
            text = self.store.attachment_text(attachment_id)
            images = attached.pictures(data, found.media_type, name=found.name)
            if not text and not images:
                return self.store.set_reading(
                    attachment_id, "failed", Reading(note="nothing in this file could be read")
                )

            def ask(shown: list[Any]) -> RoleResult:
                return reader.read(
                    found,
                    text,
                    shown,
                    self.project_profile(project),
                    language=project.language,
                    provider=self.provider_for(project.owner_id),
                    timeout_s=self.timeout_s,
                )

            note = ""
            calls: list[dict[str, Any]] = []
            result = ask(images)
            calls.append(self._reading_call(result))
            if not result.ok and images and text and may_be_blind(result):
                note = "read from its text alone: the model would not take the pictures"
                result = ask([])
                calls.append(self._reading_call(result))
            if not result.ok:
                assert result.error is not None
                return self.store.set_reading(
                    attachment_id, "failed", Reading(note=result.error.message, calls=calls)
                )
            reading = attached.reading_from(result.output, note)
            reading.calls = calls
            return self.store.set_reading(attachment_id, "done", reading)
        except Exception as exc:  # noqa: BLE001 - a broken file must not kill the request
            log.exception("reading attachment %s failed", attachment_id)
            return self.store.set_reading(
                attachment_id, "failed", Reading(note=f"{type(exc).__name__}: {exc}")
            )

    def _reading_call(self, result: RoleResult) -> dict[str, Any]:
        """One reading call as the cost panel reads a job's calls: what answered, what it
        took, and what that cost at the price of the model that actually answered."""
        usage = result.usage
        price = self.price_of(result.provider, result.model)
        cost = (
            price.cost(usage.input_tokens or 0, usage.output_tokens or 0)
            if price and usage
            else None
        )
        return {
            "role": RoleName.PO.value,
            "model": result.model,
            "provider": result.provider,
            "attempts": result.attempts,
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "cost_usd": round(cost, 6) if cost is not None else None,
            "ok": result.ok,
            "error": result.error.kind.value if result.error else None,
            "at": utcnow().isoformat(),
        }

    def screens_for(self, job: Job) -> list[Any]:
        """The attached screens, drawn, for the Designer to look at: every picture that was
        read as screens, and the pages of a PDF the reading found a screen on. A file that
        could not be read is shown whole if it is a picture -- a screenshot with no reading
        is still a screenshot."""
        if job.project_id is None:
            return []
        shown: list[Any] = []
        for a in self.store.list_attachments(job.project_id, job_id=job.id):
            read = a.reading if a.reading_state == "done" else None
            if read is not None and read.kind == "screens":
                pages = sorted({s.page for s in read.screens if s.page})
            elif read is None and a.is_picture:
                pages = []  # an unread PDF could be anything; its text reaches the agents
            else:
                continue
            _, data = self.store.attachment_data(a.id)
            shown += attached.pictures(
                data,
                a.media_type,
                name=a.name,
                pages=pages or None,
                limit=attached.DESIGN_PICTURES - len(shown),
            )
            if len(shown) >= attached.DESIGN_PICTURES:
                break
        return shown[: attached.DESIGN_PICTURES]

    def attachments_for(self, job: Job, *, whole: bool = True) -> dict[str, Any] | None:
        """The ``attachments`` section of a role's context: the project's files and this
        development's. ``whole`` gives the text of each as well as its reading -- what
        the Product Owner, who turns them into the backlog, needs; the roles after it
        build from the backlog and are given the reading alone."""
        if job.project_id is None:
            return None
        found = self.store.list_attachments(job.project_id, job_id=job.id)
        texts = {a.id: self.store.attachment_text(a.id) for a in found} if whole else None
        return attached.for_agents(found, texts)

    def project_attachments(self, project_id: str) -> dict[str, Any] | None:
        """The project's own files, whole, for the brief: there is no development yet."""
        found = self.store.list_attachments(project_id, scopes=("project",))
        return attached.for_agents(found, {a.id: self.store.attachment_text(a.id) for a in found})

    def save_brief(self, project_id: str, edit: BriefEdit) -> ProjectBrief:
        """Take the person's edits. Approving is what lets an agent read any of it."""
        self.store.get_project(project_id)
        with self._brief_locks[project_id]:
            brief = self.store.get_brief(project_id)
            if brief.state is BriefState.RUNNING:
                raise BriefIsRunning(project_id)
            brief.items = list(edit.items)
            if edit.approve:
                if not brief.items:
                    raise EmptyApproval("a brief with no items tells the agents nothing")
                brief.state = BriefState.READY
                brief.approved_at = utcnow()
            else:
                brief.state = BriefState.PROPOSED
                brief.approved_at = None
            brief.error = ""
            return self.store.save_brief(brief)

    def take_pending_request(self, project_id: str) -> Job | None:
        """The first development the project was made with, once the brief is ready.

        The wizard's last step asks what the agents should build. Starting it there meant
        the brief never ran, and a job whose brief is not ready is handed an empty one --
        the whole team then plans and builds without knowing what the project is. So the
        request waits on the project and is claimed here, exactly once: under the brief's
        own lock, and cleared before the caller can ask again.
        """
        with self._brief_locks[project_id]:
            project = self.store.get_project(project_id)
            if not project.pending_request.strip() or not self.store.get_brief(project_id).ready:
                return None
            job = self.create_job(
                project.pending_request, project_id=project_id, title=project.pending_title
            )
            self.store.update_project(
                project.model_copy(update={"pending_request": "", "pending_title": ""})
            )
            return job

    def rename_job(self, job: Job, title: str) -> Job:
        """Give a development another name. Only the name: the request is the agents'
        brief and stays as it was asked, and the branch keeps the name git already has
        (``Job.branch``) -- an open pull request cannot move to another one."""
        name = title.strip()
        if not name:
            raise ValueError("a development needs a name")
        job.title = name[:TITLE_MAX]
        return self.store.save(job)

    # -- test runs -----------------------------------------------------------------------

    def project_profile(self, project: Project) -> Profile:
        """Best known profile for a project's main checkout: its own, else the newest
        approved job profile, else the engine's seed."""
        if project.profile is not None:
            return project.profile
        for job in reversed(self.store.list(project.id)):
            if job.profile is not None:
                return job.profile
        return self.seed_profile

    def start_test_run(self, project_id: str, job_id: str | None = None) -> TestRun:
        """Record a pending run; ``execute_test_run`` does the work (usually in the background)."""
        project = self.store.get_project(project_id)
        if job_id is not None:
            job = self.store.get(job_id)
            if job.project_id != project.id:
                raise ValueError(f"job {job_id} does not belong to project {project_id}")
            profile = job.profile or self.project_profile(project)
            cwd = job.worktree_path
            note = f"job {job.id}: {job.title}"
        else:
            profile = self.project_profile(project)
            cwd = project.repo_path
            note = "main checkout"
        run = TestRun(
            project_id=project.id,
            job_id=job_id,
            command=profile.test_cmd,
            cwd=cwd or Path("."),
            note=note,
        )
        if cwd is None or not cwd.is_dir():
            run.status = TestRunStatus.ERROR
            run.finished_at = utcnow()
            run.note = f"no checkout to run in ({cwd})"
        return self.store.create_test_run(run)

    def execute_test_run(self, run_id: str) -> TestRun:
        run = self.store.get_test_run(run_id)
        if run.terminal:
            return run
        with self._checkout_locks[str(run.cwd)]:
            timeout = self.gate_timeout_s if self.gate_timeout_s is not None else GATE_TIMEOUT_S
            try:
                code, output = run_command(run.command, run.cwd, timeout, self.runner)
            except Exception as exc:  # noqa: BLE001 - recorded on the run, never raised
                code, output = -1, f"{type(exc).__name__}: {exc}"
                run.status = TestRunStatus.ERROR
            else:
                run.status = TestRunStatus.PASSED if code == 0 else TestRunStatus.FAILED
            run.exit_code = code
            run.finished_at = utcnow()
            run.output_path = self._write_run_output(run, f"$ {run.command}\n{output}")
        return self.store.update_test_run(run)

    def record_gate_run(self, job: Job, gate: GateResult) -> TestRun:
        """Keep a build-gate execution in the same list as on-demand runs."""
        profile = self._profile(job)
        phase = job.data.phase_index + 1
        finished = utcnow()
        run = TestRun(
            project_id=job.project_id or "",
            job_id=job.id,
            source=TestRunSource.GATE,
            command=f"{profile.build_cmd} && {profile.test_cmd}",
            cwd=require_worktree(job),
            status=TestRunStatus.PASSED if gate.ok else TestRunStatus.FAILED,
            # the gate timed itself: without this a gate run looks instant in the list
            started_at=finished - timedelta(seconds=gate.seconds),
            finished_at=finished,
            exit_code=0 if gate.ok else 1,
            note=f"build gate, phase {phase}",
            phase=phase,
        )
        run.output_path = self._write_run_output(run, gate.output)
        return self.store.create_test_run(run)

    def test_run_output(self, run: TestRun) -> str:
        if run.output_path is None or not run.output_path.is_file():
            return ""
        return run.output_path.read_text(encoding="utf-8", errors="replace")

    def _write_run_output(self, run: TestRun, text: str) -> Path:
        self.test_runs_root.mkdir(parents=True, exist_ok=True)
        path = self.test_runs_root / f"{run.id}.log"
        path.write_text(text, encoding="utf-8", errors="replace")
        return path

    # -- driver --------------------------------------------------------------------------

    def _run(self, job: Job) -> Job:
        """Run phase handlers until the job stops at a gate or ends.

        One job runs in one thread at a time; a second caller waits, then re-reads the
        persisted state so it never acts on a stale view.
        """
        with self._locks[job.id]:
            job = self._jira_reconcile(self.store.get(job.id))
            # whoever moved it -- the web page, the API, somebody else's chat -- the
            # questions still open in people's chats about where it was are now moot
            settle_prompts(self, job)
            if self.builder_ready(job):
                # the one wait nobody approves: a machine that can build what is left is
                # here now -- connected, or this server itself started somewhere that can
                job = self.orchestrator.transition(
                    job,
                    JobState(job.data.builder_resume or JobState.DEVELOPING.value),
                    note=f"a builder for {', '.join(job.data.waiting_platforms)} is here; "
                    "carrying on",
                )
                job.data.waiting_platforms = []
                job.data.builder_resume = None
                job = self.store.save(job)
            # a re-plan asked for while it ran is not a stop: the development goes on, to
            # the Architect, so the loop is entered again after one
            while True:
                while job.state in WORKING_STATES:
                    halt = self._stopping.pop(job.id, None)
                    if halt is not None and halt.kind == "redirect":
                        job = self._redirected(job, halt)
                        continue
                    if halt is not None:
                        return self._halt(job, halt, "nothing further was started")
                    handler = self.handlers.get(job.state)
                    if handler is None:
                        log.warning("no handler for state %s; job %s left as is", job.state, job.id)
                        return job
                    before = job.state
                    try:
                        job = handler(job)
                    except _Stopped:
                        halt = self._stopping.pop(job.id, None) or _Halt("cancel")
                        if halt.kind == "redirect":
                            job = self._redirected(self.store.get(job.id), halt)
                            continue
                        return self._halt(
                            self.store.get(job.id), halt, "its next call was not made"
                        )
                    except Exception as exc:  # noqa: BLE001 - a crashed phase fails the job
                        log.exception("job %s: %s phase crashed", job.id, before.value)
                        job = self._fail(
                            job,
                            f"{before.value} crashed: {type(exc).__name__}: {exc}",
                            detail=traceback.format_exc(),
                        )
                        return self._notify_outcome(self._jira_reconcile(job))
                    if job.state is before:  # a handler must always move the job
                        raise RuntimeError(
                            f"handler for {before.value} did not change job {job.id}"
                        )
                    job = self._jira_reconcile(job)
                    if job.state in APPROVAL_STATES:
                        job = self._supervise(job)  # may approve: then the loop goes on
                        job = self._notify_team(job)
                halt = self._stopping.pop(job.id, None)
                if halt is not None and not job.is_terminal:
                    if halt.kind == "redirect":
                        # the step it was on ended at a gate -- a decision, a review
                        job = self._redirected(job, halt)
                        if job.state in WORKING_STATES:
                            continue
                    else:
                        # the step it was stopped in ended at a gate: it was told to stop, so
                        # it does not sit there waiting for somebody to approve its next spend
                        job = self._halt(job, halt, "nothing further was started")
                break
            # what questions answered while it ran cost, now that nothing else is writing
            with contextlib.suppress(ValueError, JobNotFound):
                self._bill_answers(self.store.get(job.id))
            job = self._notify_outcome(job)
        # outside the job's lock: reading the code it wrote is a model call, and a job
        # that has finished must not look busy while it happens
        self._learn_from(job)
        return job

    def _steered(self, job: Job, role: RoleName, phase: int) -> bool:
        """Whether somebody wrote to ``role`` about ``phase`` and it has not read it yet.

        Only what was written to that agent counts. A message for whoever runs next -- the
        old steering box -- is read by whoever does; holding a green phase back for it
        would spend a specialist call on a note that may not be about the code at all."""
        return any(
            m.pending and m.role == role.value and m.phase in (None, phase)
            for m in self.store.inbox(job.id)
        )

    def _supersede(self, job_id: str, halt: _Halt) -> None:
        """Ask the running development for ``halt``. A re-plan it was asked for earlier and
        has not reached yet is dropped, and says so: a stop, a pause or a newer re-plan
        means it will never be carried out."""
        earlier = self._stopping.get(job_id)
        if earlier is not None and earlier.kind == "redirect" and earlier.message:
            self.store.set_message_status(earlier.message, "dropped")
        self._stopping[job_id] = halt

    def _redirected(self, job: Job, halt: _Halt) -> Job:
        """Carry out a re-plan asked for while the development was running."""
        message = self.store.get_message(halt.message) if halt.message else None
        if message is None:
            return job
        job = self._replan_now(job, message, by=halt.by)
        self._told(job)
        return job

    def _halt(self, job: Job, halt: _Halt, why: str) -> Job:
        """Carry out a stop or a pause asked for while the development was running."""
        if halt.kind == "pause":
            return self._enter_pause(job, halt)
        job = self.orchestrator.transition(job, JobState.CANCELLED, note=f"stopped: {why}")
        return self._notify_outcome(job)

    def _learn_from(self, job: Job) -> None:
        """Read what a finished development built, so the next one knows the project.

        A development leaves its work on its own branch and nothing merges it, so a
        project opened from an empty repository still looked empty afterwards and its
        brief stayed blank -- every later development then planned and built knowing
        nothing about what was already there. The Architect reads the code that now
        exists and proposes the brief, for a person to approve.

        Only a brief nobody has written yet is filled. Once it holds items they are
        somebody's: corrected, deleted, approved. Those are replaced when the person
        asks for it on the page, never behind their back.
        """
        if job.state is not JobState.DONE or job.project_id is None:
            return
        try:
            if self.store.get_brief(job.project_id).items:
                return
            self.start_analysis(job.project_id)
        except (ProjectNotFound, BriefIsRunning):
            return
        # the model call is the job's owner's, like every other this development made
        self.for_user(job.owner_id).execute_analysis(job.project_id)

    def _notify_outcome(self, job: Job) -> Job:
        """Tell the groups that asked that a development finished or stopped. Once per
        arrival, on the same ``notified`` markers the gate letters use, so a restart does
        not announce a failure twice and a retried one that fails again does."""
        if job.state not in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
            return job
        visits = sum(
            1 for t in job.history if t.to_state is job.state and t.from_state is not job.state
        )
        marker = f"{job.state.value}:{visits}"
        if marker in job.data.notified:
            return job
        job.data.notified.append(marker)
        job = self.store.save(job)
        error = None
        if job.state in (JobState.FAILED, JobState.CANCELLED):
            last = next((t for t in reversed(job.history) if t.to_state is job.state), None)
            error = last.note if last else None
        kind = {
            JobState.DONE: "done",
            JobState.FAILED: "failed",
            JobState.CANCELLED: "cancelled",
        }[job.state]
        notify_outcome(self, job, kind, error)
        if job.state is JobState.FAILED:
            self._mail_failure(job, error)
        return job

    def _mail_failure(self, job: Job, error: str | None, lang: str = "tr") -> None:
        """Write to the owner that their development stopped -- when there is a mail
        server to write with. Unlike a gate letter this goes to the owner: nobody else may
        retry it, and they are the one not looking at the page when it happens.

        Only over SMTP. The outbox stands in for mail so that signing up works before a
        server is configured; filling it with news nobody will read helps nobody.
        """
        self._mail_owner(
            job,
            "the failure",
            lambda link, project, name: failed_letter(
                lang,
                link=link,
                request=job.title,
                project=project,
                error=(error or "")[:600],
                name=name,
            ),
        )

    def _mail_builder_wait(self, job: Job, lang: str = "tr") -> None:
        """Write to the owner that the development waits for a machine to build its apps.
        Theirs to lend, so theirs to be told; the link is to the page that pairs one."""
        root = (self.mail_settings().base_url or "").rstrip("/")
        self._mail_owner(
            job,
            "the wait for a builder",
            lambda link, project, name: builder_letter(
                lang,
                link=link,
                pair_link=f"{root}/settings/workers",
                request=job.title,
                project=project,
                platforms=list(job.data.waiting_platforms),
                name=name,
            ),
        )

    def _mail_owner(self, job: Job, about: str, write: Callable[[str, str, str], Letter]) -> None:
        """A letter to the job's owner, over SMTP only and never for the example project;
        ``write(link, project, name)`` words it. A lost letter changes nothing."""
        if job.owner_id is None or not self.mail_settings().configured:
            return
        try:
            user = self.raw_store.get_user(job.owner_id)
            if not user.email or user.email_verified_at is None:
                return
            project = ""
            if job.project_id:
                with contextlib.suppress(ProjectNotFound):
                    found = self.store.get_project(job.project_id)
                    if found.is_demo:
                        return
                    project = found.name
            root = (self.mail_settings().base_url or "").rstrip("/")
            path = f"/projects/{job.project_id}/jobs/{job.id}" if job.project_id else "/"
            letter = write(f"{root}{path}", project, user.username)
            self.mailer().send(user.email, letter.subject, letter.body)
        except Exception as exc:  # noqa: BLE001 - a lost letter must not change the outcome
            log.warning("job %s: could not mail the owner about %s: %s", job.id, about, exc)

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

    def job_result(self, job_id: str) -> JobResult:
        """What the development produced: its branch, the commits and files on it, and
        how to get them. Reads git, so it stays true even after a restart; when the
        worktree is gone the branch in the checkout is read instead."""
        job = self.store.get(job_id)
        project = self._project_of(job)
        checkout = project.repo_path if project and project.repo_path else job.repo_path
        base_branch = self.base_branch_of(project)
        result = JobResult(
            job_id=job.id,
            state=job.state,
            branch=job.branch,
            checkout=str(checkout),
            base_branch=base_branch,
            merged=False,
            pr_url=job.data.pr_url,
            summary=self._result_summary(job),
        )
        repo = job.worktree_path if job.worktree_path and job.worktree_path.is_dir() else checkout
        base = job.data.base_commit
        if base is None or not (repo / ".git").exists():
            result.problem = "the branch is no longer in the checkout"
            return result
        head = job.branch if repo == checkout else "HEAD"
        try:
            if repo == checkout and not g.branch_exists(checkout, job.branch):
                result.problem = "the branch is no longer in the checkout"
                return result
            result.commits = [
                Commit(sha=sha, subject=subject) for sha, subject in g.commits(repo, base, head)
            ]
            result.files = [
                ChangedFile(path=path, added=added, removed=removed)
                for path, added, removed in g.numstat(repo, base, head)
            ]
            tip = g.run(repo, "rev-parse", head).stdout.strip()
            result.merged = g.branch_exists(checkout, base_branch) and g.contains(
                checkout, tip, base_branch
            )
        except g.GitError as exc:
            result.problem = exc.stderr.strip() or "git could not read the branch"
            return result
        result.added = sum(f.added for f in result.files)
        result.removed = sum(f.removed for f in result.files)
        if not result.merged and result.commits:
            result.merge_command = f"git -C {checkout} merge {job.branch}"
        return result

    @staticmethod
    def _result_summary(job: Job) -> str:
        """The DevOps write-up when there is one, else the last thing that happened."""
        for transition in reversed(job.history):
            note = transition.note or ""
            if transition.to_state is JobState.DONE and transition.detail:
                return transition.detail
            if note.startswith("devops:") and transition.detail:
                return transition.detail
        last = job.history[-1] if job.history else None
        return (last.note or "") if last else ""

    def _branch_diff(self, job: Job) -> str:
        worktree = require_worktree(job)
        base = job.data.base_commit
        if base is None:
            return "(base commit unknown)"
        return g.diff(worktree, base) or "(no changes)"

    def _branch_files(self, job: Job) -> str:
        """The branch's changed files with their line counts, not the lines themselves:
        all a pull request description needs beside the draft (T15.2)."""
        worktree = require_worktree(job)
        base = job.data.base_commit
        if base is None:
            return "(base commit unknown)"
        return g.changed_files(worktree, base) or "(no changes)"

    def _invocation_failed(self, job: Job, result: RoleResult) -> Job:
        assert result.error is not None
        if result.error.kind is InvokeErrorKind.BUDGET:
            return self._fail(job, f"budget exhausted: {result.error.message}")
        if result.error.kind is InvokeErrorKind.LOOP:
            return self._ask_human(job, f"loop detected: {result.error.message}")
        if result.error.kind is InvokeErrorKind.PHASE_BUDGET:
            return self._phase_budget_stop(job, result.error.message)
        attempts = f" after {result.attempts} attempts" if result.attempts > 1 else ""
        return self._fail(
            job,
            f"{result.role.value} failed: {result.error.kind.value}{attempts}",
            detail=result.error.message,
        )

    def _ask_human(self, job: Job, note: str, detail: str | None = None) -> Job:
        """Stop at the decision gate; approve resumes the interrupted state, reject
        resumes it with feedback in the inbox."""
        job.data.resume_state = job.state.value
        self.store.save(job)
        return self.orchestrator.transition(
            job, JobState.AWAITING_DECISION, note=note, detail=detail
        )

    # -- a re-plan from where it failed ------------------------------------------------------

    def _replan_from(
        self, job: Job, index: int, why: str, *, note: str, detail: str | None = None
    ) -> Job:
        """Send the plan back to the Architect from phase ``index`` on, keeping the ones
        before it.

        A supervisor's re-plan used to start the development over: the Architect wrote all
        eight phases again, the Designer drew every screen again, and phases one to seven,
        built and committed, were built a second time -- to fix phase eight. The phases
        before the failing one are kept; the Architect replaces the rest, and may add a
        phase that changes kept code when that is where the cause is.
        """
        self._drop_ahead(job)
        job.data.replan_from = index
        job.data.phase_index = index
        job.data.feedback = why
        job.data.build_attempts = 0
        job.data.qa_gate_fixes = 0
        job.data.qa_diagnosis = None
        job.data.last_build_output = None
        job.data.review_violations = []
        job.data.review_rounds = 0
        job.data.phase_calls = 0
        job.data.decision_kind = None
        job.data.recommendation = None
        job.data.recommendation_route = None
        self.store.save(job)
        return self.orchestrator.transition(job, JobState.ARCHITECTURE, note=note, detail=detail)

    def replan_phase(
        self, job_id: str, note: str, *, by: str | None = None, run: bool = True
    ) -> Job:
        """At a phase-budget stop: have this phase planned again, with the person's words.

        "Split it in three" is the Architect's to do, not the developer's: sent to the
        developer it was read as one more try of the same phase."""
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_DECISION or job.data.decision_kind != "phase_budget":
            raise NotAwaitingApproval(job)
        if not note.strip():
            raise EmptyApproval("say what the new plan for this phase should do")
        index = job.data.phase_index
        job.data.resume_state = None
        job = self._replan_from(
            job,
            index,
            f"phase {index + 1} spent its budget of model calls without getting through. "
            f"What to plan instead, from a person: {note.strip()}",
            note=f"re-plan from phase {index + 1}" + (f" by {by}" if by else "") + f": {note}",
        )
        return self._run(job) if run else job

    # -- one budget for a phase (T15.5) -------------------------------------------------------

    @staticmethod
    def _phase_number(job: Job) -> int | None:
        """The phase (1-based) a call in this state is made for, or None outside one. The
        review runs after the phase is committed, when the index has moved on."""
        if job.state in (JobState.DEVELOPING, JobState.BUILD_GATE):
            return job.data.phase_index + 1
        if job.state is JobState.REVIEW and job.data.phase_index >= 1:
            return job.data.phase_index
        return None

    def _phase_over_budget(self, job: Job) -> str | None:
        """Why the next call of this phase is not made, or None.

        Parts, build attempts, fix rounds and triage each stop on their own, and one phase
        could still take a dozen calls between them: phase 5 of an Android development took
        six developer calls and three QA calls. Every call of a phase counts here. Only a
        call that would build or fix is stopped -- the review runs on a committed phase,
        and stopping it half-way would leave nowhere sound to go back to; it counts, and
        the fix it asks for is what stops.
        """
        limit = self.budget_for(job).max_phase_calls
        phase = self._phase_number(job)
        if limit is None or phase is None or job.state is JobState.REVIEW:
            return None
        spent = job.data.phase_calls if job.data.phase_calls_for == phase else 0
        if spent < limit:
            return None
        return f"phase {phase} took {spent} model calls (limit {limit})"

    def _phase_budget_stop(self, job: Job, why: str, *, park: bool = True) -> Job:
        """Stop at the decision gate with a recommendation, and wait for words.

        QA reads what the phase went through and says what to do; the person accepts that
        as written or writes their own, and the text reaches the developer as the
        instruction for the next attempt, on a fresh budget. A plain "continue" is not
        offered: it would spend another budget the same way.
        """
        if park:
            parked = self._park(job, why)
            if parked is not None:
                return parked
        phases = self._phases(job)
        index = job.data.phase_index
        phase = phases[index] if index < len(phases) else {}
        attempts = self._phase_attempts(job)
        recommendation: str | None = None
        result = self._invoke(
            RoleName.QA,
            qa.recommend,
            job,
            profile=job.profile or self.seed_for(job),
            phase=phase,
            attempts=attempts,
            over_phase_budget=True,
        )
        route: str | None = None
        if result.ok and isinstance(result.output, Recommendation):
            recommendation = result.output.recommendation
            route = result.output.route
        job = self.store.get(job.id)
        job.data.decision_kind = "phase_budget"
        job.data.recommendation = recommendation
        job.data.recommendation_route = route
        job = self._ask_human(
            job,
            f"{why}; QA recommends what to do next -- write the instruction for the next try",
            detail="\n\n".join(attempts[-8:]) or None,
        )
        # whatever stopped it, the next attempt is the developer's, and the answer with it
        job.data.resume_state = JobState.DEVELOPING.value
        self.store.save(job)
        return job

    def _phase_attempts(self, job: Job) -> list[str]:
        """What this phase went through, oldest first: the notes written since it began,
        each with the start of its detail."""
        phase = self._phase_number(job)
        mark = f"phase {phase}/"
        start = next((i for i, t in enumerate(job.history) if t.note and mark in t.note), 0)
        lines: list[str] = []
        for t in job.history[start:]:
            if not t.note:
                continue
            text = t.note
            if t.detail:
                text += "\n" + t.detail[:1200]
            lines.append(text)
        return lines[-20:]

    # -- budgets (T9.7) ----------------------------------------------------------------------

    def budget_for(self, job: Job) -> BudgetSettings:
        project = self._project_of(job)
        return BudgetSettings() if project is None else project.budget

    def _budget_problem(self, job: Job) -> str | None:
        budget = self.budget_for(job)
        if budget.max_invocations is not None and job.data.invocations >= budget.max_invocations:
            return f"{job.data.invocations} model calls (limit {budget.max_invocations})"
        if budget.max_tokens is not None and job.data.tokens_used >= budget.max_tokens:
            return f"{job.data.tokens_used} tokens used (limit {budget.max_tokens})"
        if budget.max_wall_clock_s is not None and job.history:
            elapsed = (utcnow() - job.history[0].at).total_seconds()
            if elapsed >= budget.max_wall_clock_s:
                return f"{elapsed:.0f}s elapsed (limit {budget.max_wall_clock_s}s)"
        return None

    @staticmethod
    def _output_key(job: Job, role: RoleName) -> str | None:
        """Where the loop check applies: producers (PO, architect, specialists, QA, DevOps)
        within one phase. Judges (the reviewer, the supervisor) may well say the same
        thing twice; the flows around them are bounded on their own."""
        if role is RoleName.SUPERVISOR or job.state is JobState.REVIEW:
            return None
        # a review round changes the specialist's input (the violations), so each round
        # is its own series; build-gate retries are not (same failure, same fix = stuck)
        return f"{role.value}:{job.data.phase_index}:{job.state.value}:r{job.data.review_rounds}"

    def _invoke(
        self, role: RoleName, run: Callable[..., RoleResult], job: Job, **kw: Any
    ) -> RoleResult:
        """Every model call goes through here: run the role, then drain the inbox.

        Messages pending at call time were injected into the role's context by
        ``base_context``; afterwards they are marked consumed and the fact is recorded in
        the job's history, so a message is delivered exactly once.

        The inbox is read again here rather than trusted from ``job``: the copy a step
        holds was read when the step began, and a phase takes hours. Only the messages
        written for this call are put in front of it -- an instruction about phase 8 is
        the mobile specialist's, not the standards review's that runs between its calls.
        The others stay pending in the table; ``save`` never takes one away.
        """
        self._bill_answers(job)
        fresh = self.store.inbox(job.id)
        phase_now = self._phase_number(job)
        pending = [m for m in fresh if m.pending and m.for_call(role.value, phase_now)]
        job.data.inbox = [m for m in fresh if not m.pending] + pending
        project = self._project_of(job)
        profile = kw.get("profile") or kw.get("seed") or job.profile or self.seed_for(job)
        if project is not None and "jira" not in kw:
            kw["jira"] = jira_context(job, role, profile, project)
        retrieved: Retrieval | None = None
        if "standards" not in kw:
            retrieved = self.standards_for(job, role, profile)
            if retrieved is not None:
                kw["standards"] = retrieved.as_context()
                phase = job.data.phase_index + 1 if job.state is JobState.DEVELOPING else None
                self.store.update_state(
                    job.id, job.state, note=retrieved.note(phase), detail=retrieved.detail()
                )
                job.history = self.store.get(job.id).history
        problem = self._budget_problem(job)
        if problem is not None:
            return RoleResult(
                role=role,
                model=profile.roles[role].model,
                thinking_depth=profile.roles[role].thinking_depth,
                error=InvokeError(kind=InvokeErrorKind.BUDGET, message=problem),
            )
        # the recommendation at a phase-budget stop is that budget's last allowance
        spent = None if kw.pop("over_phase_budget", False) else self._phase_over_budget(job)
        if spent is not None:
            return RoleResult(
                role=role,
                model=profile.roles[role].model,
                thinking_depth=profile.roles[role].thinking_depth,
                error=InvokeError(kind=InvokeErrorKind.PHASE_BUDGET, message=spent),
            )
        self._take_off(job, role, profile)
        try:
            result = self._call_with_retries(role, run, job, profile.roles[role].retries, **kw)
        except BaseException:
            # an exception never reaches _account, and a call nobody is waiting for any more
            # must not stay on the page as one that is
            job.data.inflight = None
            with contextlib.suppress(Exception):
                self.store.save(job)
            raise
        if retrieved is not None:
            result.standards = retrieved.chunk_ids
        self._account(job, role, result)
        key = self._output_key(job, role)
        if result.ok and result.raw_text is not None and key is not None:
            digest = hashlib.sha256(result.raw_text.encode()).hexdigest()[:16]
            if job.data.output_hashes.get(key) == digest:
                job.data.output_hashes.pop(key, None)
                self.store.save(job)
                result = RoleResult(
                    role=role,
                    model=result.model,
                    thinking_depth=result.thinking_depth,
                    error=InvokeError(
                        kind=InvokeErrorKind.LOOP,
                        message=f"{role.value} produced the same output twice in a row",
                    ),
                    raw_text=result.raw_text,
                    attempts=result.attempts,
                    prompt_chars=result.prompt_chars,
                )
            else:
                job.data.output_hashes[key] = digest
                self.store.save(job)
        if result.ok and result.output is not None and project is not None:
            self._apply_jira_actions(job, role, profile, project, result.output.jira_actions)
        # a call that failed did not read anything: what was said waits for the next one
        if pending and result.ok:
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
        job.data.inbox = self.store.inbox(job.id)
        return result

    @contextlib.contextmanager
    def _provider_slot(self, job: Job, role: RoleName) -> Iterator[None]:
        """Wait for a free place among the calls this account has running on the provider
        this role is routed to. A development told to stop stops waiting."""
        limit = self.max_calls_per_provider
        if limit <= 0:
            yield
            return
        profile = job.profile or self.seed_for(job)
        cfg = profile.roles[role]
        provider: str | None = cfg.provider
        route = getattr(self.provider_for(job.owner_id), "route", None)
        if route is not None:
            with contextlib.suppress(Exception):
                provider, _model = route(role.value, cfg.provider, cfg.model)
        key = f"{job.owner_id or ''}:{provider or 'default'}"
        with self._provider_slots_lock:
            slot = self._provider_slots.setdefault(key, threading.BoundedSemaphore(limit))
        while not slot.acquire(timeout=1.0):
            if job.id in self._stopping:
                raise _Stopped
        try:
            yield
        finally:
            slot.release()

    def _call_with_retries(
        self, role: RoleName, run: Callable[..., RoleResult], job: Job, retries: int, **kw: Any
    ) -> RoleResult:
        """Run the role; on a retryable provider error wait (doubling) and try again up to
        the role's ``retries``. Every failed attempt is recorded in the history. A
        truncated answer is retried once with the role told to return a smaller part.

        What comes back carries the tokens of *every* attempt, not the last one. The bill
        does: an answer cut off at the limit was generated and charged in full, and asking
        for a smaller part sends the whole prompt again. Counting only the attempt that
        worked made a development with sixty-four retries behind it look like the one call
        that finally answered -- the figure the cost panel showed was not the money."""
        attempt = 0
        truncations = 0
        # the tokens of the attempts before this one; None while no vendor has said any,
        # so "nothing known" never turns into "nothing spent" (see ``Spend.unpriced_calls``)
        burned: list[int] | None = None
        # attempts that timed out: the vendor was writing when we stopped waiting, so
        # those tokens exist and are charged for, and no usage block will ever arrive to
        # say how many. Nothing else here can see them, so they are counted on their own.
        unreported = 0

        def settle(result: RoleResult) -> RoleResult:
            """The call, priced over all its attempts."""
            result.unreported_attempts = unreported
            if burned is None:
                return result
            result.usage = Usage(input_tokens=burned[0], output_tokens=burned[1])
            return result

        # whose keys pay for this: the account that owns the job, never the server's
        mine = self.provider_for(job.owner_id)
        provider: ModelProvider = mine
        while True:
            # a step is not one call: the developer is asked, the gate runs, the developer
            # is asked again, and a call that timed out is asked again after it. Looking for
            # a stop only between steps let a development that had been told to stop go on
            # spending for as long as its step did -- every new call is a place to stop
            if job.id in self._stopping:
                raise _Stopped
            attempt += 1
            with self._provider_slot(job, role):
                result = run(job, provider=provider, timeout_s=self.timeout_s, **kw)
            result.attempts = attempt
            if (
                result.error is not None
                and result.error.kind is InvokeErrorKind.TIMEOUT
                and result.usage is None
            ):
                unreported += 1
            if result.usage is not None:
                if burned is None:
                    burned = [0, 0]
                burned[0] += result.usage.input_tokens or 0
                burned[1] += result.usage.output_tokens or 0
            provider = mine
            if (
                result.error is not None
                and result.error.kind is InvokeErrorKind.MALFORMED_OUTPUT
                and attempt <= retries
            ):
                # the next attempt carries the validation error, not a blind repeat
                provider = _Corrected(mine, result.error.message)
            if (
                result.error is not None
                and result.error.kind is InvokeErrorKind.TRUNCATED
                and "truncated" in inspect.signature(run).parameters
                and truncations < len(TRUNCATION_STEPS)
            ):
                ask = TRUNCATION_STEPS[truncations]
                truncations += 1
                kw["truncated"] = f"{result.error.message}. {ask}"
                self.store.update_state(
                    job.id,
                    job.state,
                    note=(
                        f"{role.value} attempt {attempt}: {result.error.message}; "
                        f"asking for a smaller part ({truncations}/{len(TRUNCATION_STEPS)})"
                    ),
                    detail=ask,
                )
                job.history = self.store.get(job.id).history
                continue
            if result.ok or result.error is None or result.error.kind not in RETRYABLE:
                return settle(result)
            if attempt > retries:
                return settle(result)
            wait = self.retry_backoff_s * (2 ** (attempt - 1))
            self.store.update_state(
                job.id,
                job.state,
                note=(
                    f"{role.value} attempt {attempt} failed: {result.error.kind.value}; "
                    f"retrying in {wait:g}s ({attempt}/{retries} retries used)"
                ),
                detail=result.error.message,
            )
            job.history = self.store.get(job.id).history
            if wait > 0:
                time.sleep(wait)

    # -- what it costs ---------------------------------------------------------------------

    def refresh_prices(self) -> int:
        """Fetch the published price table and store it. Rows a person entered by hand are
        left alone. Returns how many rows were written; a failure raises and the stored
        prices stay as they were, because a stale price beats no price."""
        rows = prices.fetch(transport=self.http_transport)
        written = self.store.put_prices(rows, source="litellm")
        self.store.set_setting(
            "prices.last_fetch",
            {"at": utcnow().isoformat(), "rows": written, "source": prices.SOURCE_URL},
        )
        return written + self._refresh_openrouter_prices()

    def _refresh_openrouter_prices(self) -> int:
        """OpenRouter's own rates, alongside the table rather than inside it.

        Its own catalogue is the only first-hand pricing any vendor publishes, and for
        OpenRouter it is also the only correct one: the bill is OpenRouter's rate, not
        the underlying vendor's. Kept separate so that OpenRouter being unreachable costs
        the OpenRouter rows and not the four thousand the table just delivered.
        """
        try:
            rows = prices.fetch_openrouter(transport=self.http_transport)
        except prices.PriceFetchError as exc:
            log.warning("OpenRouter prices were not refreshed: %s", exc)
            return 0
        return self.store.put_prices(rows, source="openrouter")

    def price_index(self) -> dict[tuple[str, str], dict[str, Any]]:
        return prices.index(self.store.list_prices())

    def price_of(self, provider: str | None, model: str | None) -> prices.Price | None:
        if not provider or not model:
            return None
        return prices.resolve(self.price_index(), provider, model)

    def _take_off(self, job: Job, role: RoleName, profile: Profile) -> None:
        """Say who is being asked, before the answer exists. A call runs for minutes and no
        provider streams, so without this the page knew nothing until it was over; now it
        shows the call it is waiting on, and for how long."""
        cfg = profile.roles[role]
        provider: str | None = cfg.provider
        model: str | None = cfg.model
        route = getattr(self.provider_for(job.owner_id), "route", None)
        if route is not None:
            # where the router will send it: an agent's assignment beats the profile
            with contextlib.suppress(Exception):
                provider, model = route(role.value, cfg.provider, cfg.model)
        job.data.inflight = {
            "role": role.value,
            "provider": provider,
            "model": model,
            "state": job.state.value,
            "phase": self._phase_number(job),
            "started_at": utcnow().isoformat(),
        }
        self.store.save(job)

    def _account(
        self, job: Job, role: RoleName, result: RoleResult, *, phase: int | None = None
    ) -> None:
        """Count the call against the job's budget and keep the per-call log. ``phase`` is
        for an answer written ahead: counted against the phase it was for, not this one."""
        started = (job.data.inflight or {}).get("started_at")
        job.data.inflight = None
        usage = result.usage
        tokens = ((usage.input_tokens or 0) + (usage.output_tokens or 0)) if usage else 0
        job.data.invocations += result.attempts
        job.data.tokens_used += tokens
        # what this call cost, at the price of the model that actually answered. None when
        # the model is not in the price table: an unpriced call is reported, never guessed
        price = self.price_of(result.provider, result.model)
        cost = (
            price.cost(usage.input_tokens or 0, usage.output_tokens or 0)
            if price and usage
            else None
        )
        if cost is not None:
            job.data.cost_usd = round(job.data.cost_usd + cost, 6)
        phase = phase if phase is not None else self._phase_number(job)
        if phase is not None:
            if job.data.phase_calls_for != phase:
                job.data.phase_calls_for, job.data.phase_calls = phase, 0
            job.data.phase_calls += result.attempts
        job.data.invocation_log.append(
            {
                "role": role.value,
                "model": result.model,  # what answered: the assignment, not the profile
                "state": job.state.value,
                # building, its gate and its review alike: the phase the call was for
                "phase": phase,
                "attempts": result.attempts,
                "prompt_chars": result.prompt_chars,
                "provider": result.provider,
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "cost_usd": round(cost, 6) if cost is not None else None,
                "ok": result.ok,
                "error": result.error.kind.value if result.error else None,
                "unreported_attempts": result.unreported_attempts or None,
                "started_at": started,
                # what it wrote, for the page that follows a development as it runs: the
                # role's own one-line account, and the start of the answer itself. Clipped,
                # because every call's lands in the job's row and a row is written often
                "summary": _clip(getattr(result.output, "summary", None), SUMMARY_KEPT),
                "output": _clip(result.raw_text, OUTPUT_KEPT),
                "at": utcnow().isoformat(),
            }
        )
        self.store.save(job)

    def _bill_answers(self, job: Job) -> None:
        """Add the questions answered on this job since the last call to its spend.

        An answer is written beside the run, not by it, so it cannot touch the job's row
        while the run owns it: the run would save over it with the copy it holds. What it
        cost waits on the message instead, and is added here -- by the run before its next
        call, or by the answer itself when nothing was running. The phase's own budget of
        calls is left alone: being asked about the work is not an attempt at it."""
        owed = self.store.unbilled_answers(job.id)
        if not owed:
            return
        for _, entry in owed:
            job.data.invocations += int(entry.get("attempts") or 1)
            job.data.tokens_used += int(entry.get("input_tokens") or 0) + int(
                entry.get("output_tokens") or 0
            )
            if entry.get("cost_usd") is not None:
                job.data.cost_usd = round(job.data.cost_usd + float(entry["cost_usd"]), 6)
            job.data.invocation_log.append(entry)
        self.store.save(job)
        self.store.mark_billed([message_id for message_id, _ in owed])

    @staticmethod
    def _profile(job: Job) -> Profile:
        if job.profile is None:
            raise RuntimeError(f"job {job.id} has no approved profile")
        return job.profile

    def _run_gate(self, job: Job, platform: str | None = None) -> GateResult:
        """Build and test the worktree, wherever this installation runs commands -- the
        project's own commands, or with ``platform`` that mobile app's (T14.1).

        The specialist that wrote the phase has to hold ``run_commands`` for its build to
        be executed. The permission existed from the start and was never checked, which
        made it a promise the profile could not keep: a role could be given read-only
        permissions and still have a command of its own composition run on the host.
        """
        profile = self._profile(job)
        role = self._last_specialist(job)
        config = profile.roles.get(role)
        if config is not None and Permission.RUN_COMMANDS not in config.permissions:
            return GateResult(
                ok=False,
                output=(
                    f"$ {profile.commands_for(platform)[0]}\n"
                    f"[refused: {role.value} does not have the run_commands permission]"
                ),
            )
        lent = (
            platform is not None
            and not toolchains.can_build(platform)
            and platform in self.remote_platforms(job.owner_id)
        )
        if lent:
            assert platform is not None
            gate = self._remote_gate(job, profile, platform)
        else:
            kwargs: dict[str, Any] = {"runner": self.runner, "platform": platform}
            if self.gate_timeout_s is not None:
                kwargs["timeout_s"] = self.gate_timeout_s
            with self._checkout_locks[str(require_worktree(job))]:
                gate = build_gate(profile, require_worktree(job), **kwargs)
        if job.project_id is not None:
            self.record_gate_run(job, gate)
        return gate

    def _remote_gate(self, job: Job, profile: Profile, platform: str) -> GateResult:
        """Build on a machine the owner lent: queue the worktree and the platform's two
        commands, and wait for the answer.

        A worker that stops being heard from while it holds the build has it taken back
        and queued again, once; a second time, or nobody able to take it at all, is
        ``BuilderLost`` -- a Mac gone to sleep is not a red build and must not be charged
        as one. The queued copy is dropped whatever happens: it is a whole worktree.
        """
        timeout = self.gate_timeout_s or GATE_TIMEOUT_S
        worktree = require_worktree(job)
        with self._checkout_locks[str(worktree)]:
            try:
                packed = workers.snapshot(worktree)
            except ValueError as exc:
                return GateResult(ok=False, output=f"[{platform}: not sent to a Mac: {exc}]")
        build, test = profile.commands_for(platform)
        task_id = self.store.enqueue_worker_task(
            job.owner_id,
            job.id,
            platform,
            [(f"{platform} build", build), (f"{platform} test", test)],
            timeout,
            packed,
        )
        # both commands may take their whole timeout; past that and a margin, nobody is coming
        deadline = time.monotonic() + 2 * timeout + workers.LIVE.total_seconds()
        waiting_since = time.monotonic()
        try:
            while True:
                row = self.store.worker_task_row(task_id)
                if row is None:
                    raise BuilderLost(f"the {platform} build was taken off the queue")
                if row["state"] == "done":
                    return GateResult(
                        ok=row["exit_code"] == 0,
                        output=str(row["output"] or ""),
                        seconds=float(row["seconds"] or 0.0),
                    )
                now = time.monotonic()
                if row["state"] == "running":
                    holder = self.store.get_worker(
                        str(row["worker_id"]), live_since=workers.live_since()
                    )
                    if holder is None or not holder.online:
                        if int(row["tries"]) >= 2:
                            raise BuilderLost(f"the Mac building {platform} went away twice")
                        self.store.requeue_worker_task(task_id)
                        waiting_since = now
                elif (
                    platform not in self.remote_platforms(job.owner_id)
                    and now - waiting_since > workers.LIVE.total_seconds()
                ):
                    raise BuilderLost(f"no Mac that builds {platform} is connected")
                if now > deadline:
                    raise BuilderLost(f"no answer from the Mac building {platform} in time")
                time.sleep(self.worker_poll_s)
        finally:
            self.store.drop_worker_task(task_id)

    def _final_gate(self, job: Job) -> GateResult:
        """The whole project, once QA's tests are written: its own commands, then every
        mobile platform's that can be built here or on a machine the owner lent. One that
        cannot is said, not failed: its phases already passed their own gates, and holding
        the tests of everything else hostage to a Mac being awake would help nobody."""
        gate = self._run_gate(job)
        profile = self._profile(job)
        outputs = [gate.output]
        seconds = gate.seconds
        for platform in profile.platform_names():
            if not gate.ok:
                break
            if not self.can_build(job, platform):
                outputs.append(f"[{platform}: not built here -- this machine cannot build it]")
                continue
            try:
                built = self._run_gate(job, platform)
            except BuilderLost as lost:
                outputs.append(f"[{platform}: not built -- {lost}]")
                continue
            gate = built
            outputs.append(gate.output)
            seconds += gate.seconds
        return GateResult(ok=gate.ok, output="\n\n".join(outputs), seconds=seconds)

    @staticmethod
    def _phases(job: Job) -> list[dict[str, Any]]:
        plan = job.data.plan or {}
        phases: list[dict[str, Any]] = plan.get("phases", [])
        return phases

    # -- phase handlers ------------------------------------------------------------------

    def _backlog(self, job: Job) -> Job:
        """The Product Owner writes the backlog; the human approves it before design."""
        if job.data.reject_rounds > self.max_reject_rounds:
            return self._fail(
                job,
                f"backlog rejected {job.data.reject_rounds} times; giving up",
                detail=job.data.feedback,
            )
        job = self._ensure_workspace(job)
        seed = self.seed_for(job)
        result = self._invoke(
            RoleName.PO, po.run, job, profile=seed, attachments=self.attachments_for(job)
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, POResult)
        job.data.backlog = result.output.breakdown.model_dump(mode="json")
        self.store.save(job)
        breakdown = result.output.breakdown
        tasks = breakdown.tasks()
        stories = sum(len(e.stories) for e in breakdown.epics)
        # the note is the headline a feed can show in one line; the model's prose and the
        # backlog itself belong to the detail, where a page can lay them out
        note = (
            f"po: backlog ready — {len(breakdown.epics)} epics, "
            f"{stories} stories, {len(tasks)} tasks"
        )
        detail = json.dumps({"summary": result.output.summary, **job.data.backlog}, indent=2)
        if job.data.plan_gate == "combined":
            # one work list: the architect goes on and the person approves both at once
            return self.orchestrator.transition(
                job, JobState.ARCHITECTURE, note=f"{note}; the architect continues", detail=detail
            )
        return self.orchestrator.transition(
            job, JobState.AWAITING_BACKLOG_APPROVAL, note=note, detail=detail
        )

    def _architecture(self, job: Job) -> Job:
        """The Architect proposes profile, decisions and one phase per backlog task."""
        if job.data.reject_rounds > self.max_reject_rounds:
            return self._fail(
                job,
                f"architecture rejected {job.data.reject_rounds} times; giving up",
                detail=job.data.feedback,
            )
        if not job.data.backlog:
            return self._fail(job, "no approved backlog to design from")
        seed = self.seed_for(job)
        result = self._invoke(
            RoleName.ARCHITECT,
            architect.run,
            job,
            seed=seed,
            attachments=self.attachments_for(job, whole=False),
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, ArchitectResult)
        breakdown = Breakdown.model_validate(job.data.backlog)
        task_ids = [t.id for t in breakdown.tasks()]
        kept = [PlanPhase.model_validate(p) for p in architect.kept_phases(job)]
        mapping = _plan_problem(kept, result.output.phases, task_ids)
        if isinstance(mapping, str):
            # a plan that skips a task is usually the Architect obeying "say so in summary"
            # too literally: it flags a large task and leaves it out. Failing outright threw
            # away a paid plan the person never got to see, so it is asked once more with
            # the reason and the task list spelled out, and only then given up on.
            self.store.update_state(
                job.id,
                job.state,
                note=f"architect: plan does not match the backlog ({mapping}); asking again",
                detail=result.output.summary,
            )
            job.history = self.store.get(job.id).history
            listing = "; ".join(f"{t.id} ({t.title})" for t in breakdown.tasks())
            result = self._invoke(
                RoleName.ARCHITECT,
                architect.run,
                job,
                seed=seed,
                attachments=self.attachments_for(job, whole=False),
                problem=(
                    f"{mapping}. Every backlog task needs a phase whose `task_id` is the "
                    f"task's id, and every phase lists in `depends_on` the earlier phases it "
                    f"builds on; the tasks are: {listing}"
                ),
            )
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, ArchitectResult)
            mapping = _plan_problem(kept, result.output.phases, task_ids)
            if isinstance(mapping, str):
                return self._fail(
                    job,
                    f"architect: plan does not match the backlog: {mapping}",
                    detail=result.output.summary,
                )
        assert isinstance(result.output, ArchitectResult)
        for task in breakdown.tasks():
            task.phase = mapping[task.id]
        job.profile = architect.accepted_profile(result.output, seed)
        phases = [*kept, *result.output.phases]
        job.data.plan = {
            "summary": result.output.summary,
            "stack": [s.model_dump(mode="json") for s in result.output.stack],
            "decisions": result.output.decisions,
            "phases": [p.model_dump(mode="json") for p in phases],
            "breakdown": breakdown.model_dump(mode="json"),
        }
        # how many of its phases were built before it: the pipeline reads their history,
        # and only what came after the plan for the rest -- a phase 2 of an earlier plan
        # passing its gate says nothing about this plan's phase 2
        job.data.plan["kept"] = len(kept)
        job.data.phase_commits = {
            n: sha for n, sha in job.data.phase_commits.items() if int(n) <= len(kept)
        }
        # a re-plan resumes where it started: what is built stays built
        job.data.phase_index = len(kept)
        job.data.build_attempts = 0
        job.data.last_build_output = None
        self.store.save(job)
        # what the gate shows, taken before QA is asked: the call returns a fresh job
        detail = json.dumps(
            {"profile": job.profile.model_dump(mode="json"), **job.data.plan}, indent=2
        )
        if job.data.plan_gate == "combined" and not (kept and job.data.test_cases):
            job = self._propose_test_cases_early(job)
        ready = (
            f"architect: re-planned from phase {len(kept) + 1} — {len(kept)} kept, "
            f"{len(result.output.phases)} new"
            if job.data.replan_from is not None
            else f"architect: plan ready — {len(phases)} phases"
        )
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_ARCHITECTURE_APPROVAL,
            note=f"{ready}, {len(result.output.decisions)} decisions",
            detail=detail,
        )

    def _propose_test_cases_early(self, job: Job) -> Job:
        """With one work list, QA is asked for its cases while the list is still being read:
        the person sees what will be tested before anything is built. They are a proposal —
        QA revisits them once the code exists, and the test gate is still the human's.
        A failure here costs the list a section, never the development."""
        result = self._invoke(
            RoleName.QA,
            qa.run,
            job,
            profile=self._profile(job),
            branch_diff="(nothing is built yet: propose the cases from the plan)",
        )
        if not result.ok or not isinstance(result.output, QAResult):
            self.store.update_state(
                job.id,
                job.state,
                note="qa: could not propose test cases yet; they are asked for again later",
            )
            return self.store.get(job.id)
        job.data.test_cases = [c.model_dump(mode="json") for c in result.output.test_cases]
        self.store.save(job)
        self.store.update_state(
            job.id,
            job.state,
            note=f"qa: {len(job.data.test_cases)} test case(s) proposed for the list",
            detail=json.dumps(job.data.test_cases, indent=2),
        )
        return self.store.get(job.id)

    def _design(self, job: Job) -> Job:
        """The Designer turns the approved backlog into screens for the UI specialists.

        The state can be entered more than once for the same plan — a resumed job re-runs
        the state it stopped in — so it steps aside when the screens on the job were drawn
        for the plan as it stands. A rejected and rewritten plan has a different
        fingerprint, so those screens are drawn again rather than carried over."""
        fingerprint = plan_fingerprint(job)
        sent_back = designer.rejected(job)
        if (job.data.design or {}).get("plan_fingerprint") == fingerprint and not sent_back:
            return self.orchestrator.transition(
                job,
                JobState.DEVELOPING,
                note="designer: the screens already match this plan",
            )
        if job.data.design and not sent_back and not designer.unscreened(job):
            # a re-plan with the same tasks: their screens still stand, approvals and all
            job.data.design = {**job.data.design, "plan_fingerprint": fingerprint}
            self.store.save(job)
            return self.orchestrator.transition(
                job,
                JobState.DEVELOPING,
                note="designer: every task still to build has its screens already",
            )
        profile = self._profile(job)
        result = self._invoke(
            RoleName.DESIGNER,
            designer.run,
            job,
            profile=profile,
            attachments=self.attachments_for(job, whole=False),
            screens=self.screens_for(job),
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, DesignResult)
        job.data.design = {
            "principles": list(result.output.principles),
            "screens": [s.model_dump(mode="json") for s in result.output.screens],
            # which plan these screens are for; a plain string, so an older build still
            # reads the row it was written by
            "plan_fingerprint": fingerprint,
        }
        # a screen that was sent back is waiting again, whatever it was before; one that was
        # never sent back keeps the yes it already had, so approving eight screens and
        # asking for one to be redrawn does not put the other seven back in the queue
        redrawn = {str(s["id"]) for s in sent_back}
        drawn = {s.id for s in result.output.screens}
        job.data.design_approvals = {
            sid: ok
            for sid, ok in job.data.design_approvals.items()
            if ok and sid in drawn and sid not in redrawn
        }
        job.data.design_feedback = {}
        job.data.feedback = None
        self.store.save(job)
        screens = result.output.screens
        return self.orchestrator.transition(
            job,
            JobState.DEVELOPING,
            note=f"designer: {len(screens)} screen(s) designed — {result.output.summary}",
            detail=json.dumps(
                {"summary": result.output.summary, **job.data.design}, indent=2, ensure_ascii=False
            ),
        )

    def _design_gate(self, job: Job, phase: dict[str, Any]) -> Job | None:
        """Stop before a phase that would have to guess what the screen looks like.

        The screens are signed off one at a time, and the wait is put where it costs the
        least: a development builds its backend phases while the design is still being
        looked at, and only the first web or mobile phase stops. A development with no
        screens, or one whose screens are all approved, never sees this.
        """
        if phase.get("domain") not in ("web", "mobile"):
            return None
        pending = designer.pending_screens(job)
        if not pending:
            return None
        names = ", ".join(str(s.get("name")) for s in pending[:3])
        more = f" and {len(pending) - 3} more" if len(pending) > 3 else ""
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_DESIGN_APPROVAL,
            note=f"design: {len(pending)} screen(s) waiting for you — {names}{more}",
        )

    def _develop(self, job: Job) -> Job:
        profile = self._profile(job)
        phases = self._phases(job)
        index = job.data.phase_index
        if index >= len(phases):
            return self._fail(job, f"no plan phase {index + 1} to develop")
        asked = self._unpark(job)  # a phase set aside earlier: its turn, and the question
        if asked is not None:
            return asked
        if not self._phase_buildable(job, phases[index]):
            # checked before the screens: a phase that cannot be built yet should not keep
            # the ones that can waiting on a design approval
            job = self._put_unbuildable_last(job)
            phases = self._phases(job)
            if not self._phase_buildable(job, phases[index]):
                return self._wait_for_builder(job)
        waiting = self._design_gate(job, phases[index])
        if waiting is not None:
            return waiting
        role = specialist_for(phases[index].get("domain"))
        worktree = require_worktree(job)
        if job.data.build_attempts == 0 and job.data.review_rounds == 0:
            job.data.phase_base_commit = g.head_commit(worktree)  # the review diffs from here
            self.store.save(job)
        # a fix round is only worth a build if it changes something. What the failed attempt
        # left is still staged, uncommitted, so the index before and after says whether it did
        before_fix: str | None = None
        if job.data.build_attempts > 0 and job.data.last_build_output is not None:
            g.stage_all(worktree)
            before_fix = g.staged_diff(worktree)
        review_ctx: dict[str, Any] | None = None
        if job.data.review_violations:
            review_ctx = {
                "round": job.data.review_rounds,
                "violations": job.data.review_violations,
                "feedback": job.data.feedback,
            }
        # a big phase may take several answers: each part is applied and the specialist
        # is called again with what is already written, until it says the phase is done
        touched_all: list[str] = []
        summaries: list[str] = []
        continuation: dict[str, Any] | None = None
        # a person who writes to the specialist while it is answering is read by the next
        # part; when that answer was going to be the last, there is one part more for it
        allowed = self.max_phase_parts
        steered = False
        part = 0
        fresh = job.data.build_attempts == 0 and review_ctx is None
        # the phases after this one that need nothing it does start writing now (T16.3)
        job = self._write_ahead(job, index)
        while part < allowed:
            part += 1
            ahead = self._take_ahead(job, index, role) if part == 1 and fresh else None
            result = ahead or self._invoke(
                role,
                developer.run,
                job,
                profile=profile,
                as_role=role,
                review=review_ctx,
                continuation=continuation,
            )
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, DeveloperResult)
            try:
                touched = apply_changes(
                    job,
                    profile,
                    role,
                    result.output.changes,
                    cut=developer.too_large(worktree, developer.editable_files(job, worktree)),
                )
            except PermissionError as exc:
                return self._fail(
                    job,
                    f"{exc}; grant it under Agents → {role.value} → Setup and retry",
                )
            except EditMismatch as exc:
                # nothing of the answer was written: the specialist is asked again with
                # the file's real lines, as one more part of the same phase (T15.4)
                if part == allowed:
                    return self._fail(
                        job, f"{role.value}'s changes could not be applied", detail=str(exc)
                    )
                self.store.update_state(
                    job.id,
                    job.state,
                    note=f"{role.value} phase {index + 1}/{len(phases)}: an edit did not fit",
                    detail=str(exc),
                )
                job.history = self.store.get(job.id).history
                continuation = {
                    "part": part + 1,
                    "files_so_far": list(touched_all),
                    "summary_so_far": " ".join(summaries),
                    "edit_failed": str(exc),
                }
                continue
            touched_all.extend(t for t in touched if t not in touched_all)
            summaries.append(result.output.summary)
            last = result.output.phase_complete or part == allowed
            late = last and not steered and self._steered(job, role, index + 1)
            if late:
                # it said it was done, but somebody wrote while it was writing: the phase
                # is not committed past what they said -- one more part reads it
                steered = True
                allowed = max(allowed, part + 1)
            elif last:
                break
            g.stage_all(worktree)
            self.store.update_state(
                job.id,
                job.state,
                note=(
                    f"{role.value} phase {index + 1}/{len(phases)} part {part}: "
                    f"{result.output.summary} ({len(touched)} files, more to come)"
                ),
                detail=g.staged_diff(worktree) or "(no changes)",
            )
            job.history = self.store.get(job.id).history
            continuation = {
                "part": part + 1,
                "files_so_far": list(touched_all),
                "summary_so_far": " ".join(summaries),
            }
            if late:
                continuation["new_instruction"] = True
        g.stage_all(worktree)
        diff = g.staged_diff(worktree)
        if before_fix is not None and diff == before_fix:
            # First the reason that is ours: a file it would have had to change reached it
            # cut short, and a file is changed by returning all of it. Blaming the machine
            # here once sent a person to look for a missing tool while the fix was one word
            # on a line of App.tsx the specialist was never shown.
            cut = developer.too_large(worktree, developer.editable_files(job, worktree))
            if cut:
                return self._fail(
                    job,
                    f"{role.value} phase {index + 1}/{len(phases)}: the fix changed no file "
                    f"because {', '.join(cut)} is too large to be sent whole, and a file is "
                    f"changed by returning all of it; re-plan so it is split into smaller "
                    f"files ({summaries[-1]})",
                    detail=job.data.last_build_output,
                )
            # The specialist read the failure and changed nothing: it is saying the code is
            # not what fails. That leaves the command itself or what the machine has
            # installed, and neither is a specialist's. Running the same command on the same
            # files would fail the same way and spend an attempt; three of those once burned
            # an Android development's fix rounds on an SDK the image did not have.
            return self._fail(
                job,
                f"{role.value} phase {index + 1}/{len(phases)}: the fix changed no file, "
                f"so the build would fail the same way again — the build command or this "
                f"machine's tools are what fails, not the code; re-plan, or install what is "
                f"missing and retry ({summaries[-1]})",
                detail=job.data.last_build_output,
            )
        attempt = f", fix attempt {job.data.build_attempts}" if job.data.build_attempts else ""
        if job.data.review_rounds and not attempt:
            attempt = f", review fix {job.data.review_rounds}"
        parts = f" in {len(summaries)} parts" if len(summaries) > 1 else ""
        return self.orchestrator.transition(
            job,
            JobState.BUILD_GATE,
            note=(
                f"{role.value} phase {index + 1}/{len(phases)}{attempt}: "
                f"{summaries[-1]} ({len(touched_all)} files{parts})"
            ),
            detail=diff or "(no changes)",
        )

    # -- builds this machine cannot do (T14.2) ---------------------------------------------

    def remote_platforms(self, owner_id: str | None) -> frozenset[str]:
        """What the machines this account has lent, and that are there now, can build.
        Only its own: a Mac is lent to one account and never builds another's code."""
        found: set[str] = set()
        for worker in self.store.list_workers(owner_id, live_since=workers.live_since()):
            if worker.online:
                found.update(worker.capabilities)
        return frozenset(found)

    def can_build(self, job: Job, platform: str) -> bool:
        """Here, or on a machine the job's owner has lent -- never somebody else's."""
        return toolchains.can_build(platform) or platform in self.remote_platforms(job.owner_id)

    def _phase_buildable(self, job: Job, phase: dict[str, Any]) -> bool:
        platform = phase.get("platform")
        return not platform or self.can_build(job, str(platform))

    # -- answers written ahead (T16.3) ----------------------------------------------------

    def _write_ahead(self, job: Job, index: int) -> Job:
        """Start writing the answers of the phases after ``index`` that need nothing still
        to be built -- by the plan's `depends_on` (T16.2) -- so they are ready when their
        turn comes.

        The model's answer is where a phase's time goes: minutes to most of an hour, while
        its build gate takes seconds. So that is what runs side by side. Each phase is still
        applied, built, reviewed, committed and pushed in its turn, in plan order, on the
        one branch: no second checkout, no merge, no conflict to resolve. A phase that needs
        nothing still to be built cannot need what the phases before it are writing, and
        two phases on one file are always ordered (T16.2), so an answer written ahead
        touches nothing another one does.
        """
        limit = self.budget_for(job).max_parallel_phases or 1
        phases = self._phases(job)
        running = self._ahead.setdefault(job.id, {})
        # what an earlier run of the server started is gone with it
        shown = {k: v for k, v in job.data.ahead.items() if int(k) in running}
        if shown != job.data.ahead:
            job.data.ahead = shown
            self.store.save(job)
        room = limit - 1 - sum(1 for f in running.values() if not f.done())
        if room <= 0:
            return job
        done = set(range(1, index + 1))  # the phases committed, and this one
        started: list[int] = []
        for j in range(index + 1, len(phases)):
            if room <= 0:
                break
            number = j + 1
            phase = phases[j]
            needs = phase.get("depends_on")
            if number in running or needs is None or not set(needs) <= done - {index + 1}:
                continue
            if not self._phase_buildable(job, phase) or (
                phase.get("domain") in ("web", "mobile") and designer.pending_screens(job)
            ):
                continue  # it waits for a Mac or a design approval, and so does its answer
            running[number] = self._start_ahead(job, j)
            job.data.ahead[str(number)] = {
                "role": specialist_for(phase.get("domain")).value,
                "started_at": utcnow().isoformat(),
            }
            started.append(number)
            room -= 1
        if started:
            self.store.save(job)
            names = ", ".join(str(n) for n in started)
            self._record_gate_note(
                job,
                f"phase(s) {names}: their answers are written alongside phase {index + 1}",
                None,
            )
        return job

    def _start_ahead(self, job: Job, j: int) -> Future[RoleResult]:
        """One phase's first answer, on a thread, from a copy of the job that is on it."""
        phases = self._phases(job)
        role = specialist_for(phases[j].get("domain"))
        profile = self._profile(job)
        ahead = job.model_copy(deep=True)
        ahead.data.phase_index = j
        ahead.data.last_build_output = None
        ahead.data.qa_diagnosis = None
        ahead.data.review_violations = []
        ahead.data.inbox = []  # what a person wrote is for the phase that reads it in turn
        retrieved = self.standards_for(ahead, role, profile)
        kw: dict[str, Any] = {"profile": profile, "as_role": role}
        if retrieved is not None:
            kw["standards"] = retrieved.as_context()
        retries = profile.roles[role].retries

        def write() -> RoleResult:
            return self._call_with_retries(role, developer.run, ahead, retries, **kw)

        return self._ahead_pool.submit(write)

    def _take_ahead(self, job: Job, index: int, role: RoleName) -> RoleResult | None:
        """The answer written ahead for this phase, once it is ready; None when there is
        none, or it failed -- then the phase is asked as it always was."""
        number = index + 1
        future = self._ahead.get(job.id, {}).pop(number, None)
        if job.data.ahead.pop(str(number), None) is not None:
            self.store.save(job)
        if future is None:
            return None
        self._take_off(job, role, self._profile(job))  # shown as the call it is waiting on
        try:
            result = future.result()
        except Exception as exc:  # noqa: BLE001 -- the phase is asked in turn instead
            job.data.inflight = None
            self.store.save(job)
            self._record_gate_note(
                job, f"phase {number}: the answer written ahead failed", str(exc)
            )
            return None
        self._account(job, role, result, phase=number)
        if not result.ok:
            self._record_gate_note(
                job,
                f"phase {number}: the answer written ahead failed; asking in turn",
                result.error.message if result.error else None,
            )
            return None
        project = self._project_of(job)
        if result.output is not None and project is not None:
            profile = self._profile(job)
            self._apply_jira_actions(job, role, profile, project, result.output.jira_actions)
        return result

    def _drop_ahead(self, job: Job) -> None:
        """Forget what is being written ahead: the plan it was for is going. What is already
        on its way is paid for and finishes; nobody reads it."""
        for future in self._ahead.pop(job.id, {}).values():
            future.cancel()
        job.data.ahead = {}

    def _reorder(self, job: Job, moved: list[dict[str, Any]]) -> None:
        """Put the plan's phases in a new order (the same dicts, rearranged). A phase's number
        is where it stands, so the numbers it depends on move with it, and the breakdown's
        too -- or the board would mark the wrong tasks done. Only phases not started move."""
        plan = dict(job.data.plan or {})
        phases: list[dict[str, Any]] = list(plan.get("phases", []))
        number = {id(p): i for i, p in enumerate(moved, start=1)}
        before = {i: id(p) for i, p in enumerate(phases, start=1)}
        plan["phases"] = [
            p
            if p.get("depends_on") is None
            else {**p, "depends_on": sorted(number[before[d]] for d in p["depends_on"])}
            for p in moved
        ]
        if plan.get("breakdown"):
            breakdown = Breakdown.model_validate(plan["breakdown"])
            mapping = architect.phase_task_map(
                [PlanPhase.model_validate(p) for p in plan["phases"]],
                [t.id for t in breakdown.tasks()],
            )
            if isinstance(mapping, dict):
                for task in breakdown.tasks():
                    task.phase = mapping[task.id]
                plan["breakdown"] = breakdown.model_dump(mode="json")
        job.data.plan = plan

    # -- a phase that spent its budget waits while the others go on -----------------------

    def _park(self, job: Job, why: str) -> Job | None:
        """Set the phase that spent its budget aside and go on with the ones that need
        nothing of it; None when there are none, and the person is asked now.

        A stuck phase used to stop the whole development, though the phases after it that
        did not need it could have been built meanwhile. Its uncommitted work is kept as a
        patch with its counters, the checkout goes back to the last commit, and the phase --
        with every phase that needs it -- moves behind the ones that do not. When its turn
        comes again it is put back as it was, and the person is asked then, once nothing
        else can run.
        """
        phases = self._phases(job)
        index = job.data.phase_index
        number = index + 1
        # what needs this phase, directly or through others; a phase that does not say
        # needs every earlier one
        needs_it = {number}
        for n in range(number + 1, len(phases) + 1):
            deps = phases[n - 1].get("depends_on")
            if deps is None or needs_it & set(deps):
                needs_it.add(n)
        free = [n for n in range(number + 1, len(phases) + 1) if n not in needs_it]
        if not free:
            return None
        worktree = require_worktree(job)
        g.stage_all(worktree)
        patch = g.run(worktree, "diff", "--cached", "--binary").stdout
        g.run(worktree, "reset", "-q", "--hard", "HEAD")
        held = {
            "why": why,
            "patch": patch,
            "build_attempts": job.data.build_attempts,
            "last_build_output": job.data.last_build_output,
            "qa_diagnosis": job.data.qa_diagnosis,
            "review_violations": job.data.review_violations,
            "review_rounds": job.data.review_rounds,
            "phase_calls": job.data.phase_calls,
        }
        order = [phases[n - 1] for n in free] + [phases[n - 1] for n in sorted(needs_it)]
        self._drop_ahead(job)
        # a phase set aside earlier moves too: its record follows it to its new number
        moving = {
            id(phases[n - 1]): job.data.parked.pop(str(n))
            for n in list(range(number, len(phases) + 1))
            if str(n) in job.data.parked
        }
        self._reorder(job, phases[:index] + order)
        new_phases = self._phases(job)
        for i, p in enumerate(new_phases, start=1):
            record = moving.get(id(p))
            if record is not None:
                job.data.parked[str(i)] = record
        job.data.parked[str(index + len(free) + 1)] = held
        job.data.build_attempts = 0
        job.data.last_build_output = None
        job.data.qa_diagnosis = None
        job.data.review_violations = []
        job.data.review_rounds = 0
        job.data.phase_calls = 0
        job.data.phase_calls_for = None
        self.store.save(job)
        goes = ", ".join(str(n) for n in range(number, number + len(free)))
        note = (
            f"phase {number} spent its budget and waits: phase(s) {goes} need nothing of it "
            "and go on first; you are asked about it when its turn comes again"
        )
        if job.state is not JobState.DEVELOPING:
            # stopped at its gate's triage: the next phase is written, not built
            return self.orchestrator.transition(job, JobState.DEVELOPING, note=note, detail=why)
        self._record_gate_note(job, note, why)
        # still developing, so the next phase is written now: the run loop wants every
        # step to move the development on, and this one has not moved yet
        return self._develop(self.store.get(job.id))

    def _unpark(self, job: Job) -> Job | None:
        """The phase set aside, back as it was when its turn comes; None when it was not
        one. Then the person is asked, as it would have been asked when it stopped."""
        held = job.data.parked.pop(str(job.data.phase_index + 1), None)
        if held is None:
            return None
        worktree = require_worktree(job)
        if held.get("patch"):
            try:
                g.run(worktree, "apply", "--index", "--binary", "-", stdin=str(held["patch"]))
            except g.GitError as exc:
                self._record_gate_note(job, "its work in progress could not be put back", str(exc))
        job.data.build_attempts = int(held.get("build_attempts") or 0)
        job.data.last_build_output = held.get("last_build_output")
        job.data.qa_diagnosis = held.get("qa_diagnosis")
        job.data.review_violations = list(held.get("review_violations") or [])
        job.data.review_rounds = int(held.get("review_rounds") or 0)
        job.data.phase_calls = int(held.get("phase_calls") or 0)
        job.data.phase_calls_for = job.data.phase_index + 1
        self.store.save(job)
        return self._phase_budget_stop(job, str(held.get("why") or ""), park=False)

    def _put_unbuildable_last(self, job: Job) -> Job:
        """Move the phases nothing here can build behind the ones it can.

        Safe because nothing depends on a platform phase -- the Architect is told so -- and
        stable, so each group keeps its own order: an iOS phase that builds on another iOS
        phase still comes after it. Only phases not started yet move, so every number the
        history already speaks of stays true; the breakdown's numbers follow the plan, or
        the board would mark the wrong tasks done.
        """
        plan = dict(job.data.plan or {})
        phases: list[dict[str, Any]] = list(plan.get("phases", []))
        index = job.data.phase_index
        rest = phases[index:]
        ready = [p for p in rest if self._phase_buildable(job, p)]
        later = [p for p in rest if not self._phase_buildable(job, p)]
        if not ready or rest == ready + later:
            return job
        self._reorder(job, phases[:index] + ready + later)
        job = self.store.save(job)
        names = ", ".join(sorted({str(p["platform"]) for p in later}))
        self._record_gate_note(
            job,
            f"{len(later)} phase(s) wait until last: nothing here builds {names} yet",
            "\n".join(str(p.get("goal", "")) for p in later),
        )
        return job

    def _wait_for_builder(
        self, job: Job, *, resume: JobState = JobState.DEVELOPING, why: str | None = None
    ) -> Job:
        """Everything left needs a machine this is not: stop and say which, and wait for
        one to connect. No attempt is spent and nothing has failed.

        ``resume`` is where it picks up: the phase itself, or -- when the Mac went away
        with a phase already written -- only its build.
        """
        phases = self._phases(job)
        index = job.data.phase_index
        wanted = {
            str(p["platform"])
            for p in phases[index:]
            if p.get("platform") and not self._phase_buildable(job, p)
        }
        if resume is JobState.BUILD_GATE and index < len(phases) and phases[index].get("platform"):
            wanted.add(str(phases[index]["platform"]))
        platforms = sorted(wanted)
        job.data.waiting_platforms = platforms
        job.data.builder_resume = resume.value
        self.store.save(job)
        names = ", ".join(platforms)
        job = self.orchestrator.transition(
            job,
            JobState.AWAITING_BUILDER,
            note=(
                f"waiting for a builder: phase {index + 1}/{len(phases)} and after need "
                f"{names}, which nothing here can build; it carries on when one connects"
            ),
            detail="\n".join(
                ([why] if why else [])
                + [
                    f"{i + 1}. {p.get('goal', '')} ({p.get('platform')})"
                    for i, p in enumerate(phases)
                    if i >= index
                ]
            ),
        )
        self._notify_builder_wait(job)
        return job

    def builder_ready(self, job: Job) -> bool:
        """Whether a job waiting for a builder can go on now."""
        phases = self._phases(job)
        index = job.data.phase_index
        return (
            job.state is JobState.AWAITING_BUILDER
            and index < len(phases)
            and self._phase_buildable(job, phases[index])
        )

    def waiting_for_builders(self, owner_id: str | None) -> list[str]:
        """This account's developments that a builder connecting now would carry on.

        The one way a waiting development moves without a person pressing anything, so it
        is asked per account: a Mac one account lends never wakes another's work. The
        caller resumes them, each on its own owner's keys like any other run.
        """
        # no owner is a local install's jobs, and "= NULL" matches no row: filter here
        listed = self.store.list(owner_id=ANY_OWNER if owner_id is None else owner_id)
        return [job.id for job in listed if job.owner_id == owner_id and self.builder_ready(job)]

    def _notify_builder_wait(self, job: Job) -> None:
        """Tell the owner once per wait: the chat groups that hear of gates, and a letter.
        The letter links to the page that pairs a Mac -- it never carries a pairing code,
        which in a mailbox or a chat history would outlive its purpose."""
        visits = sum(
            1 for t in job.history if t.to_state is job.state and t.from_state is not job.state
        )
        marker = f"{job.state.value}:{visits}"
        if marker in job.data.notified:
            return
        notify_builder_wait(self, job)
        self._mail_builder_wait(job)
        job.data.notified.append(marker)
        self.store.save(job)

    def _last_specialist(self, job: Job) -> RoleName:
        """The specialist that wrote the last phase: it also handles CI fixes."""
        phases = self._phases(job)
        if not phases:
            return RoleName.BACKEND
        index = min(max(job.data.phase_index - 1, 0), len(phases) - 1)
        return specialist_for(phases[index].get("domain"))

    def _build_gate(self, job: Job) -> Job:
        phases = self._phases(job)
        index = job.data.phase_index
        # a phase that builds one platform's app is built with that platform's commands
        platform = phases[index].get("platform") if index < len(phases) else None
        try:
            gate = self._run_gate(job, platform)
            # the tester reads a failure first: a test that asserts something nobody agreed
            # to is QA's own to correct, and the gate runs again without a specialist
            while not gate.ok and self._qa_gate_triage(job, index, gate.for_model):
                gate = self._run_gate(job, platform)
        except BuilderLost as lost:
            # the phase is written and staged; only its build is owed, so that is where the
            # development picks up again -- not with the specialist writing it twice
            return self._wait_for_builder(job, resume=JobState.BUILD_GATE, why=str(lost))
        if gate.ok:
            job.data.build_attempts = 0
            job.data.last_build_output = None
            job.data.qa_gate_fixes = 0
            job.data.qa_diagnosis = None
            if job.data.rerun_only:
                # a hand-run of the tests on work that is already committed: report and stop
                job.data.rerun_only = False
                self.store.save(job)
                return self.orchestrator.transition(
                    job, JobState.DONE, note="tests re-run by hand: passed", detail=gate.tail
                )
            if index < len(phases):
                writer = specialist_for(phases[index].get("domain"))
                if self._steered(job, writer, index + 1):
                    # green, but somebody wrote to the specialist about this phase while it
                    # was being built and tested: what they said is read before the phase is
                    # committed and the development moves past it. Not a fix attempt -- the
                    # build did not fail
                    self.store.save(job)
                    return self.orchestrator.transition(
                        job,
                        JobState.DEVELOPING,
                        note=(
                            f"{writer.value} phase {index + 1}/{len(phases)}: the build "
                            "passed; a person wrote about this phase, so it is read before "
                            "the phase is committed"
                        ),
                        detail=gate.tail,
                    )
            worktree = require_worktree(job)
            g.stage_all(worktree)
            goal = phases[index].get("goal", "") if index < len(phases) else ""
            if g.commit(worktree, self._commit_message(job, index, goal)):
                job.data.phase_commits[str(index + 1)] = g.head_commit(worktree)
                self._push(job, worktree, f"phase {index + 1}/{len(phases)}")
            job.data.phase_index = index + 1
            self.store.save(job)
            done = job.data.phase_index >= len(phases)
            if self.review_mode(job) != "off":
                after = JobState.REVIEW
            else:
                after = JobState.QA if done else JobState.DEVELOPING
            return self.orchestrator.transition(
                job,
                after,
                note=f"build gate passed for phase {index + 1}/{len(phases)}",
                detail=gate.tail,
            )

        # whether the last fix moved anything at all, decided before the record of it is
        # overwritten: byte-identical output means the specialist changed nothing the
        # command could notice, and the supervisor cannot see that from one attempt alone
        repeated = job.data.last_build_output == gate.for_model
        job.data.build_attempts += 1
        # the developer's next prompt carries this on every retry: the errors, not the run
        job.data.last_build_output = gate.for_model
        job.data.rerun_only = False  # the specialist now fixes it the ordinary way
        self.store.save(job)
        if job.data.build_attempts >= self.max_build_attempts:
            return self._fail(
                job,
                f"build gate failed {job.data.build_attempts} times on phase {index + 1}",
                detail=gate.tail,
            )
        note = (
            f"build gate failed on phase {index + 1} "
            f"(attempt {job.data.build_attempts}/{self.max_build_attempts})"
        )
        choice, reason = self._failed_gate_choice(job, index, gate.for_model, repeated=repeated)
        if choice == "replan":
            return self._replan_from(
                job,
                index,
                f"phase {index + 1} failed the build gate {job.data.build_attempts} time(s); "
                f"the supervisor asked for a re-plan: {reason}\n\n{gate.tail[-2000:]}",
                note=f"{note}; supervisor: re-plan from phase {index + 1} ({reason})",
                detail=gate.tail,
            )
        if choice == "ask_human":
            job.data.resume_state = JobState.DEVELOPING.value
            self.store.save(job)
            return self.orchestrator.transition(
                job,
                JobState.AWAITING_DECISION,
                note=f"{note}; supervisor: asks you ({reason})",
                detail=gate.tail,
            )
        suffix = f"; supervisor: same specialist fixes ({reason})" if reason else ""
        return self.orchestrator.transition(
            job, JobState.DEVELOPING, note=f"{note}{suffix}", detail=gate.tail
        )

    def _qa_gate_triage(self, job: Job, index: int, output: str) -> bool:
        """The tester reads a failed build gate before anyone starts fixing code.

        QA answers one question: was the failing test wrong, or was the code? A test that
        asserts something nobody agreed to is QA's own mistake, so QA rewrites it, the gate
        runs again, and no specialist fix attempt is spent on it. Anything else is the
        code's fault and QA's reading of the failure is kept for the specialist instead of
        a patch. Either way the reason is written into the history, so the record says
        which side was wrong and why rather than only that something failed.

        Returns whether the tests were corrected, i.e. whether the gate is worth re-running.
        """
        if job.data.rerun_only:
            return False  # a person re-ran the tests by hand; nobody asked for a rewrite
        if job.data.qa_gate_fixes >= self.max_qa_gate_fixes:
            return False
        profile = self._profile(job)
        phases = self._phases(job)
        phase = {"number": index + 1, **(phases[index] if index < len(phases) else {})}
        # only a fresh reading reaches the specialist: last attempt's is not this one's
        job.data.qa_diagnosis = None
        self.store.save(job)
        result = self._invoke(
            RoleName.QA,
            qa.triage,
            job,
            profile=profile,
            build_failure=output[-8000:],
            phase=phase,
            branch_diff=self._phase_diff(job),
        )
        if not result.ok or not isinstance(result.output, QAResult):
            return False  # the gate is handled as before; a silent tester blocks nothing
        out = result.output
        at = f"qa: phase {index + 1}:"  # the note says which phase, so it groups with it
        if out.gate_verdict != "test_is_wrong":
            return self._qa_blames_the_code(job, index, out.summary, output)
        stray = sorted(c.path for c in out.changes if not qa.is_test_path(c.path))
        if stray:
            # "the test was wrong" is never a licence to edit the code under test
            self._record_gate_note(
                job,
                f"{at} test fix refused, it changed {', '.join(stray)} — not a test file",
                out.summary,
            )
            return self._qa_blames_the_code(job, index, out.summary, output)
        if not out.changes:
            self._record_gate_note(
                job, f"{at} called the test wrong but sent no correction", out.summary
            )
            return False
        try:
            touched = apply_changes(job, profile, RoleName.QA, out.changes)
        except (PermissionError, EditMismatch) as exc:
            self._record_gate_note(job, f"{at} test fix not written ({exc})", out.summary)
            return False
        worktree = require_worktree(job)
        g.stage_all(worktree)
        job.data.qa_gate_fixes += 1
        job.data.qa_diagnosis = None
        self.store.save(job)
        self._record_gate_note(
            job,
            f"{at} the test was wrong, corrected ({len(touched)} files) — {out.summary}",
            g.staged_diff(worktree) or "(no changes)",
        )
        return True

    def _qa_blames_the_code(self, job: Job, index: int, summary: str, output: str) -> bool:
        """QA read the failure and the code is the side that is wrong: keep the reading for
        the specialist, record it, and let the gate fail the ordinary way."""
        job.data.qa_diagnosis = summary or None
        self.store.save(job)
        self._record_gate_note(
            job,
            f"qa: phase {index + 1}: the code is wrong, not the test — {summary}",
            output[-2000:],
        )
        return False

    def _record_gate_note(self, job: Job, note: str, detail: str | None) -> None:
        self.store.update_state(job.id, job.state, note=note, detail=detail)
        job.history = self.store.get(job.id).history

    def _failed_gate_choice(
        self, job: Job, index: int, output: str, *, repeated: bool = False
    ) -> tuple[str, str]:
        """The one decision code cannot make: after a failed build gate, does the same
        specialist fix it, does the architect re-plan, or does a human look? Without a
        supervisor (manual projects) the specialist fixes, as before."""
        if self.supervisor_settings(job).mode == "manual":
            return "fix", ""
        profile = self._profile(job)
        phases = self._phases(job)
        result = self._invoke(
            RoleName.SUPERVISOR,
            supervisor.run,
            job,
            profile=profile,
            gate_material={
                "failed_build_gate": {
                    "phase": {"number": index + 1, **phases[index]},
                    "attempt": job.data.build_attempts,
                    "max_attempts": self.max_build_attempts,
                    "repeated": repeated,
                    "output": output[-4000:],
                    "commands": {
                        # the commands are the profile's and no specialist can change
                        # them; when one of these is what failed, only a re-plan helps
                        "build_cmd": profile.build_cmd,
                        "test_cmd": profile.test_cmd,
                    },
                },
                "choices": {
                    "fix": "the same specialist tries again with the build output",
                    "replan": "the architect re-plans (the change is larger than one phase)",
                    "ask_human": "a person should look before more model time is spent",
                },
            },
            jira=None,
        )
        if not result.ok or not isinstance(result.output, SupervisorResult):
            return "fix", "supervisor unavailable"
        out = result.output
        choice = out.decision if out.decision in ("fix", "replan", "ask_human") else "fix"
        reason = "; ".join(out.reasons) or out.summary
        self.store.update_state(
            job.id,
            job.state,
            note=f"supervisor: {choice} ({reason})",
            detail=json.dumps(out.model_dump(mode="json"), indent=2),
        )
        job.history = self.store.get(job.id).history
        return choice, reason

    # -- standards review (T9.5) -----------------------------------------------------------

    def review_mode(self, job: Job) -> str:
        if self.review_override is not None:
            return self.review_override
        project = self._project_of(job)
        return "advisory" if project is None else str(project.review)

    def _phase_diff(self, job: Job) -> str:
        worktree = require_worktree(job)
        base = job.data.phase_base_commit
        if base is None:
            return "(phase base unknown)"
        return g.diff(worktree, base) or "(no changes)"

    def _review(self, job: Job) -> Job:
        """QA reviews the phase just built against the standards its specialist read.
        Advisory projects record the findings and move on; blocking projects send blocking
        findings back to the specialist (two rounds), then ask the human."""
        profile = self._profile(job)
        phases = self._phases(job)
        index = job.data.phase_index - 1
        if index < 0 or index >= len(phases):
            return self._fail(job, "no phase to review")
        phase = phases[index]
        mode = self.review_mode(job)
        specialist = specialist_for(phase.get("domain"))
        # the reviewer reads exactly the sections the specialist was given
        retrieved = self.standards_for(job, specialist, profile)
        result = self._invoke(
            RoleName.QA,
            review.run,
            job,
            profile=profile,
            phase=phase,
            phase_number=index + 1,
            phase_diff=self._phase_diff(job),
            standards=retrieved.as_context() if retrieved else None,
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, QAResult)
        violations = [v.model_dump(mode="json") for v in result.output.violations]
        blocking = [v for v in violations if v["severity"] == "blocking"]
        advisory = [v for v in violations if v["severity"] != "blocking"]
        done = job.data.phase_index >= len(phases)
        next_state = JobState.QA if done else JobState.DEVELOPING
        label = f"review phase {index + 1}/{len(phases)}"
        counts = (
            f"{len(violations)} violation(s), {len(blocking)} blocking, {len(advisory)} advisory"
            if violations
            else "clean"
        )
        record: dict[str, Any] = {
            "phase": index + 1,
            "round": job.data.review_rounds,
            "mode": mode,
            "summary": result.output.summary,
            "violations": violations,
            "blocking": len(blocking),
            "advisory": len(advisory),
            "verdict": "",
        }
        detail = json.dumps(record, indent=2)

        if blocking and mode == "blocking":
            job.data.review_violations = blocking
            if job.data.review_rounds < self.max_review_rounds:
                job.data.review_rounds += 1
                job.data.phase_index = index  # the specialist reworks this phase
                record["verdict"] = f"fix round {job.data.review_rounds}/{self.max_review_rounds}"
                job.data.reviews.append(record)
                self.store.save(job)
                return self.orchestrator.transition(
                    job,
                    JobState.DEVELOPING,
                    note=f"{label}: {counts}; {record['verdict']}",
                    detail=json.dumps(record, indent=2),
                )
            record["verdict"] = "needs your decision"
            job.data.reviews.append(record)
            self.store.save(job)
            return self.orchestrator.transition(
                job,
                JobState.AWAITING_REVIEW_APPROVAL,
                note=(
                    f"{label}: {counts} after {job.data.review_rounds} fix round(s); "
                    "needs your decision"
                ),
                detail=json.dumps(record, indent=2),
            )

        record["verdict"] = "passed" if not violations else f"passed ({mode})"
        job.data.reviews.append(record)
        job.data.review_violations = []
        job.data.review_rounds = 0
        self.store.save(job)
        return self.orchestrator.transition(
            job, next_state, note=f"{label}: {counts}", detail=detail
        )

    def _qa(self, job: Job) -> Job:
        return self._qa_propose(job) if job.data.qa_stage == 1 else self._qa_write(job)

    def _qa_propose(self, job: Job) -> Job:
        profile = self._profile(job)
        diff = self._branch_diff(job)
        result = self._invoke(RoleName.QA, qa.run, job, profile=profile, branch_diff=diff)
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, QAResult)
        if not result.output.test_cases:
            # the cases ended up in the prose: ask once more for the array, then give up
            # readably rather than park a gate with nothing to approve
            self.store.update_state(
                job.id,
                job.state,
                note="qa: no test cases in the answer; asking again for the list",
                detail=result.output.summary,
            )
            job.history = self.store.get(job.id).history
            result = self._invoke(
                RoleName.QA,
                qa.run,
                job,
                profile=profile,
                branch_diff=diff,
                problem=(
                    "`test_cases` was empty; the cases you described in `summary` must be "
                    "returned as entries of the `test_cases` array (name + description)"
                ),
            )
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, QAResult)
            if not result.output.test_cases:
                return self._fail(
                    job,
                    "qa returned no test cases twice; retry, or switch QA to a stronger model",
                    detail=result.output.summary,
                )
        output = result.output
        assert isinstance(output, QAResult)
        job.data.test_cases = [c.model_dump() for c in output.test_cases]
        job.data.feedback = None
        self.store.save(job)
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_TEST_APPROVAL,
            note=f"qa: {len(job.data.test_cases)} test cases proposed",
            detail=json.dumps(
                {"summary": output.summary, "test_cases": job.data.test_cases}, indent=2
            ),
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
            try:
                touched = apply_changes(job, profile, RoleName.QA, result.output.changes)
            except EditMismatch as exc:
                return self._fail(job, "qa's tests could not be applied", detail=str(exc))
            g.stage_all(worktree)
            test_diff = g.staged_diff(worktree)
            gate = self._final_gate(job)
            if gate.ok:
                if g.commit(worktree, "slipwright: tests"):
                    self._push(job, worktree, "qa: tests")
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
            job.data.last_build_output = gate.for_model
            self.store.save(job)
            if job.data.build_attempts >= self.max_build_attempts:
                return self._fail(
                    job,
                    f"qa tests failed the build gate {job.data.build_attempts} times",
                    detail=gate.tail,
                )

    def _deployment_files(self, job: Job) -> dict[str, str]:
        """What the branch already holds under the deployment folder."""
        worktree = require_worktree(job)
        folder = worktree / devops.DEPLOY_FOLDER
        if not folder.is_dir():
            return {}
        names = [
            (p.relative_to(worktree)).as_posix() for p in sorted(folder.rglob("*")) if p.is_file()
        ]
        return read_files(worktree, names)

    def _deploy_gate(self, job: Job) -> Job:
        """Stage one: DevOps proposes how this project is deployed and the person decides.

        A project that is not deployed to a cloud, or whose deployment folder already
        holds what this change needs, comes back with no scripts: there is nothing to
        approve, so the job goes straight on to the pull request.

        ``target: none`` is not the same as "no files". A library has nothing to deploy
        and still wants a build pipeline, and the pipeline is a file landing in somebody's
        repository, so it goes to the gate like any other.
        """
        profile = self._profile(job)
        existing = self._deployment_files(job)
        result = self._invoke(
            RoleName.DEVOPS,
            devops.plan_deploy,
            job,
            profile=profile,
            existing=existing,
            source=self._source_of(job),
        )
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, DeployPlan)
        plan = result.output
        # A path DevOps may not write is refused here, before anybody approves it. It was
        # only caught at the write, after the yes: the development failed there, and a
        # retry wrote the same approved plan into the same refusal every time.
        source = self._source_of(job)
        stray = devops.outside((s.path for s in plan.scripts), source)
        if stray:
            self.store.update_state(
                job.id,
                job.state,
                note=f"devops: proposed files it may not write ({', '.join(stray)}); asking again",
                detail=plan.summary,
            )
            job.history = self.store.get(job.id).history
            job.data.output_hashes = {}  # the refusal changes the input: not a loop
            self.store.save(job)
            result = self._invoke(
                RoleName.DEVOPS,
                devops.plan_deploy,
                job,
                profile=profile,
                existing=existing,
                source=source,
                problem=(
                    f"`scripts` named {', '.join(stray)}, which DevOps may not write. Every "
                    f"path must be under `{devops.DEPLOY_FOLDER}/` or be the pipeline file; "
                    f"the project's own README.md is the Architect's, not yours"
                ),
            )
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, DeployPlan)
            plan = result.output
            stray = devops.outside((s.path for s in plan.scripts), source)
            if stray:
                # twice is a model that will not be told; the rest of its plan is still
                # good, so the paths go and the person is shown that they went
                plan.scripts = [s for s in plan.scripts if s.path not in stray]
                plan.notes.append(
                    f"Left out, because DevOps may not write them: {', '.join(stray)}"
                )
        job.data.deploy = plan.model_dump(mode="json")
        job.data.feedback = None
        self.store.save(job)
        if not plan.scripts:
            job.data.devops_stage = 2
            self.store.save(job)
            self.store.update_state(
                job.id,
                job.state,
                note=f"devops: nothing to deploy — {plan.summary}",
                detail=json.dumps(job.data.deploy, indent=2),
            )
            return self._devops(self.store.get(job.id))
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_DEPLOY_APPROVAL,
            note=(f"devops: {len(plan.scripts)} deployment script(s) proposed for {plan.target}"),
            detail=json.dumps(job.data.deploy, indent=2),
        )

    def _write_deployment(self, job: Job) -> Job | None:
        """Stage two, first half: write the approved scripts into ``deployment/``.

        Returns the job to stop on (failed, or back at the deployment gate), or None when
        the branch is ready for its pull request. Paths are confined to the deployment
        folder and to the one file this project's host runs its pipeline from: DevOps is
        opening a pull request, not editing the product. Anything else is a failure rather
        than a silent trim, because a script that was approved and quietly dropped is worse
        than one that never ran.
        """
        plan = job.data.deploy or {}
        if job.data.deploy_written or job.data.deploy_skipped or not plan.get("scripts"):
            return None
        stray = devops.outside(
            (str(s.get("path", "")) for s in plan["scripts"]), self._source_of(job)
        )
        if stray:
            # approved before the proposal was checked: writing it can only be refused, so
            # every retry failed in the same place. It goes back to be proposed again.
            job.data.devops_stage = 1
            job.data.feedback = (
                f"The approved plan names {', '.join(stray)}, which DevOps may not write. "
                f"Propose it again with every file under {devops.DEPLOY_FOLDER}/ or the "
                f"pipeline file."
            )
            self.store.save(job)
            self.store.update_state(
                job.id,
                job.state,
                note=f"devops: the approved plan names {', '.join(stray)}; proposing again",
            )
            return self._deploy_gate(self.store.get(job.id))
        profile = self._profile(job)
        worktree = require_worktree(job)
        # An approved plan of seven files does not always fit in one answer. The phases
        # take several parts for the same reason, so the deployment does too: each part
        # is applied and DevOps is called again with what is already written.
        touched: list[str] = []
        summaries: list[str] = []
        continuation: dict[str, Any] | None = None
        prefix = f"{devops.DEPLOY_FOLDER}/"
        source = self._source_of(job)
        pipeline = devops.ci_path(source)
        for part in range(1, self.max_phase_parts + 1):
            result = self._invoke(
                RoleName.DEVOPS,
                devops.write_deployment,
                job,
                profile=profile,
                existing=self._deployment_files(job),
                continuation=continuation,
                source=self._source_of(job),
            )
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, DeveloperResult)
            stray = devops.outside((c.path for c in result.output.changes), source)
            if stray:
                allowed = f"{prefix} or {pipeline}" if pipeline else prefix
                return self._fail(
                    job,
                    f"devops wrote outside {allowed}: {', '.join(sorted(stray))}",
                    detail=result.output.summary,
                )
            try:
                written = apply_changes(job, profile, RoleName.DEVOPS, result.output.changes)
            except (PermissionError, EditMismatch) as exc:
                return self._fail(job, f"devops: {exc}")
            touched.extend(t for t in written if t not in touched)
            summaries.append(result.output.summary)
            if result.output.phase_complete or part == self.max_phase_parts:
                break
            g.stage_all(worktree)
            self.store.update_state(
                job.id,
                job.state,
                note=(
                    f"devops part {part}: {result.output.summary} "
                    f"({len(written)} file(s), more to come)"
                ),
                detail=g.staged_diff(worktree) or "(no changes)",
            )
            job.history = self.store.get(job.id).history
            continuation = {
                "part": part + 1,
                "files_so_far": list(touched),
                "summary_so_far": " ".join(summaries),
            }
        if not touched:
            return self._fail(job, "devops wrote no deployment files", detail=" ".join(summaries))
        job.data.deploy_written = touched
        self.store.save(job)
        g.stage_all(worktree)
        diff = g.staged_diff(worktree)
        if g.commit(worktree, f"slipwright: deployment ({plan.get('target')})"):
            self._push(job, worktree, "devops: deployment files")
        parts = f" in {len(summaries)} parts" if len(summaries) > 1 else ""
        self.store.update_state(
            job.id,
            job.state,
            note=(f"devops: {len(touched)} deployment file(s) written{parts} — {summaries[-1]}"),
            detail=diff or "(no changes)",
        )
        job.history = self.store.get(job.id).history
        return None

    def _devops(self, job: Job) -> Job:
        profile = self._profile(job)
        worktree = require_worktree(job)
        if Permission.GIT_PUSH not in profile.roles[RoleName.DEVOPS].permissions:
            return self._fail(job, "devops role lacks the git_push permission")
        if job.data.devops_stage == 1 and job.data.pr_url is None:
            return self._deploy_gate(job)
        failed = self._write_deployment(job)
        if failed is not None:
            return failed
        job = self.store.get(job.id)

        if job.data.pr_url is None:
            result = self._invoke(
                RoleName.DEVOPS,
                devops.run,
                job,
                profile=profile,
                changed_files=self._branch_files(job),
            )
            if not result.ok:
                return self._invocation_failed(job, result)
            assert isinstance(result.output, DevOpsResult)
            try:
                host = self._host_of(job)
            except SourceError as exc:
                # No token for the host. That is a failure for a project that has a
                # repository on one -- and no kind of failure at all for a checkout with
                # nowhere to push, which is most of them on somebody's own machine. The
                # token was asked for before anybody looked at whether a remote existed,
                # so a local project crashed here instead of finishing.
                if not g.has_remote(worktree):
                    return self._done_locally(job, result.output)
                return self._fail(job, f"devops: {exc}")
            try:
                host.push(worktree, job.branch)
                finish = getattr(host, "finish_pr", None)
                if job.data.draft_pr_url and finish is not None:
                    # the draft opened at the first push gets DevOps' words and is made
                    # ready for review, rather than a second pull request being opened
                    job.data.pr_url = finish(
                        worktree, job.branch, result.output.pr_title, result.output.pr_body
                    )
                else:
                    job.data.pr_url = host.open_pr(
                        worktree, job.branch, result.output.pr_title, result.output.pr_body
                    )
            except NoRemote:
                return self._done_locally(job, result.output)
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
            fixer = self._last_specialist(job)
            fix = self._invoke(
                fixer,
                developer.run,
                job,
                profile=profile,
                ci_failure=status.log or status.summary,
                as_role=fixer,
            )
            if not fix.ok:
                return self._invocation_failed(job, fix)
            assert isinstance(fix.output, DeveloperResult)
            try:
                apply_changes(job, profile, fixer, fix.output.changes)
            except EditMismatch as exc:
                return self._fail(job, "the CI fix could not be applied", detail=str(exc))
            g.stage_all(worktree)
            g.commit(worktree, f"slipwright: CI fix {job.data.ci_attempts}: {fix.output.summary}")
            try:
                self._host_of(job).push(worktree, job.branch)
            except GitHostError as exc:
                return self._fail(job, f"devops: {exc}")

    def _done_locally(self, job: Job, result: DevOpsResult) -> Job:
        """A local checkout with no remote: there is nowhere to push and no pull request
        to open, so the finished branch stays in the checkout and the DevOps write-up
        becomes the note for whoever merges it."""
        project = self._project_of(job)
        checkout = project.repo_path if project else None
        return self.orchestrator.transition(
            job,
            JobState.DONE,
            note=(
                f"nothing was pushed: the checkout {checkout} has no remote. Branch "
                f"{job.branch} is ready there — merge it with `git merge {job.branch}`, or "
                f"set the project's GitHub repository so the next development pushes and "
                f"opens a pull request"
            ),
            detail=f"{result.pr_title}\n\n{result.pr_body}".strip(),
        )

    def _poll_ci(self, job: Job) -> CiStatus:
        worktree = require_worktree(job)
        assert job.data.pr_url is not None
        deadline = time.monotonic() + self.ci_timeout_s
        while True:
            status = self._host_of(job).ci_status(worktree, job.branch, job.data.pr_url)
            if status.terminal or time.monotonic() >= deadline:
                return status
            time.sleep(self.ci_poll_s)


def _reworded(planned: dict[str, Any], edited: Breakdown) -> dict[str, Any]:
    """The plan keeps its own copy of the breakdown (with the phase numbers); carry the new
    wording into it so the two never disagree."""
    titles = {t.id: (t.title, t.description) for t in edited.tasks()}
    stories = {s.id: (s.title, s.description) for e in edited.epics for s in e.stories}
    epics = {e.id: (e.title, e.description) for e in edited.epics}
    out = Breakdown.model_validate(planned)
    for epic in out.epics:
        epic.title, epic.description = epics.get(epic.id, (epic.title, epic.description))
        for story in epic.stories:
            story.title, story.description = stories.get(story.id, (story.title, story.description))
            for task in story.tasks:
                task.title, task.description = titles.get(task.id, (task.title, task.description))
    return out.model_dump(mode="json")


def is_approval_state(state: JobState) -> bool:
    return state in APPROVAL_STATES


__all__ = [
    "APPROVAL_EDGES",
    "WORKING_STATES",
    "Engine",
    "JobIsRunning",
    "NotAwaitingApproval",
    "ProjectCloneError",
]
