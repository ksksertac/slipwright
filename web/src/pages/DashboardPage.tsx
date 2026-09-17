import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Job } from "../api/client";
import { useOverview, useProjects, useJob } from "../api/hooks";
import { BulkBar } from "../components/BulkBar";
import { Crumbs } from "../components/Crumbs";
import { GateActions } from "../components/GateActions";
import {
  IconActivity,
  IconAlert,
  IconCheck,
  IconFolder,
  IconInbox,
  IconLayers,
  IconPlay,
  IconPlus,
} from "../components/icons";
import { ActivityRow } from "../components/ActivityRow";
import {
  Empty,
  ErrorBox,
  Loading,
  PageHead,
  ProgressBar,
  StatTile,
  timeAgo,
} from "../components/ui";

export function DashboardPage() {
  const overview = useOverview();
  const projects = useProjects();
  const byId = new Map((projects.data ?? []).map((p) => [p.id, p]));
  const [chosen, setSelected] = useState<string[]>([]);
  const waitingIds = useMemo(
    () => new Set((overview.data?.waiting ?? []).map((w) => w.job_id)),
    [overview.data],
  );
  // a job that moved on drops out of the selection by itself
  const selected = useMemo(() => chosen.filter((id) => waitingIds.has(id)), [chosen, waitingIds]);

  if (overview.isLoading) return <Loading rows={5} />;
  if (overview.error) return <ErrorBox error={overview.error} />;
  const o = overview.data!;

  return (
    <div>
      <Crumbs items={[{ label: "Dashboard" }]} />
      <PageHead
        title="Dashboard"
        subtitle="What the agents are doing right now, and what waits for you."
        actions={
          <Link className="btn primary" to="/projects/new">
            <IconPlus /> New project
          </Link>
        }
      />

      <div className="grid-tiles">
        <StatTile
          label="Projects"
          icon={<IconFolder />}
          value={o.projects}
          sub={`${o.jobs_total} development${o.jobs_total === 1 ? "" : "s"} in total`}
        />
        <StatTile
          label="Running"
          icon={<IconPlay />}
          value={o.jobs_running}
          sub="agents working now"
        />
        <StatTile
          label="Waiting for you"
          icon={<IconInbox />}
          value={o.pending_approvals}
          sub={o.pending_approvals ? "approvals pending" : "nothing pending"}
        />
        <StatTile
          label="Tasks done"
          icon={<IconLayers />}
          value={
            <span>
              {o.tasks_done}
              <span className="faint" style={{ fontSize: 15 }}>
                {" "}
                / {o.tasks_total}
              </span>
            </span>
          }
          sub={<ProgressBar done={o.tasks_done} total={o.tasks_total} showText={false} />}
        />
        <StatTile
          label="Outcomes"
          icon={<IconCheck />}
          value={
            <span>
              <span style={{ color: "var(--good-text)" }}>{o.jobs_done}</span>
              <span className="faint" style={{ fontSize: 15 }}>
                {" "}
                done
              </span>{" "}
              <span style={{ color: "var(--bad-text)" }}>{o.jobs_failed}</span>
              <span className="faint" style={{ fontSize: 15 }}>
                {" "}
                failed
              </span>
            </span>
          }
        />
      </div>

      <div className="grid-2" style={{ marginTop: 18, alignItems: "start" }}>
        <div className="card flush">
          <div className="card-head">
            <h3>
              <IconAlert style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 6 }} />
              Pending approvals
            </h3>
            <span className="row" style={{ gap: 8 }}>
              {o.waiting.length > 1 && (
                <button
                  className="btn ghost small"
                  disabled={selected.length === o.waiting.length}
                  onClick={() => setSelected(o.waiting.map((w) => w.job_id))}
                >
                  Select all
                </button>
              )}
              <span className="badge wait plain">{o.waiting.length}</span>
            </span>
          </div>
          {o.waiting.length === 0 ? (
            <div className="empty" style={{ padding: 28 }}>
              <div className="glyph">
                <IconCheck />
              </div>
              <div className="small">Nothing waits for you.</div>
            </div>
          ) : (
            <table>
              <tbody>
                {o.waiting.map((w) => (
                  <WaitingRow
                    key={w.job_id}
                    jobId={w.job_id}
                    request={w.request}
                    projectName={byId.get(w.project_id ?? "")?.name}
                    projectId={w.project_id ?? undefined}
                    pending={w.pending_approval ?? ""}
                    at={w.last_activity}
                    selected={selected.includes(w.job_id)}
                    onSelect={(on) =>
                      setSelected((ids) =>
                        on ? [...new Set([...ids, w.job_id])] : ids.filter((i) => i !== w.job_id),
                      )
                    }
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card flush">
          <div className="card-head">
            <h3>
              <IconActivity style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 6 }} />
              Recent activity
            </h3>
          </div>
          {o.recent.length === 0 ? (
            <div className="empty" style={{ padding: 28 }}>
              <div className="small">
                No activity yet.{" "}
                {o.projects === 0 ? (
                  <Link to="/projects/new">Add a project</Link>
                ) : (
                  <Link to="/projects">Start a development</Link>
                )}
                .
              </div>
            </div>
          ) : (
            <ul className="feed" style={{ padding: "0 20px" }}>
              {o.recent.map((item) => (
                <ActivityRow
                  key={`${item.job_id}:${item.index}`}
                  item={item}
                  projectId={item.project_id ?? ""}
                  projectName={byId.get(item.project_id ?? "")?.name}
                />
              ))}
            </ul>
          )}
        </div>
      </div>

      <BulkBar
        selected={selected}
        onClear={() => setSelected([])}
        labelOf={(id) => o.waiting.find((w) => w.job_id === id)?.request ?? id}
      />

      {projects.data && projects.data.length === 0 && (
        <div style={{ marginTop: 18 }}>
          <Empty
            title="Add your first project"
            action={
              <Link className="btn primary" to="/projects/new">
                <IconPlus /> New project
              </Link>
            }
          >
            A project is a repository the agents work on. Connect GitHub under Settings, or point at
            a local checkout.
          </Empty>
        </div>
      )}
    </div>
  );
}

function WaitingRow({
  jobId,
  request,
  projectName,
  projectId,
  pending,
  at,
  selected,
  onSelect,
}: {
  jobId: string;
  request: string;
  projectName?: string;
  projectId?: string;
  pending: string;
  at: string;
  selected: boolean;
  onSelect: (on: boolean) => void;
}) {
  const job = useJob(jobId);
  const j: Job | undefined = job.data;
  return (
    <tr>
      <td style={{ width: 28 }}>
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
          aria-label={`select ${request}`}
        />
      </td>
      <td style={{ width: "100%" }}>
        <Link to={`/projects/${projectId ?? j?.project_id ?? ""}/jobs/${jobId}`}>
          <strong>{request}</strong>
        </Link>
        <div className="faint tiny">
          {projectName ? `${projectName} · ` : ""}needs <strong>{pending}</strong> approval ·{" "}
          {timeAgo(at)}
        </div>
      </td>
      <td className="actions" style={{ whiteSpace: "nowrap" }}>
        {j && <GateActions job={j} compact />}
      </td>
    </tr>
  );
}
