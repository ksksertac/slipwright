import { Link, useNavigate } from "react-router-dom";
import type { Project } from "../api/client";
import { useProgress, useProjects } from "../api/hooks";
import { Empty, ErrorBox, Loading, ProgressBar, timeAgo } from "../components/ui";

export function ProjectsPage() {
  const projects = useProjects();

  return (
    <div>
      <div className="row spread">
        <h1>Projects</h1>
        <Link className="btn primary" to="/projects/new">
          New project
        </Link>
      </div>
      <ErrorBox error={projects.error} />
      {projects.isLoading && <Loading />}
      {projects.data && projects.data.length === 0 && (
        <Empty>
          No projects yet. A project is a repository Slipwright works on: add one from a local
          checkout or a GitHub repository, then start a development by describing what you want.{" "}
          <Link to="/projects/new">Add the first project</Link>.
        </Empty>
      )}
      {projects.data && projects.data.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Repository</th>
                <th>Running</th>
                <th>Pending approvals</th>
                <th style={{ width: 200 }}>Tasks</th>
                <th>Last activity</th>
              </tr>
            </thead>
            <tbody>
              {projects.data.map((p) => (
                <ProjectRow key={p.id} project={p} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ProjectRow({ project }: { project: Project }) {
  const navigate = useNavigate();
  const progress = useProgress(project.id);
  const p = progress.data;
  const remote = project.github_repo ?? project.clone_url;
  return (
    <tr className="clickable" onClick={() => navigate(`/projects/${project.id}`)}>
      <td>
        <Link to={`/projects/${project.id}`} onClick={(e) => e.stopPropagation()}>
          <strong>{project.name}</strong>
        </Link>
        {project.jira_project_key && <span className="tag">{project.jira_project_key}</span>}
        {project.description && <div className="muted small">{project.description}</div>}
      </td>
      <td className="mono small">
        {remote ? <div>{remote}</div> : null}
        <div className="muted">{project.repo_path ?? "—"}</div>
      </td>
      <td>{p ? p.jobs_running : "…"}</td>
      <td>
        {p && p.pending_approvals > 0 ? (
          <span className="badge wait">{p.pending_approvals} waiting</span>
        ) : (
          <span className="muted">none</span>
        )}
      </td>
      <td>{p ? <ProgressBar done={p.tasks_done} total={p.tasks_total} /> : "…"}</td>
      <td className="muted small">{p ? timeAgo(p.last_activity) : "…"}</td>
    </tr>
  );
}
