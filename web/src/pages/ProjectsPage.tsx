import { type CSSProperties, useState } from "react";
import { Link } from "react-router-dom";
import type { Project } from "../api/client";
import { useProgress, useProjects } from "../api/hooks";
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
import { sentenceCase, useT } from "../i18n";

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

/**
 * A colour per project, so a card is recognisable before its name is read. The hue is
 * hashed from the id — stable across reloads, never random — and picked from a set that
 * stays legible as both a pale tile in light and a deep one in dark. The card hands it to
 * CSS as --proj-h/--proj-s, the way agent roles do.
 */
const HUES: readonly [number, number][] = [
  [212, 68],
  [265, 60],
  [150, 58],
  [28, 78],
  [330, 62],
  [190, 62],
  [96, 50],
  [14, 72],
  [240, 52],
  [45, 72],
];

function tint(id: string): CSSProperties {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const [hue, sat] = HUES[h % HUES.length] ?? [212, 68];
  return { "--proj-h": hue, "--proj-s": sat } as CSSProperties;
}

/** Up to two initials, so "ai test app" reads as AT and "slipwright" as S. */
function initials(name: string): string {
  const words = name
    .trim()
    .split(/[\s._/-]+/)
    .filter(Boolean);
  return words
    .slice(0, 2)
    .map((w) => [...w][0])
    .join("")
    .toUpperCase();
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
  const repo = project.github_repo ?? project.clone_url ?? tx("local checkout");
  return (
    <div className="card pcard proj" style={tint(project.id)}>
      <div className="pcard-head">
        <span className="pmark" aria-hidden>
          {initials(project.name)}
        </span>
        <div style={{ minWidth: 0 }}>
          <div className="title truncate">
            <Link to={`/projects/${project.id}`}>{sentenceCase(project.name)}</Link>
          </div>
          {project.description ? (
            <div className="pcard-desc muted small">{project.description}</div>
          ) : (
            <div className="pcard-desc faint small">{tx("No description")}</div>
          )}
        </div>
        <div className="pcard-tools">
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
      <div className="meta">
        <span title={project.repo_path ?? repo}>
          <IconGit /> {repo}
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
      <div className="pcard-foot faint tiny">
        <span>
          {p ? tx("{n} development(s)", { n: p.jobs.length }) : "…"}
          {p && p.jobs_failed > 0 ? ` · ${tx("{n} failed", { n: p.jobs_failed })}` : ""}
        </span>
        <span>{p ? tx("active {when}", { when: timeAgo(p.last_activity) }) : ""}</span>
      </div>
    </div>
  );
}
