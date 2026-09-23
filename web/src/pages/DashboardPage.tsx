import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { describeError, type Job } from "../api/client";
import { useOverview, useProjects, useJob, useUndoAutoApproval } from "../api/hooks";
import { useToast } from "../components/Toast";
import { BulkBar } from "../components/BulkBar";
import { Crumbs } from "../components/Crumbs";
import { GateActions, Recommendation } from "../components/GateActions";
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
import { ActivityChart, RoleLoadChart, StateBar } from "../components/charts";
import {
  Empty,
  ErrorBox,
  Loading,
  PageHead,
  ProgressBar,
  StatTile,
  timeAgo,
} from "../components/ui";
import { useT } from "../i18n";

export function DashboardPage() {
  const tx = useT();
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
        title={tx("Dashboard")}
        subtitle={tx("What the agents are doing right now, and what waits for you.")}
        actions={
          <Link className="btn primary" to="/projects/new">
            <IconPlus /> {tx("New project")}
          </Link>
        }
      />

      <div className="grid-tiles">
        <StatTile
          label={tx("Projects")}
          icon={<IconFolder />}
          value={o.projects}
          sub={tx("{n} development(s) in total", { n: o.jobs_total })}
        />
        <StatTile
          label={tx("Running")}
          icon={<IconPlay />}
          value={o.jobs_running}
          sub={tx("agents working now")}
        />
        <StatTile
          label={tx("Waiting for you")}
          icon={<IconInbox />}
          value={o.pending_approvals}
          sub={o.pending_approvals ? tx("approvals pending") : tx("nothing pending")}
        />
        <StatTile
          label={tx("Tasks done")}
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
          label={tx("Outcomes")}
          icon={<IconCheck />}
          value={
            <span className="outcomes">
              <span>
                <span style={{ color: "var(--good-text)" }}>{o.jobs_done}</span>
                <span className="unit">{tx("done")}</span>
              </span>
              <span>
                <span style={{ color: "var(--bad-text)" }}>{o.jobs_failed}</span>
                <span className="unit">{tx("failed")}</span>
              </span>
            </span>
          }
        />
      </div>

      <div className="dash-charts">
        <div className="card">
          <ActivityChart days={o.by_day} />
        </div>
        <div className="card">
          <StateBar o={o} />
        </div>
        <div className="card">
          <RoleLoadChart roles={o.by_role} />
        </div>
      </div>

      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="card flush">
          <div className="card-head">
            <h3>
              <IconAlert style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 6 }} />
              {tx("Pending approvals")}
            </h3>
            <span className="row" style={{ gap: 8 }}>
              {o.waiting.length > 1 && (
                <button
                  className="btn ghost small"
                  disabled={selected.length === o.waiting.length}
                  onClick={() => setSelected(o.waiting.map((w) => w.job_id))}
                >
                  {tx("Select all")}
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
              <div className="small">{tx("Nothing waits for you.")}</div>
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
              {tx("Recent activity")}
            </h3>
          </div>
          {o.recent.length === 0 ? (
            <div className="empty" style={{ padding: 28 }}>
              <div className="small">
                No activity yet.{" "}
                {o.projects === 0 ? (
                  <Link to="/projects/new">{tx("Add a project")}</Link>
                ) : (
                  <Link to="/projects">{tx("Start a development")}</Link>
                )}
                .
              </div>
            </div>
          ) : (
            <ul className="feed capped">
              {o.recent.map((item) => (
                <ActivityRow
                  key={`${item.job_id}:${item.index}`}
                  item={item}
                  projectId={item.project_id ?? ""}
                  projectName={byId.get(item.project_id ?? "")?.name}
                  compact
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

      {o.auto_approved.length > 0 && (
        <div className="card flush" style={{ marginTop: 18 }}>
          <div className="card-head">
            <h3>{tx("Approved by the supervisor")}</h3>
            <span className="badge plain idle">{o.auto_approved.length}</span>
          </div>
          <table>
            <tbody>
              {o.auto_approved.map((w) => (
                <AutoApprovedRow
                  key={w.job_id}
                  jobId={w.job_id}
                  request={w.request}
                  projectId={w.project_id ?? ""}
                  projectName={byId.get(w.project_id ?? "")?.name}
                  phase={w.current_phase}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {projects.data && projects.data.length === 0 && (
        <div style={{ marginTop: 18 }}>
          <Empty
            title={tx("Add your first project")}
            action={
              <Link className="btn primary" to="/projects/new">
                <IconPlus /> {tx("New project")}
              </Link>
            }
          >
            {tx(
              "A project is a repository the agents work on. Connect GitHub under Settings, or point at a local checkout.",
            )}
          </Empty>
        </div>
      )}
    </div>
  );
}

/** A gate the supervisor approved: the job runs on; the human can still overrule it. */
function AutoApprovedRow({
  jobId,
  request,
  projectId,
  projectName,
  phase,
}: {
  jobId: string;
  request: string;
  projectId: string;
  projectName?: string;
  phase: string;
}) {
  const tx = useT();
  const undo = useUndoAutoApproval(jobId);
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  return (
    <tr>
      <td style={{ width: "100%" }}>
        <Link to={`/projects/${projectId}/jobs/${jobId}`}>
          <strong>{request}</strong>
        </Link>
        <div className="faint tiny">
          {projectName ? `${projectName} · ` : ""}
          {phase || "running"}
        </div>
      </td>
      <td className="actions" style={{ whiteSpace: "nowrap" }}>
        {!open ? (
          <button className="btn bad small" onClick={() => setOpen(true)}>
            {tx("Undo…")}
          </button>
        ) : (
          <div className="row">
            <input
              type="text"
              style={{ width: 240 }}
              placeholder={tx("what the supervisor missed")}
              value={feedback}
              autoFocus
              onChange={(e) => setFeedback(e.target.value)}
            />
            <button
              className="btn bad small"
              disabled={!feedback.trim() || undo.isPending}
              onClick={() =>
                undo.mutate(feedback.trim(), {
                  onSuccess: () => {
                    toast.ok("Feedback queued for the next agent");
                    setOpen(false);
                  },
                  onError: (e) => toast.bad(describeError(e)),
                })
              }
            >
              {tx("Send")}
            </button>
            <button className="btn small" onClick={() => setOpen(false)}>
              {tx("Cancel")}
            </button>
          </div>
        )}
      </td>
    </tr>
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
        {j && (
          <div style={{ marginTop: 4 }}>
            <Recommendation job={j} />
          </div>
        )}
      </td>
      <td className="actions" style={{ whiteSpace: "nowrap" }}>
        {j && <GateActions job={j} compact />}
      </td>
    </tr>
  );
}
