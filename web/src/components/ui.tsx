import type { ReactNode } from "react";
import type { JobState, TaskStatus } from "../api/client";
import { IconFolder } from "./icons";

const STATE_CLASS: Record<JobState, string> = {
  created: "idle",
  backlog: "work",
  awaiting_backlog_approval: "wait",
  architecture: "work",
  awaiting_architecture_approval: "wait",
  developing: "work",
  build_gate: "work",
  qa: "work",
  awaiting_test_approval: "wait",
  devops: "work",
  done: "ok",
  failed: "bad",
};

export const STATE_LABEL: Record<JobState, string> = {
  created: "created",
  backlog: "writing backlog",
  awaiting_backlog_approval: "needs backlog approval",
  architecture: "designing",
  awaiting_architecture_approval: "needs architecture approval",
  developing: "developing",
  build_gate: "build gate",
  qa: "qa",
  awaiting_test_approval: "needs test approval",
  devops: "devops",
  done: "done",
  failed: "failed",
};

export function StateBadge({ state }: { state: JobState }) {
  return <span className={`badge ${STATE_CLASS[state]}`}>{STATE_LABEL[state]}</span>;
}

const STATUS_CLASS: Record<TaskStatus, string> = {
  todo: "idle",
  in_progress: "work",
  done: "ok",
  failed: "bad",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`badge ${STATUS_CLASS[status]}`}>{status.replace("_", " ")}</span>;
}

export function StatusDot({ status }: { status: TaskStatus }) {
  return <span className={`status-dot ${status}`} title={status} />;
}

export function ProgressBar({
  done,
  total,
  showText = true,
}: {
  done: number;
  total: number;
  showText?: boolean;
}) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);
  return (
    <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
      <div
        className={`progress ${pct === 100 ? "good" : ""}`}
        style={{ flex: 1, minWidth: 60 }}
        role="progressbar"
        aria-valuenow={pct}
      >
        <div style={{ width: `${pct}%` }} />
      </div>
      {showText && (
        <span className="faint small mono" style={{ whiteSpace: "nowrap" }}>
          {done}/{total}
        </span>
      )}
    </div>
  );
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const delta = (Date.now() - new Date(iso).getTime()) / 1000;
  if (delta < 45) return "just now";
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`;
  return `${Math.round(delta / 86400)} d ago`;
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function Empty({
  title,
  children,
  icon,
  action,
}: {
  title?: string;
  children: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="card empty">
      <div className="glyph">{icon ?? <IconFolder />}</div>
      {title && <h3>{title}</h3>}
      <div className="small">{children}</div>
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const text = error instanceof Error ? error.message : String(error);
  return <div className="callout error">{text}</div>;
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack" style={{ gap: 10 }} aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 15}%` }} />
      ))}
    </div>
  );
}

export function StatTile({
  label,
  value,
  sub,
  icon,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="tile">
      <div className="label">
        {icon}
        {label}
      </div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function PageHead({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}
