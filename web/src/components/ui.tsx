import type { ReactNode } from "react";
import type { JobState, TaskStatus } from "../api/client";

const STATE_CLASS: Record<JobState, string> = {
  created: "idle",
  analyzing: "work",
  awaiting_profile_approval: "wait",
  planning: "work",
  awaiting_plan_approval: "wait",
  developing: "work",
  build_gate: "work",
  qa: "work",
  awaiting_test_approval: "wait",
  devops: "work",
  done: "ok",
  failed: "bad",
};

export function StateBadge({ state }: { state: JobState }) {
  return <span className={`badge ${STATE_CLASS[state]}`}>{state.replaceAll("_", " ")}</span>;
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

export function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((done / total) * 100);
  return (
    <div className="row" style={{ gap: 8 }}>
      <div className="progress" style={{ flex: 1, minWidth: 80 }}>
        <div style={{ width: `${pct}%` }} />
      </div>
      <span className="muted small mono">
        {done}/{total}
      </span>
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
    second: "2-digit",
  });
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="card muted">{children}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const text = error instanceof Error ? error.message : String(error);
  return <div className="error">{text}</div>;
}

export function Loading() {
  return <div className="muted">Loading…</div>;
}
