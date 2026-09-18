"""Engine-driven Jira mirror of a job's breakdown (T7.4).

``reconcile`` is idempotent: it creates the issues that do not exist yet (keys are kept
on ``job.data.jira_keys``), moves each issue to the status its board item has, and posts
the one-shot comments (PR link on success, build output on failure) it has not posted
before. A Jira failure aborts the pass and is retried on the next transition; it never
touches the job's own state. Agents writing to Jira themselves is T7.5, not this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from slipwright.board import EpicView, StoryView, TaskStatus, TaskView, job_epics
from slipwright.jira import JiraClient, JiraError
from slipwright.schemas.job import Job, JobState
from slipwright.schemas.project import Project

DEFAULT_TRANSITIONS: dict[str, str | None] = {
    TaskStatus.TODO.value: "To Do",
    TaskStatus.IN_PROGRESS.value: "In Progress",
    TaskStatus.DONE.value: "Done",
    TaskStatus.FAILED.value: None,  # comment only, unless the project maps it
}
MAX_COMMENT_CHARS = 4000


@dataclass
class SyncReport:
    notes: list[str] = field(default_factory=list)
    changed: bool = False
    error: str | None = None

    def note(self, text: str) -> None:
        self.notes.append(text)
        self.changed = True


class JiraSync:
    def __init__(self, client: JiraClient, project: Project, issue_types: dict[str, str]) -> None:
        self.client = client
        self.project = project
        self.types = dict(issue_types)
        self._resolved = False

    @property
    def key(self) -> str:
        assert self.project.jira_project_key is not None
        return self.project.jira_project_key

    def reconcile(self, job: Job) -> SyncReport:
        """Bring Jira up to date with ``job``; mutates ``job.data`` (caller persists)."""
        report = SyncReport()
        epics = job_epics(job)
        if not epics:
            return report
        try:
            self._ensure_issues(job, epics, report)
            self._ensure_sprint(job, epics, report)
            self._sync_statuses(job, epics, report)
            self._one_shot_comments(job, epics, report)
        except JiraError as exc:
            report.error = str(exc)
            job.data.jira_last_error = report.error
            return report
        if job.data.jira_last_error is not None:
            job.data.jira_last_error = None
            report.changed = True
        return report

    # -- issues ------------------------------------------------------------------------------

    def _resolve_types(self, report: SyncReport) -> None:
        """Check the configured names against the project's real issue types once per
        sync: a task must be a sub-task type to nest under a story (Jira calls it
        ``Subtask`` or ``Sub-task`` depending on the site); a wrong name in the settings
        is corrected here rather than failing every create."""
        if self._resolved:
            return
        self._resolved = True
        try:
            available = self.client.issue_types(self.key)
        except JiraError:
            return  # the create call will report the real problem
        by_name = {t["name"].lower(): t for t in available}
        subtasks = [t["name"] for t in available if t["subtask"]]
        for kind, wanted_level in (("epic", 1), ("story", 0), ("task", -1)):
            name = self.types.get(kind, "")
            current = by_name.get(name.lower())
            if current is not None and current["level"] == wanted_level:
                continue
            candidates = [t["name"] for t in available if t["level"] == wanted_level]
            if kind == "task":
                candidates = subtasks or candidates
            if not candidates:
                continue
            replacement = candidates[0]
            if name.lower() != replacement.lower():
                report.note(
                    f"issue type for {kind}: {name!r} cannot be used at that level in "
                    f"{self.key}; using {replacement!r}"
                )
            self.types[kind] = replacement

    def _ensure_issues(self, job: Job, epics: list[EpicView], report: SyncReport) -> None:
        keys = job.data.jira_keys
        if any(item.id not in keys for item in _flatten(epics)):
            self._resolve_types(report)
        for epic in epics:
            if epic.id not in keys:
                keys[epic.id] = self.client.create_issue(
                    self.key,
                    self.types.get("epic", "Epic"),
                    epic.title,
                    _describe(epic.description, job),
                )
                report.note(f"created {keys[epic.id]} (epic) {epic.title}")
            for story in epic.stories:
                if story.id not in keys:
                    keys[story.id] = self.client.create_issue(
                        self.key,
                        self.types.get("story", "Story"),
                        story.title,
                        _describe(story.description, job),
                        parent_key=keys[epic.id],
                    )
                    report.note(f"created {keys[story.id]} (story) {story.title}")
                for task in story.tasks:
                    if task.id not in keys:
                        files = ", ".join(task.files)
                        description = task.description or ""
                        if files:
                            description += f"\nFiles: {files}"
                        keys[task.id] = self.client.create_issue(
                            self.key,
                            self.types.get("task", "Subtask"),
                            task.title,
                            _describe(description, job, phase=task.phase),
                            parent_key=keys[story.id],
                        )
                        report.note(f"created {keys[task.id]} (task) {task.title}")

    # -- sprint ------------------------------------------------------------------------------

    def _ensure_sprint(self, job: Job, epics: list[EpicView], report: SyncReport) -> None:
        """Put the development's stories into a sprint (sub-tasks follow their parents):
        the active one when there is one, else a new one named after the request when
        the project allows it. Done once per job; a project without a scrum board is
        left alone."""
        mode = self.project.jira_sprint
        if mode == "off" or job.data.jira_sprint_id is not None:
            return
        keys = job.data.jira_keys
        stories = [keys[s.id] for e in epics for s in e.stories if s.id in keys]
        if not stories:
            return
        board = self.client.board_id(self.key)
        if board is None:
            job.data.jira_sprint_id = 0  # remember: nothing to do for this project
            report.note("no scrum board: stories stay in the backlog")
            return
        sprint = self.client.active_sprint(board)
        if sprint is None and mode == "create":
            sprint = self.client.create_sprint(board, f"Slipwright: {job.request[:60]}")
            report.note(f"started sprint {sprint.get('name')} (#{sprint['id']})")
        if sprint is None:
            job.data.jira_sprint_id = 0
            report.note("no active sprint: stories stay in the backlog")
            return
        self.client.add_to_sprint(int(sprint["id"]), stories)
        job.data.jira_sprint_id = int(sprint["id"])
        report.note(f"{len(stories)} story(ies) added to sprint {sprint.get('name')}")

    # -- statuses ----------------------------------------------------------------------------

    def _sync_statuses(self, job: Job, epics: list[EpicView], report: SyncReport) -> None:
        for item in _flatten(epics):
            self._move(job, item.id, item.status, report)

    def _move(self, job: Job, item_id: str, status: TaskStatus, report: SyncReport) -> None:
        key = job.data.jira_keys.get(item_id)
        if key is None or job.data.jira_status.get(item_id) == status.value:
            return
        name = self.project.jira_transitions.get(status.value, DEFAULT_TRANSITIONS[status.value])
        job.data.jira_status[item_id] = status.value  # never retried: logged instead
        if not name:
            return
        if self.client.transition(key, name):
            report.note(f"{key} -> {name}")
        else:
            report.note(f"{key}: no transition named {name!r}; left as is")

    # -- comments ----------------------------------------------------------------------------

    def _one_shot_comments(self, job: Job, epics: list[EpicView], report: SyncReport) -> None:
        marks = job.data.jira_marks
        if job.state is JobState.DONE and job.data.pr_url and "pr" not in marks:
            text = f"Pull request opened by Slipwright job {job.id}: {job.data.pr_url}"
            for key in sorted(set(job.data.jira_keys.values())):
                self.client.comment(key, text)
            marks.append("pr")
            report.note(f"commented PR link on {len(set(job.data.jira_keys.values()))} issue(s)")
        for record in job.data.reviews:
            if not record.get("blocking"):
                continue
            mark = f"review:{record.get('phase')}:{record.get('round')}"
            if mark in marks:
                continue
            task = next(
                (
                    t
                    for t in _flatten(epics)
                    if isinstance(t, TaskView) and t.phase == record.get("phase")
                ),
                None,
            )
            issue = job.data.jira_keys.get(task.id) if task is not None else None
            if issue is None:
                continue
            lines = [
                f"Slipwright standards review of phase {record.get('phase')} found "
                f"{record.get('blocking')} blocking violation(s) ({record.get('verdict', '')}):"
            ]
            for v in record.get("violations", []):
                if v.get("severity") == "blocking":
                    where = f"{v.get('file')}:{v.get('line')}" if v.get("line") else v.get("file")
                    lines.append(f"- [{v.get('section')}] {where}: {v.get('message')}")
            self.client.comment(issue, "\n".join(lines)[:MAX_COMMENT_CHARS])
            marks.append(mark)
            report.note(f"commented review findings on {issue}")
        if job.state is JobState.FAILED:
            reason = next(
                (t.note for t in reversed(job.history) if t.to_state is JobState.FAILED), None
            )
            output = job.data.last_build_output or ""
            for item in _flatten(epics):
                mark = f"fail:{item.id}"
                if item.status is TaskStatus.FAILED and mark not in marks:
                    issue = job.data.jira_keys.get(item.id)
                    if issue is None:
                        continue
                    text = f"Slipwright job {job.id} failed here: {reason or 'unknown reason'}"
                    if output and isinstance(item, TaskView):
                        text += "\n\nLast build output:\n" + output[-MAX_COMMENT_CHARS:]
                    self.client.comment(issue, text)
                    marks.append(mark)
                    report.note(f"commented failure on {issue}")


def _flatten(epics: list[EpicView]) -> list[EpicView | StoryView | TaskView]:
    out: list[EpicView | StoryView | TaskView] = []
    for epic in epics:
        out.append(epic)
        for story in epic.stories:
            out.append(story)
            out.extend(story.tasks)
    return out


def _describe(text: str, job: Job, *, phase: int | None = None) -> str:
    lines = [text.strip()] if text.strip() else []
    if phase is not None:
        lines.append(f"Plan phase {phase} of Slipwright job {job.id}.")
    else:
        lines.append(f"Created by Slipwright job {job.id}: {job.request}")
    return "\n".join(lines)


__all__ = ["DEFAULT_TRANSITIONS", "JiraSync", "SyncReport"]
