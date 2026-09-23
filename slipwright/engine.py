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

import hashlib
import inspect
import json
import logging
import os
import threading
import time
import traceback
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import httpx
from pydantic import ValidationError

from slipwright.events import EventBus
from slipwright.gates import DEFAULT_TIMEOUT_S as GATE_TIMEOUT_S
from slipwright.gates import GateResult, build_gate, run_command
from slipwright.githost import CiState, CiStatus, GitHost, GitHostError, NoRemote
from slipwright.github import GitHubClient, GitHubError, GitHubSettings
from slipwright.invoke import DEFAULT_TIMEOUT_S, RETRYABLE, InvokeError, InvokeErrorKind, RoleResult
from slipwright.jira import DEFAULT_ISSUE_TYPES, JiraClient, JiraError, JiraSettings
from slipwright.jiraactions import ActionOutcome, ActionRunner, jira_context
from slipwright.jirasync import JiraSync
from slipwright.orchestrator import IllegalTransitionError, Orchestrator
from slipwright.providers import ModelProvider, ProviderUnavailableError
from slipwright.providers.registry import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    Credentials,
    RoutingProvider,
    list_models,
)
from slipwright.roles import architect, developer, devops, po, qa, review, supervisor
from slipwright.roles.common import apply_changes, require_worktree
from slipwright.roles.results import (
    ArchitectResult,
    Breakdown,
    DeveloperResult,
    DevOpsResult,
    PlanPhase,
    POResult,
    QAResult,
    SupervisorResult,
)
from slipwright.roles.specialists import specialist_for
from slipwright.schemas.job import (
    APPROVAL_STATES,
    ChangedFile,
    Commit,
    Job,
    JobData,
    JobResult,
    JobState,
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
from slipwright.standards import GLOBAL_DIR, PROJECT_SUBDIR, load_corpus
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
from slipwright.store import JobInProgress, JobStore, ProjectNotFound
from slipwright.workspace import Workspace
from slipwright.workspace import git as g

log = logging.getLogger(__name__)

WORKING_STATES: frozenset[JobState] = frozenset(
    {
        JobState.BACKLOG,
        JobState.ARCHITECTURE,
        JobState.DEVELOPING,
        JobState.BUILD_GATE,
        JobState.REVIEW,
        JobState.QA,
        JobState.DEVOPS,
    }
)

# approval state -> (state on approve, state on reject)
APPROVAL_EDGES: dict[JobState, tuple[JobState, JobState]] = {
    JobState.AWAITING_BACKLOG_APPROVAL: (JobState.ARCHITECTURE, JobState.BACKLOG),
    JobState.AWAITING_ARCHITECTURE_APPROVAL: (JobState.DEVELOPING, JobState.ARCHITECTURE),
    # accepting the violations continues with the next phase (or QA); rejecting sends the
    # phase back to its specialist
    JobState.AWAITING_REVIEW_APPROVAL: (JobState.DEVELOPING, JobState.DEVELOPING),
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
    if edges is not None and job.state is JobState.AWAITING_REVIEW_APPROVAL:
        phases = (job.data.plan or {}).get("phases", [])
        if job.data.phase_index >= len(phases):
            return (JobState.QA, JobState.DEVELOPING)
    if job.state is JobState.AWAITING_DECISION:
        back = JobState(job.data.resume_state or JobState.DEVELOPING.value)
        return (back, back)
    return edges


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


class EmptyApproval(ValueError):
    """A gate whose material is empty cannot be approved (nothing would happen next)."""


class InvalidEdit(ValueError):
    """A human edit at a gate does not pass the same checks as the agent's output."""


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
        max_review_rounds: int = 2,
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
        self.standards_db = workspace.worktrees_root.parent / "standards.sqlite3"
        self.standards_dir = GLOBAL_DIR
        # where the UI looks for local checkouts to register (None: type a path)
        self.local_repos_root: Path | None = None
        self._standards_index: StandardsIndex | None = None
        self._standards_editor: StandardsEditor | None = None
        self.orchestrator = Orchestrator(store)
        self.seed_profile = seed_profile
        self._provider = provider
        self.timeout_s = timeout_s
        self.max_reject_rounds = max_reject_rounds
        self.max_build_attempts = max_build_attempts
        self.max_ci_attempts = max_ci_attempts
        self.max_review_rounds = max_review_rounds
        self.max_phase_parts = max_phase_parts  # answers one phase may take (T9.7 follow-up)
        # a forced standards-review mode (off/advisory/blocking); None follows the project
        self.review_override = review
        # a forced gate mode (manual/assisted/auto); None follows the project
        self.supervisor_override = supervisor_mode
        # first retry waits this long, then doubles (T9.7); tests set it to 0
        self.retry_backoff_s = retry_backoff_s
        self.gate_timeout_s = gate_timeout_s
        self._git_host = git_host
        # tests answer GitHub/Jira HTTP locally through a mock transport
        self.http_transport = http_transport
        self.ci_poll_s = ci_poll_s
        self.ci_timeout_s = ci_timeout_s
        self.handlers: dict[JobState, Handler] = {
            JobState.BACKLOG: self._backlog,
            JobState.ARCHITECTURE: self._architecture,
            JobState.DEVELOPING: self._develop,
            JobState.BUILD_GATE: self._build_gate,
            JobState.REVIEW: self._review,
            JobState.QA: self._qa,
            JobState.DEVOPS: self._devops,
        }
        self._locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        # one test run at a time per checkout, so runs never trample each other's files
        self._checkout_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
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
        Agents, else the profile's provider, else the default provider and its model."""
        assigned = self.agent_routing(role.value) if role is not None else None
        if assigned is not None:
            return assigned
        if cfg.provider:
            return cfg.provider, cfg.model
        name = self.default_provider_name()
        return name, self.default_model_for(name) or cfg.model

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

    def provider_credentials(self, name: str) -> Credentials | None:
        """Stored key first, else the vendor's environment variable; None when neither."""
        spec = PROVIDERS.get(name)
        if spec is None:
            return None
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
            data: dict[str, Any] = self.store.get_setting(f"providers.{spec.name}", {}) or {}
            stored = self.store.get_setting(f"providers.{spec.name}.api_key")
            env = os.environ.get(spec.env_var)
            key = stored or env
            out.append(
                {
                    "name": spec.name,
                    "label": spec.label,
                    "env_var": spec.env_var,
                    "docs_url": spec.docs_url,
                    "default_base_url": spec.default_base_url,
                    "base_url": data.get("base_url"),
                    "key_set": bool(key),
                    "key_hint": f"…{str(key)[-4:]}" if key else None,
                    "key_from_env": bool(env) and not stored,
                    "is_default": spec.name == default,
                    "default_model": data.get("default_model"),
                    "max_tokens": data.get("max_tokens"),
                    "default_max_tokens": spec.max_tokens,
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
        if make_default:
            self.store.set_setting("providers.default", name)
        # a changed key or URL must not keep serving from a stale cached client
        if isinstance(self._provider, RoutingProvider):
            self._provider = None

    def provider_models(self, name: str) -> list[str]:
        creds = self.provider_credentials(name)
        if creds is None:
            spec = PROVIDERS[name]
            raise ProviderUnavailableError(f"no API key for {spec.label}; set it or {spec.env_var}")
        return list_models(creds, transport=self.http_transport)

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

    def host_for(self, project: Project | None) -> SourceHost:
        """The host a project belongs to; the default for a project that names none."""
        if self._git_host is not None:
            # injected (tests, or a single-host deployment): it answers push/open_pr/
            # ci_status, which is all a running job asks of a host
            return cast(SourceHost, self._git_host)
        return self.source_host(project.source if project else None)

    def _host_of(self, job: Job) -> SourceHost:
        return self.host_for(self._project_of(job))

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

    def _agent_jira_client(self) -> JiraClient | None:
        try:
            return self.jira_client(agent=True)
        except JiraError:
            return None

    def _apply_jira_actions(
        self, job: Job, role: RoleName, profile: Profile, project: Project, actions: list[Any]
    ) -> None:
        """Run a role's ``jira_actions`` (permission and confinement checked by the runner)
        and record every outcome, executed or refused, in the job's history."""
        if not actions:
            return
        client = self._agent_jira_client() if project.jira_project_key else None
        runner = ActionRunner(client, project)
        outcomes = runner.run(job, role, profile, list(actions))
        self._record_jira_outcomes(job, role, outcomes)

    def _retry_jira_queue(self, job: Job) -> Job:
        if not job.data.jira_queue:
            return job
        project = self._project_of(job)
        if project is None:
            return job
        client = self._agent_jira_client()
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
        if self._standards_index is None:
            self.standards_db.parent.mkdir(parents=True, exist_ok=True)
            self._standards_index = StandardsIndex(self.standards_db, self._build_embedder())
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
        self, project_id: str | None = None, *, force: bool = False
    ) -> dict[str, Any]:
        """Index the global corpus, or one project's overrides. Skipped when the files did
        not change since the last pass unless ``force``."""
        index = self.standards_index
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

    def ensure_standards_indexed(self, project_id: str | None = None) -> None:
        """Cheap mtime check, then an incremental reindex if anything changed."""
        try:
            self.reindex_standards(None)
            if project_id is not None:
                self.reindex_standards(project_id)
        except StandardsIndexError as exc:
            log.warning("standards index unavailable: %s", exc)

    def search_standards(
        self, query: str, domain: str | None, *, project_id: str | None = None, k: int | None = None
    ) -> list[Hit]:
        self.ensure_standards_indexed(project_id)
        return self.standards_index.search(
            query, domain, k=k or self.standards_settings()["top_k"], project_id=project_id
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
        try:
            self.ensure_standards_indexed(project.id if project else None)
            index = self.standards_index
        except StandardsIndexError as exc:
            log.warning("standards unavailable for %s: %s", role.value, exc)
            return None
        project_id = project.id if project else None

        def search(query: str, domain: str | None, k: int) -> list[Hit]:
            return index.search(query, domain, k=k, project_id=project_id)

        def browse(domain: str | None, k: int) -> list[Hit]:
            return index.browse(domain, k=k, project_id=project_id)

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
        settings = self.jira_settings()
        if not settings.configured:
            return None
        return JiraSync(self.jira_client(), project, settings.issue_types)

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
        if project.repo_path is None:
            url = project.effective_clone_url
            if url is None:
                raise ValueError("project needs a repo_path or a github_repo/clone_url")
            target = self.repos_root / project.id
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                g.clone(self._authenticated(url, project.source), target)
            except g.GitError as exc:
                raise ProjectCloneError(f"could not clone {url}: {exc.stderr}") from exc
            project = project.model_copy(update={"repo_path": target})
        elif not project.repo_path.is_dir():
            raise ValueError(f"repo_path is not a directory: {project.repo_path}")
        else:
            self._ensure_git_repository(project.repo_path)
        self._wire_remote(project)
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

    @staticmethod
    def _ensure_git_repository(path: Path) -> None:
        """A plain folder becomes a repository with everything in it committed, so jobs
        can branch from it; an existing repository is left exactly as it is."""
        if (path / ".git").exists():
            return
        try:
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
        self, request: str, repo_path: Path | None = None, *, project_id: str | None = None
    ) -> Job:
        """Create a job inside a project.

        With ``project_id`` the job uses that project's checkout. With only ``repo_path``
        the repository's project is looked up, or created on the spot, so callers that
        predate projects keep working.
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
        return self.store.create(
            Job(
                project_id=project.id,
                request=request,
                repo_path=project.repo_path,
                data=JobData(language=project.language),
            )
        )

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
        if by:
            note = f"{note} by {by}"
        if job.state is JobState.AWAITING_DECISION:
            note = f"{note}: continue with {edges[0].value}"
            job.data.resume_state = None
        job.data.feedback = None
        job.data.reject_rounds = 0
        job.data.output_hashes = {}  # a human decision is a fresh start for the loop check
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
        job.data.output_hashes = {}  # the feedback changes the input: not a loop
        if job.state is JobState.AWAITING_REVIEW_APPROVAL:
            # back to the specialist for another round on the same phase
            job.data.phase_index = max(job.data.phase_index - 1, 0)
            job.data.review_rounds = 0
            job.data.reject_rounds = 0
        if job.state is JobState.AWAITING_DECISION:
            from slipwright.schemas.job import InboxMessage

            # the feedback reaches the role that continues, through the inbox
            job.data.inbox.append(InboxMessage(text=feedback))
            job.data.feedback = None
            job.data.reject_rounds = 0
            job.data.resume_state = None
        self.store.save(job)
        job = self.orchestrator.transition(job, edges[1], note=f"rejected: {feedback}")
        return self._run(job) if run else job

    def set_profile(self, job_id: str, profile: Profile) -> Job:
        """Replace the proposed profile while the job waits for its approval."""
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_ARCHITECTURE_APPROVAL:
            raise NotAwaitingApproval(job)
        job.profile = profile
        return self.store.save(job)

    def set_backlog(self, job_id: str, breakdown: dict[str, Any]) -> Job:
        """Replace the proposed backlog while the job waits at the backlog gate."""
        job = self.store.get(job_id)
        if job.state is not JobState.AWAITING_BACKLOG_APPROVAL:
            raise NotAwaitingApproval(job)
        try:
            tree = Breakdown.model_validate(breakdown)
            POResult(summary="edited", breakdown=tree)  # the PO's own checks (unique ids)
        except ValidationError as exc:
            raise InvalidEdit(str(exc)) from exc
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
            phases = [PlanPhase.model_validate(p) for p in plan.get("phases", [])]
            breakdown = Breakdown.model_validate(
                plan.get("breakdown") or current.get("breakdown") or job.data.backlog
            )
            POResult(summary="edited", breakdown=breakdown)
        except ValidationError as exc:
            raise InvalidEdit(str(exc)) from exc
        if not phases:
            raise InvalidEdit("a plan needs at least one phase")
        mapping = architect.phase_task_map(phases, [t.id for t in breakdown.tasks()])
        if isinstance(mapping, str):
            raise InvalidEdit(f"plan does not match the backlog: {mapping}")
        for task in breakdown.tasks():
            task.phase = mapping[task.id]
        decisions = plan.get("decisions", current.get("decisions", []))
        job.data.plan = {
            "summary": str(plan.get("summary", current.get("summary", ""))),
            "decisions": [str(d) for d in decisions],
            "phases": [p.model_dump(mode="json") for p in phases],
            "breakdown": breakdown.model_dump(mode="json"),
        }
        job.data.phase_index = 0
        return self.store.save(job)

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

        ``tests`` runs the build gate: the test command over the current worktree, nothing
        rewritten. ``devops`` runs the DevOps step from the top — the write-up, the push
        and the pull request — which is how a development that finished with nowhere to
        push reaches GitHub once the project names a repository.

        Only a development that has stopped can be re-run; a running one is left alone.
        """
        targets = {"tests": JobState.BUILD_GATE, "devops": JobState.DEVOPS}
        if step not in targets:
            raise ValueError(f"unknown step {step!r}; expected one of {sorted(targets)}")
        job = self.store.get(job_id)
        if job.state in WORKING_STATES:
            raise JobIsRunning(job)
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
        if back is JobState.DEVOPS:
            # the pull request is opened again; without this the step would only poll CI
            job.data.pr_url = None
        self.store.save(job)
        job = self.orchestrator.transition(job, back, note=f"re-run by hand: {step}")
        return self._run(job) if run else job

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
                        "gate": gate,
                        "confidence": record.get("confidence"),
                        "reasons": record.get("reasons", []),
                    },
                )
        except httpx.HTTPError as exc:  # a broken webhook never stops a job
            log.warning("webhook %s failed: %s", url, exc)

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
            note = f"job {job.id}: {job.request}"
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
                code, output = run_command(run.command, run.cwd, timeout)
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
        run = TestRun(
            project_id=job.project_id or "",
            job_id=job.id,
            source=TestRunSource.GATE,
            command=f"{profile.build_cmd} && {profile.test_cmd}",
            cwd=require_worktree(job),
            status=TestRunStatus.PASSED if gate.ok else TestRunStatus.FAILED,
            finished_at=utcnow(),
            exit_code=0 if gate.ok else 1,
            note=f"build gate, phase {job.data.phase_index + 1}",
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
                    job = self._fail(
                        job,
                        f"{before.value} crashed: {type(exc).__name__}: {exc}",
                        detail=traceback.format_exc(),
                    )
                    return self._jira_reconcile(job)
                if job.state is before:  # a handler must always move the job
                    raise RuntimeError(f"handler for {before.value} did not change job {job.id}")
                job = self._jira_reconcile(job)
                if job.state in APPROVAL_STATES:
                    job = self._supervise(job)  # may approve, in which case the loop goes on
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

    def job_result(self, job_id: str) -> JobResult:
        """What the development produced: its branch, the commits and files on it, and
        how to get them. Reads git, so it stays true even after a restart; when the
        worktree is gone the branch in the checkout is read instead."""
        job = self.store.get(job_id)
        project = self._project_of(job)
        checkout = project.repo_path if project and project.repo_path else job.repo_path
        base_branch = self.github_settings().base_branch
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
        return g.run(worktree, "diff", "--no-color", base, "HEAD").stdout or "(no changes)"

    def _invocation_failed(self, job: Job, result: RoleResult) -> Job:
        assert result.error is not None
        if result.error.kind is InvokeErrorKind.BUDGET:
            return self._fail(job, f"budget exhausted: {result.error.message}")
        if result.error.kind is InvokeErrorKind.LOOP:
            return self._ask_human(job, f"loop detected: {result.error.message}")
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
        """
        pending = job.pending_messages
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
        result = self._call_with_retries(role, run, job, profile.roles[role].retries, **kw)
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

    def _call_with_retries(
        self, role: RoleName, run: Callable[..., RoleResult], job: Job, retries: int, **kw: Any
    ) -> RoleResult:
        """Run the role; on a retryable provider error wait (doubling) and try again up to
        the role's ``retries``. Every failed attempt is recorded in the history. A
        truncated answer is retried once with the role told to return a smaller part."""
        attempt = 0
        truncations = 0
        provider: ModelProvider = self.provider
        while True:
            attempt += 1
            result = run(job, provider=provider, timeout_s=self.timeout_s, **kw)
            result.attempts = attempt
            provider = self.provider
            if (
                result.error is not None
                and result.error.kind is InvokeErrorKind.MALFORMED_OUTPUT
                and attempt <= retries
            ):
                # the next attempt carries the validation error, not a blind repeat
                provider = _Corrected(self.provider, result.error.message)
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
                return result
            if attempt > retries:
                return result
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

    def _account(self, job: Job, role: RoleName, result: RoleResult) -> None:
        """Count the call against the job's budget and keep the per-call log."""
        usage = result.usage
        tokens = ((usage.input_tokens or 0) + (usage.output_tokens or 0)) if usage else 0
        job.data.invocations += result.attempts
        job.data.tokens_used += tokens
        job.data.invocation_log.append(
            {
                "role": role.value,
                "model": result.model,  # what answered: the assignment, not the profile
                "state": job.state.value,
                "phase": job.data.phase_index + 1 if job.state is JobState.DEVELOPING else None,
                "attempts": result.attempts,
                "prompt_chars": result.prompt_chars,
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "ok": result.ok,
                "error": result.error.kind.value if result.error else None,
                "at": utcnow().isoformat(),
            }
        )
        self.store.save(job)

    @staticmethod
    def _profile(job: Job) -> Profile:
        if job.profile is None:
            raise RuntimeError(f"job {job.id} has no approved profile")
        return job.profile

    def _run_gate(self, job: Job) -> GateResult:
        kwargs = {} if self.gate_timeout_s is None else {"timeout_s": self.gate_timeout_s}
        with self._checkout_locks[str(require_worktree(job))]:
            gate = build_gate(self._profile(job), require_worktree(job), **kwargs)
        if job.project_id is not None:
            self.record_gate_run(job, gate)
        return gate

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
        result = self._invoke(RoleName.PO, po.run, job, profile=seed)
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
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_BACKLOG_APPROVAL,
            note=(
                f"po: backlog ready — {len(breakdown.epics)} epics, "
                f"{stories} stories, {len(tasks)} tasks"
            ),
            detail=json.dumps({"summary": result.output.summary, **job.data.backlog}, indent=2),
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
        result = self._invoke(RoleName.ARCHITECT, architect.run, job, seed=seed)
        if not result.ok:
            return self._invocation_failed(job, result)
        assert isinstance(result.output, ArchitectResult)
        breakdown = Breakdown.model_validate(job.data.backlog)
        mapping = architect.phase_task_map(result.output.phases, [t.id for t in breakdown.tasks()])
        if isinstance(mapping, str):
            return self._fail(job, f"architect: plan does not match the backlog: {mapping}")
        for task in breakdown.tasks():
            task.phase = mapping[task.id]
        job.profile = architect.accepted_profile(result.output, seed)
        job.data.plan = {
            "summary": result.output.summary,
            "decisions": result.output.decisions,
            "phases": [p.model_dump(mode="json") for p in result.output.phases],
            "breakdown": breakdown.model_dump(mode="json"),
        }
        job.data.phase_index = 0
        job.data.build_attempts = 0
        job.data.last_build_output = None
        self.store.save(job)
        return self.orchestrator.transition(
            job,
            JobState.AWAITING_ARCHITECTURE_APPROVAL,
            note=(
                f"architect: plan ready — {len(result.output.phases)} phases, "
                f"{len(result.output.decisions)} decisions"
            ),
            detail=json.dumps(
                {"profile": job.profile.model_dump(mode="json"), **job.data.plan}, indent=2
            ),
        )

    def _develop(self, job: Job) -> Job:
        profile = self._profile(job)
        phases = self._phases(job)
        index = job.data.phase_index
        if index >= len(phases):
            return self._fail(job, f"no plan phase {index + 1} to develop")
        role = specialist_for(phases[index].get("domain"))
        worktree = require_worktree(job)
        if job.data.build_attempts == 0 and job.data.review_rounds == 0:
            job.data.phase_base_commit = g.head_commit(worktree)  # the review diffs from here
            self.store.save(job)
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
        for part in range(1, self.max_phase_parts + 1):
            result = self._invoke(
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
                touched = apply_changes(job, profile, role, result.output.changes)
            except PermissionError as exc:
                return self._fail(
                    job,
                    f"{exc}; grant it under Agents → {role.value} → Setup and retry",
                )
            touched_all.extend(t for t in touched if t not in touched_all)
            summaries.append(result.output.summary)
            if result.output.phase_complete or part == self.max_phase_parts:
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
        g.stage_all(worktree)
        diff = g.staged_diff(worktree)
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
        gate = self._run_gate(job)
        if gate.ok:
            job.data.build_attempts = 0
            job.data.last_build_output = None
            if job.data.rerun_only:
                # a hand-run of the tests on work that is already committed: report and stop
                job.data.rerun_only = False
                self.store.save(job)
                return self.orchestrator.transition(
                    job, JobState.DONE, note="tests re-run by hand: passed", detail=gate.tail
                )
            worktree = require_worktree(job)
            g.stage_all(worktree)
            goal = phases[index].get("goal", "") if index < len(phases) else ""
            g.commit(worktree, f"slipwright: phase {index + 1}: {goal}")
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

        job.data.build_attempts += 1
        job.data.last_build_output = gate.tail
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
        choice, reason = self._failed_gate_choice(job, index, gate.tail)
        if choice == "replan":
            job.data.feedback = (
                f"phase {index + 1} failed the build gate {job.data.build_attempts} time(s); "
                f"the supervisor asked for a re-plan: {reason}\n\n{gate.tail[-2000:]}"
            )
            job.data.phase_index = 0
            job.data.build_attempts = 0
            self.store.save(job)
            return self.orchestrator.transition(
                job,
                JobState.ARCHITECTURE,
                note=f"{note}; supervisor: re-plan ({reason})",
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

    def _failed_gate_choice(self, job: Job, index: int, output: str) -> tuple[str, str]:
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
                    "output": output[-4000:],
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
        return g.run(worktree, "diff", "--no-color", base, "HEAD").stdout or "(no changes)"

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
            host = self._host_of(job)
            try:
                host.push(worktree, job.branch)
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
            apply_changes(job, profile, fixer, fix.output.changes)
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
