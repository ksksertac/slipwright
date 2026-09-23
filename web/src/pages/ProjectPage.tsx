import { useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { describeError, type Job, type Project } from "../api/client";
import {
  useActivity,
  useBoard,
  useDeleteJob,
  useProgress,
  useProject,
  useProjectJobs,
  useStartJob,
} from "../api/hooks";
import { ActivityRow } from "../components/ActivityRow";
import { Crumbs } from "../components/Crumbs";
import { GateActions } from "../components/GateActions";
import { IconEdit, IconExternal, IconPlus, IconTrash } from "../components/icons";
import { JiraLink } from "../components/JiraLink";
import { Menu } from "../components/Menu";
import { ConfirmModal } from "../components/Modal";
import { DeleteProjectModal, EditProjectModal } from "../components/ProjectDialogs";
import { useToast } from "../components/Toast";
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
import { PipelineTab } from "./PipelineTab";
import { TestsTab } from "./TestsTab";
import { useT } from "../i18n";
import { ResultCard } from "../components/ResultCard";
import { WorkListPanel } from "../components/WorkList";

const TABS = ["pipeline", "overview", "board", "developments", "tests", "activity"] as const;
type Tab = (typeof TABS)[number];

export function ProjectPage() {
  const tx = useT();
  const { projectId = "", tab = "pipeline" } = useParams();
  const project = useProject(projectId);
  const current: Tab = (TABS as readonly string[]).includes(tab) ? (tab as Tab) : "pipeline";

  if (project.isLoading) return <Loading />;
  if (project.error) return <ErrorBox error={project.error} />;
  if (!project.data) return null;
  const p = project.data;

  return (
    <div>
      <Crumbs items={[{ label: "Projects", to: "/projects" }, { label: p.name }]} />
      <ProjectHeader project={p} />

      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink key={t} to={`/projects/${p.id}/${t}`} className={t === current ? "active" : ""}>
            {tx(t[0]!.toUpperCase() + t.slice(1))}
          </NavLink>
        ))}
      </nav>

      {current === "pipeline" && <PipelineTab projectId={p.id} />}
      {current === "overview" && <OverviewTab projectId={p.id} />}
      {current === "board" && <BoardTab projectId={p.id} />}
      {current === "developments" && <DevelopmentsTab projectId={p.id} />}
      {current === "tests" && <TestsTab projectId={p.id} />}
      {current === "activity" && <ActivityTab projectId={p.id} />}
    </div>
  );
}

function ProjectHeader({ project: p }: { project: Project }) {
  const tx = useT();
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  return (
    <div className="page-head">
      <div style={{ minWidth: 0 }}>
        <h1>
          {p.name} {p.jira_project_key && <JiraLink issueKey={p.jira_project_key} />}
        </h1>
        <div className="faint small mono truncate">
          {p.github_repo ?? p.clone_url ?? ""} {p.repo_path ? `· ${p.repo_path}` : ""}
        </div>
        {p.description && <p>{p.description}</p>}
      </div>
      <div className="row" style={{ flexWrap: "nowrap" }}>
        <Link className="btn primary" to={`/projects/${p.id}/developments`}>
          <IconPlus /> {tx("New development")}
        </Link>
        <Menu>
          <button onClick={() => setEditing(true)}>
            <IconEdit /> {tx("Edit project")}
          </button>
          <button className="danger" onClick={() => setDeleting(true)}>
            <IconTrash /> {tx("Delete project")}
          </button>
        </Menu>
      </div>
      {editing && <EditProjectModal project={p} onClose={() => setEditing(false)} />}
      {deleting && (
        <DeleteProjectModal project={p} onClose={() => setDeleting(false)} redirectTo="/projects" />
      )}
    </div>
  );
}

// -- overview ------------------------------------------------------------------------------

function OverviewTab({ projectId }: { projectId: string }) {
  const tx = useT();
  const progress = useProgress(projectId);
  const jobs = useProjectJobs(projectId);
  if (progress.isLoading || jobs.isLoading) return <Loading />;
  if (progress.error) return <ErrorBox error={progress.error} />;
  const p = progress.data;
  if (!p || !jobs.data) return null;
  const byId = new Map(jobs.data.map((j) => [j.id, j]));
  const waiting = p.jobs.filter((j) => j.pending_approval);
  // the newest finished development: what the project has to show for itself
  const lastDone = [...jobs.data].reverse().find((j) => j.state === "done" || j.state === "failed");
  const running = p.jobs.filter(
    (j) => !j.pending_approval && j.state !== "done" && j.state !== "failed",
  );

  return (
    <div className="stack">
      <div className="card">
        <h3 style={{ marginBottom: 10 }}>{tx("Progress")}</h3>
        <ProgressBar done={p.tasks_done} total={p.tasks_total} />
        <div className="muted small" style={{ marginTop: 8 }}>
          {tx(
            "{running} running · {waiting} waiting for approval · {done} done · {failed} failed · last activity {when}",
            {
              running: p.jobs_running,
              waiting: p.pending_approvals,
              done: p.jobs_done,
              failed: p.jobs_failed,
              when: timeAgo(p.last_activity),
            },
          )}
        </div>
        <div className="muted small" style={{ marginTop: 4 }}>
          {tx("Standards review: {n} review(s)", { n: p.reviews })}
          {p.reviews > 0 && (
            <>
              {" "}
              ·{" "}
              <span className={p.review_blocking ? "error" : ""}>
                {tx("{n} blocking", { n: p.review_blocking })}
              </span>{" "}
              · {tx("{n} advisory finding(s)", { n: p.review_advisory })}
            </>
          )}
        </div>
      </div>

      {lastDone && <ResultCard job={lastDone} compact />}

      <div className="card">
        <h3 style={{ marginBottom: 10 }}>{tx("Pending approvals")}</h3>
        {waiting.length === 0 && <div className="muted small">{tx("Nothing waits for you.")}</div>}
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
        <h3 style={{ marginBottom: 10 }}>{tx("Running")}</h3>
        {running.length === 0 && (
          <div className="muted small">{tx("No development is running.")}</div>
        )}
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
  const tx = useT();
  const board = useBoard(projectId);
  if (board.isLoading) return <Loading />;
  if (board.error) return <ErrorBox error={board.error} />;
  if (!board.data) return null;
  if (board.data.epics.length === 0) {
    return (
      <Empty>
        {tx(
          "The board fills in once a development's plan is approved: each epic, story and task appears here and moves as the work is done.",
        )}
      </Empty>
    );
  }
  return (
    <div className="card flush">
      <div className="card-head">
        <h3>{tx("Epics → stories → tasks")}</h3>
        <div style={{ width: 200 }}>
          <ProgressBar done={board.data.tasks_done} total={board.data.tasks_total} />
        </div>
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
                          {task.violations > 0 && (
                            <span
                              className={`badge plain ${task.blocking ? "bad" : "work"}`}
                              title={tx("standards review findings")}
                            >
                              {task.blocking
                                ? `${task.blocking} blocking`
                                : `${task.violations} advisory`}
                            </span>
                          )}
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
  const tx = useT();
  const jobs = useProjectJobs(projectId);
  const start = useStartJob(projectId);
  const navigate = useNavigate();
  const [request, setRequest] = useState("");

  // a development that has not started yet is the list waiting to be read: it is shown
  // here, so closing the tab (or the whole application) loses nothing
  const planning = (jobs.data ?? []).find((j) => j.state === "awaiting_architecture_approval");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    start.mutate(request.trim(), {
      onSuccess: () => {
        setRequest("");
        void jobs.refetch();
      },
    });
  };

  return (
    <div className="stack">
      <form className="card" onSubmit={submit}>
        <h3 style={{ marginBottom: 6 }}>{tx("New development")}</h3>
        <p className="muted small">
          {tx(
            "Describe what you want. The Product Owner turns it into epics, stories and tasks, the Architect designs how to build and test it, and you approve each step.",
          )}
        </p>
        <textarea
          value={request}
          onChange={(e) => setRequest(e.target.value)}
          placeholder={tx("e.g. Add a /health endpoint that reports the database status")}
        />
        {start.error && <div className="error">{describeError(start.error)}</div>}
        <div className="row" style={{ marginTop: 8 }}>
          <button className="btn primary" disabled={!request.trim() || start.isPending}>
            <IconPlus /> {start.isPending ? tx("Working it out…") : tx("Plan it")}
          </button>
          <span className="faint small">
            {tx("The Product Owner and the Architect answer first; nothing is built yet.")}
          </span>
        </div>
      </form>

      {planning && (
        <div className="card">
          <WorkListPanel
            job={planning}
            onStarted={() => navigate(`/projects/${projectId}/jobs/${planning.id}`)}
          />
        </div>
      )}

      <div className="card flush">
        <div className="card-head">
          <h3>{tx("Developments")}</h3>
          <span className="faint small">{jobs.data?.length ?? 0}</span>
        </div>
        {jobs.isLoading && (
          <div className="card-body">
            <Loading />
          </div>
        )}
        {jobs.data && jobs.data.length === 0 && (
          <div className="empty" style={{ padding: 28 }}>
            <div className="small">{tx("No developments yet. Describe one above to start.")}</div>
          </div>
        )}
        {jobs.data && jobs.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>{tx("Request")}</th>
                <th>{tx("State")}</th>
                <th>{tx("Started")}</th>
                <th>{tx("Last activity")}</th>
                <th>PR</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {[...jobs.data].reverse().map((job: Job) => (
                <JobRow key={job.id} job={job} projectId={projectId} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function JobRow({ job, projectId }: { job: Job; projectId: string }) {
  const tx = useT();
  const remove = useDeleteJob();
  const toast = useToast();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState(false);
  const terminal = job.state === "done" || job.state === "failed";
  return (
    <tr>
      <td>
        <Link to={`/projects/${projectId}/jobs/${job.id}`}>{job.request}</Link>
        <div className="faint tiny mono">{job.id}</div>
      </td>
      <td>
        <StateBadge state={job.state} />
      </td>
      <td className="muted small">{formatTime(job.created_at)}</td>
      <td className="muted small">
        {job.history.length > 0 ? timeAgo(job.history[job.history.length - 1]!.at) : "—"}
      </td>
      <td>
        {job.data.pr_url ? (
          <a href={job.data.pr_url} target="_blank" rel="noreferrer">
            {tx("open ↗")}
          </a>
        ) : (
          <span className="faint">—</span>
        )}
      </td>
      <td className="actions">
        <Menu>
          <button onClick={() => navigate(`/projects/${projectId}/jobs/${job.id}`)}>
            <IconExternal /> {tx("Open")}
          </button>
          <button className="danger" disabled={!terminal} onClick={() => setConfirm(true)}>
            <IconTrash /> Delete{terminal ? "" : " (still running)"}
          </button>
        </Menu>
        {confirm && (
          <ConfirmModal
            title={tx("Delete development")}
            body={
              <>
                {tx("Delete")} <strong>{job.request}</strong>
                {tx(
                  "? Its worktree, branch, history and test runs are removed. A pull request already opened stays on GitHub.",
                )}
              </>
            }
            busy={remove.isPending}
            error={remove.error ? describeError(remove.error) : null}
            onClose={() => setConfirm(false)}
            onConfirm={() =>
              remove.mutate(job.id, {
                onSuccess: () => {
                  toast.ok("Development deleted");
                  setConfirm(false);
                },
              })
            }
          />
        )}
      </td>
    </tr>
  );
}

// -- activity ------------------------------------------------------------------------------

function ActivityTab({ projectId }: { projectId: string }) {
  const tx = useT();
  const activity = useActivity(projectId);
  if (activity.isLoading) return <Loading />;
  if (activity.error) return <ErrorBox error={activity.error} />;
  if (!activity.data || activity.data.length === 0) {
    return <Empty>{tx("Nothing has happened yet.")}</Empty>;
  }
  return (
    <div className="card">
      <ul className="feed">
        {activity.data.map((item) => (
          <ActivityRow key={`${item.job_id}:${item.index}`} item={item} projectId={projectId} />
        ))}
      </ul>
    </div>
  );
}
