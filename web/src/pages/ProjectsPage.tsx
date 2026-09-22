import { useState } from "react";
import { Link } from "react-router-dom";
import type { Project } from "../api/client";
import { useProgress, useProjects } from "../api/hooks";
import { Crumbs } from "../components/Crumbs";
import {
  IconEdit,
  IconGit,
  IconPlus,
  IconSearch,
  IconTicket,
  IconTrash,
} from "../components/icons";
import { Menu } from "../components/Menu";
import { DeleteProjectModal, EditProjectModal } from "../components/ProjectDialogs";
import { Empty, ErrorBox, Loading, PageHead, ProgressBar, timeAgo } from "../components/ui";
import { useT } from "../i18n";

export function ProjectsPage() {
  const tx = useT();
  const projects = useProjects();
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Project | null>(null);
  const [deleting, setDeleting] = useState<Project | null>(null);
  const visible = (projects.data ?? []).filter((p) =>
    `${p.name} ${p.description} ${p.github_repo ?? ""}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div>
      <Crumbs items={[{ label: "Projects" }]} />
      <PageHead
        title={tx("Projects")}
        subtitle={tx("Repositories the agents work on.")}
        actions={
          <>
            <div style={{ position: "relative" }}>
              <IconSearch
                style={{
                  position: "absolute",
                  left: 9,
                  top: 9,
                  width: 15,
                  height: 15,
                  color: "var(--text-3)",
                }}
              />
              <input
                type="text"
                placeholder={tx("Search…")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{ paddingLeft: 30, width: 220 }}
              />
            </div>
            <Link className="btn primary" to="/projects/new">
              <IconPlus /> {tx("New project")}
            </Link>
          </>
        }
      />
      <ErrorBox error={projects.error} />
      {projects.isLoading && <Loading />}
      {projects.data && projects.data.length === 0 && (
        <Empty
          title={tx("No projects yet")}
          action={
            <Link className="btn primary" to="/projects/new">
              <IconPlus /> {tx("Add the first project")}
            </Link>
          }
        >
          {tx(
            "A project is a repository Slipwright works on: add one from a local checkout or a GitHub repository, then start a development by describing what you want.",
          )}
        </Empty>
      )}
      {visible.length > 0 && (
        <div className="grid-3">
          {visible.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              onEdit={() => setEditing(p)}
              onDelete={() => setDeleting(p)}
            />
          ))}
        </div>
      )}
      {projects.data && projects.data.length > 0 && visible.length === 0 && (
        <Empty>{tx("No project matches “{query}”.", { query })}</Empty>
      )}
      {editing && <EditProjectModal project={editing} onClose={() => setEditing(null)} />}
      {deleting && <DeleteProjectModal project={deleting} onClose={() => setDeleting(null)} />}
    </div>
  );
}

function ProjectCard({
  project,
  onEdit,
  onDelete,
}: {
  project: Project;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const tx = useT();
  const progress = useProgress(project.id);
  const p = progress.data;
  return (
    <div className="card pcard">
      <div className="row spread" style={{ flexWrap: "nowrap" }}>
        <div className="title truncate">
          <Link to={`/projects/${project.id}`}>{project.name}</Link>
        </div>
        <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
          {p && p.pending_approvals > 0 && (
            <span className="badge wait">{tx("{n} waiting", { n: p.pending_approvals })}</span>
          )}
          {p && p.jobs_running > 0 && (
            <span className="badge work">{tx("{n} running", { n: p.jobs_running })}</span>
          )}
          <Menu>
            <button onClick={onEdit}>
              <IconEdit /> {tx("Edit")}
            </button>
            <button className="danger" onClick={onDelete}>
              <IconTrash /> {tx("Delete")}
            </button>
          </Menu>
        </div>
      </div>
      {project.description ? (
        <div className="muted small" style={{ minHeight: 20 }}>
          {project.description}
        </div>
      ) : (
        <div className="faint small" style={{ minHeight: 20 }}>
          {tx("No description")}
        </div>
      )}
      <div className="meta">
        <span title={project.repo_path ?? ""}>
          <IconGit /> {project.github_repo ?? project.clone_url ?? tx("local checkout")}
        </span>
        {project.jira_project_key && (
          <span>
            <IconTicket /> {project.jira_project_key}
          </span>
        )}
      </div>
      <div>
        {p ? (
          <ProgressBar done={p.tasks_done} total={p.tasks_total} />
        ) : (
          <div className="skeleton" style={{ height: 8 }} />
        )}
      </div>
      <div className="row spread faint tiny">
        <span>
          {p ? tx("{n} development(s)", { n: p.jobs.length }) : "…"}
          {p && p.jobs_failed > 0 ? ` · ${tx("{n} failed", { n: p.jobs_failed })}` : ""}
        </span>
        <span>{p ? tx("active {when}", { when: timeAgo(p.last_activity) }) : ""}</span>
      </div>
    </div>
  );
}
