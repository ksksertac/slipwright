import { useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { describeError, type ActivityItem, type Job } from "../api/client";
import {
  useActivity,
  useBoard,
  useProgress,
  useProject,
  useProjectJobs,
  useStartJob,
  useTransition,
} from "../api/hooks";
import { Detail } from "../components/Detail";
import { GateActions } from "../components/GateActions";
import { JiraLink } from "../components/JiraLink";
import {
  Empty,
  ErrorBox,
  Loading,
  ProgressBar,
  StateBadge,
  StatusBadge,
  StatusDot,
  formatTime,
  timeAgo,
} from "../components/ui";
import { TestsTab } from "./TestsTab";

const TABS = ["overview", "board", "developments", "tests", "activity"] as const;
type Tab = (typeof TABS)[number];

export function ProjectPage() {
  const { projectId = "", tab = "overview" } = useParams();
  const project = useProject(projectId);
  const current: Tab = (TABS as readonly string[]).includes(tab) ? (tab as Tab) : "overview";

  if (project.isLoading) return <Loading />;
  if (project.error) return <ErrorBox error={project.error} />;
  if (!project.data) return null;
  const p = project.data;

  return (
    <div>
      <p className="muted small">
        <Link to="/projects">Projects</Link> / {p.name}
      </p>
      <div className="row spread">
        <div>
          <h1 style={{ marginBottom: 2 }}>
            {p.name} {p.jira_project_key && <JiraLink issueKey={p.jira_project_key} />}
          </h1>
          <div className="muted small mono">
            {p.github_repo ?? p.clone_url ?? ""} {p.repo_path ? `· ${p.repo_path}` : ""}
          </div>
          {p.description && <p style={{ marginTop: 8 }}>{p.description}</p>}
        </div>
        <Link className="btn primary" to={`/projects/${p.id}/developments`}>
          New development
        </Link>
      </div>

      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink key={t} to={`/projects/${p.id}/${t}`} className={t === current ? "active" : ""}>
            {t[0]!.toUpperCase() + t.slice(1)}
          </NavLink>
        ))}
      </nav>

      {current === "overview" && <OverviewTab projectId={p.id} />}
      {current === "board" && <BoardTab projectId={p.id} />}
      {current === "developments" && <DevelopmentsTab projectId={p.id} />}
      {current === "tests" && <TestsTab projectId={p.id} />}
      {current === "activity" && <ActivityTab projectId={p.id} />}
    </div>
  );
}

// -- overview ------------------------------------------------------------------------------

function OverviewTab({ projectId }: { projectId: string }) {
  const progress = useProgress(projectId);
  const jobs = useProjectJobs(projectId);
  if (progress.isLoading || jobs.isLoading) return <Loading />;
  if (progress.error) return <ErrorBox error={progress.error} />;
  const p = progress.data;
  if (!p || !jobs.data) return null;
  const byId = new Map(jobs.data.map((j) => [j.id, j]));
  const waiting = p.jobs.filter((j) => j.pending_approval);
  const running = p.jobs.filter(
    (j) => !j.pending_approval && j.state !== "done" && j.state !== "failed",
  );

  return (
    <div className="stack">
      <div className="card">
        <h3>Progress</h3>
        <ProgressBar done={p.tasks_done} total={p.tasks_total} />
        <div className="muted small" style={{ marginTop: 6 }}>
          {p.jobs_running} running · {p.pending_approvals} waiting for approval · {p.jobs_done} done
          · {p.jobs_failed} failed · last activity {timeAgo(p.last_activity)}
        </div>
      </div>

      <div className="card">
        <h3>Pending approvals</h3>
        {waiting.length === 0 && <div className="muted">Nothing waits for you.</div>}
        {waiting.map((row) => {
          const job = byId.get(row.job_id);
          return (
            <div key={row.job_id} className="gate">
              <div className="row spread">
                <div>
                  <Link to={`/projects/${projectId}/jobs/${row.job_id}`}>
                    <strong>{row.request}</strong>
                  </Link>{" "}
                  <span className="muted small">· {row.pending_approval}</span>
                </div>
                {job && <GateActions job={job} compact />}
              </div>
            </div>
          );
        })}
      </div>

      <div className="card">
        <h3>Running</h3>
        {running.length === 0 && <div className="muted">No development is running.</div>}
        {running.length > 0 && (
          <table>
            <tbody>
              {running.map((row) => (
                <tr key={row.job_id}>
                  <td>
                    <Link to={`/projects/${projectId}/jobs/${row.job_id}`}>{row.request}</Link>
                  </td>
                  <td>
                    <StateBadge state={row.state} />
                  </td>
                  <td className="muted small">{row.current_phase}</td>
                  <td style={{ width: 160 }}>
                    <ProgressBar done={row.tasks_done} total={row.tasks_total} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// -- board ---------------------------------------------------------------------------------

function BoardTab({ projectId }: { projectId: string }) {
  const board = useBoard(projectId);
  if (board.isLoading) return <Loading />;
  if (board.error) return <ErrorBox error={board.error} />;
  if (!board.data) return null;
  if (board.data.epics.length === 0) {
    return (
      <Empty>
        The board fills in once a development's plan is approved: each epic, story and task appears
        here and moves as the work is done.
      </Empty>
    );
  }
  return (
    <div className="card" style={{ padding: 0 }}>
      <div className="row spread" style={{ padding: "10px 14px" }}>
        <strong>Epics → stories → tasks</strong>
        <ProgressBar done={board.data.tasks_done} total={board.data.tasks_total} />
      </div>
      <ul className="tree">
        {board.data.epics.map((epic) => (
          <li key={`${epic.job_id}:${epic.id}`}>
            <div className="node">
              <StatusDot status={epic.status} />
              <span className="kind">epic</span>
              <span className="title">
                {epic.title}{" "}
                <Link className="muted small" to={`/projects/${projectId}/jobs/${epic.job_id}`}>
                  · {epic.job_request}
                </Link>
              </span>
              <JiraLink issueKey={epic.jira_key} />
              <StatusBadge status={epic.status} />
            </div>
            <ul className="tree">
              {epic.stories.map((story) => (
                <li key={story.id} className="depth-1">
                  <div className="node">
                    <StatusDot status={story.status} />
                    <span className="kind">story</span>
                    <span className="title">{story.title}</span>
                    <JiraLink issueKey={story.jira_key} />
                    <StatusBadge status={story.status} />
                  </div>
                  <ul className="tree">
                    {story.tasks.map((task) => (
                      <li key={task.id} className="depth-2">
                        <div className="node">
                          <StatusDot status={task.status} />
                          <span className="kind">task</span>
                          <span className="title">
                            <Link
                              to={`/projects/${projectId}/jobs/${task.job_id}#phase-${task.phase}`}
                            >
                              {task.title}
                            </Link>
                            {task.files.length > 0 && (
                              <span className="muted small mono"> · {task.files.join(", ")}</span>
                            )}
                          </span>
                          <JiraLink issueKey={task.jira_key} />
                          <StatusBadge status={task.status} />
                        </div>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

// -- developments --------------------------------------------------------------------------

function DevelopmentsTab({ projectId }: { projectId: string }) {
  const jobs = useProjectJobs(projectId);
  const start = useStartJob(projectId);
  const navigate = useNavigate();
  const [request, setRequest] = useState("");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    start.mutate(request.trim(), {
      onSuccess: (job) => {
        setRequest("");
        navigate(`/projects/${projectId}/jobs/${job.id}`);
      },
    });
  };

  return (
    <div className="stack">
      <form className="card" onSubmit={submit}>
        <h3>New development</h3>
        <p className="muted small">
          Describe what you want. The Analyst proposes how to build and test the project, the
          Planner breaks the work into epics, stories and tasks, and you approve each step.
        </p>
        <textarea
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          placeholder="e.g. Add a /health endpoint that reports the database status"
        />
        {start.error && <div className="error">{describeError(start.error)}</div>}
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn primary" disabled={!request.trim() || start.isPending}>
            {start.isPending ? "Starting…" : "Start development"}
          </button>
        </div>
      </form>

      <div className="card" style={{ padding: 0 }}>
        {jobs.isLoading && <Loading />}
        {jobs.data && jobs.data.length === 0 && (
          <div className="muted" style={{ padding: 14 }}>
            No developments yet.
          </div>
        )}
        {jobs.data && jobs.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Request</th>
                <th>State</th>
                <th>Started</th>
                <th>Last activity</th>
                <th>PR</th>
              </tr>
            </thead>
            <tbody>
              {[...jobs.data].reverse().map((job: Job) => (
                <tr key={job.id}>
                  <td>
                    <Link to={`/projects/${projectId}/jobs/${job.id}`}>{job.request}</Link>
                    <div className="muted small mono">{job.id}</div>
                  </td>
                  <td>
                    <StateBadge state={job.state} />
                  </td>
                  <td className="muted small">{formatTime(job.created_at)}</td>
                  <td className="muted small">
                    {job.history.length > 0
                      ? timeAgo(job.history[job.history.length - 1]!.at)
                      : "—"}
                  </td>
                  <td>
                    {job.data.pr_url ? (
                      <a href={job.data.pr_url} target="_blank" rel="noreferrer">
                        open
                      </a>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// -- activity ------------------------------------------------------------------------------

function ActivityTab({ projectId }: { projectId: string }) {
  const activity = useActivity(projectId);
  if (activity.isLoading) return <Loading />;
  if (activity.error) return <ErrorBox error={activity.error} />;
  if (!activity.data || activity.data.length === 0) {
    return <Empty>Nothing has happened yet.</Empty>;
  }
  return (
    <div className="card" style={{ padding: "4px 14px" }}>
      <ul className="feed">
        {activity.data.map((item) => (
          <ActivityRow key={`${item.job_id}:${item.index}`} item={item} projectId={projectId} />
        ))}
      </ul>
    </div>
  );
}

const KIND_LABEL: Record<ActivityItem["kind"], string> = {
  started: "started",
  role: "agent",
  gate: "build gate",
  approval: "you",
  inbox: "steering",
  jira: "jira",
  crash: "crash",
  failed: "failed",
  done: "done",
  other: "",
};

export function ActivityRow({ item, projectId }: { item: ActivityItem; projectId: string }) {
  const [open, setOpen] = useState(false);
  const detail = useTransition(item.job_id, open ? item.index : null);
  const who = item.role ?? KIND_LABEL[item.kind];
  const cls =
    item.kind === "failed" || item.kind === "crash"
      ? "bad"
      : item.kind === "done"
        ? "ok"
        : item.kind === "approval"
          ? "wait"
          : item.kind === "gate"
            ? "work"
            : "idle";
  return (
    <li>
      <span className="when" title={item.at}>
        {formatTime(item.at)}
      </span>
      <span className="who">
        <span className={`badge ${cls}`}>{who}</span>
      </span>
      <span>
        {item.title}{" "}
        <Link className="muted small" to={`/projects/${projectId}/jobs/${item.job_id}`}>
          · {item.job_request}
        </Link>
        {item.has_detail && (
          <details onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
            <summary>detail</summary>
            {detail.isLoading && <Loading />}
            {detail.data && <Detail text={detail.data.detail} />}
          </details>
        )}
      </span>
    </li>
  );
}
