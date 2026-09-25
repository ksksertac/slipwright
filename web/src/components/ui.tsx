import type { ReactNode } from "react";
import type { JobState, TaskStatus } from "../api/client";
import { IconFolder } from "./icons";
import { currentLang } from "../i18n";
import { useT } from "../i18n";

const STATE_CLASS: Record<JobState, string> = {
  created: "idle",
  backlog: "work",
  awaiting_backlog_approval: "wait",
  architecture: "work",
  awaiting_architecture_approval: "wait",
  design: "work",
  awaiting_design_approval: "wait",
  developing: "work",
  build_gate: "work",
  review: "work",
  awaiting_review_approval: "wait",
  qa: "work",
  awaiting_test_approval: "wait",
  devops: "work",
  awaiting_deploy_approval: "wait",
  awaiting_decision: "wait",
  done: "ok",
  failed: "bad",
};

export const STATE_LABEL: Record<JobState, string> = {
  created: "created",
  backlog: "writing backlog",
  awaiting_backlog_approval: "needs backlog approval",
  architecture: "designing",
  awaiting_architecture_approval: "needs architecture approval",
  design: "designing the screens",
  awaiting_design_approval: "needs design approval",
  developing: "developing",
  build_gate: "build gate",
  review: "standards review",
  awaiting_review_approval: "needs review decision",
  qa: "qa",
  awaiting_test_approval: "needs test approval",
  devops: "devops",
  awaiting_deploy_approval: "needs deployment approval",
  awaiting_decision: "needs your decision",
  done: "done",
  failed: "failed",
};

export function StateBadge({ state }: { state: JobState }) {
  const tx = useT();
  return <span className={`badge ${STATE_CLASS[state]}`}>{tx(STATE_LABEL[state])}</span>;
}

const STATUS_CLASS: Record<TaskStatus, string> = {
  todo: "idle",
  in_progress: "work",
  done: "ok",
  failed: "bad",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  const tx = useT();
  return <span className={`badge ${STATUS_CLASS[status]}`}>{tx(status.replace("_", " "))}</span>;
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
  const tr = currentLang() === "tr";
  if (delta < 45) return tr ? "az önce" : "just now";
  if (delta < 3600) return `${Math.round(delta / 60)} ${tr ? "dk önce" : "min ago"}`;
  if (delta < 86400) return `${Math.round(delta / 3600)} ${tr ? "sa önce" : "h ago"}`;
  return `${Math.round(delta / 86400)} ${tr ? "gün önce" : "d ago"}`;
}

/** What somebody typed, shown as a title: the first letter raised, the rest left alone.
 *
 * Turkish decides the case of an i by its dot, so the raising is done in the language the
 * page is in -- "istanbul" becomes "İstanbul" here and "Istanbul" on the English side.
 * The rest of the line is left exactly as it was typed, because lowering it would spell
 * "API" and "Jira" wrong. A line typed entirely in capitals is the one exception: there
 * the shouting is not something anybody meant to keep, so it is brought back down. */
export function sentence(text: string): string {
  const s = text.trimStart();
  if (!s) return text;
  const locale = currentLang() === "tr" ? "tr-TR" : "en-GB";
  const upper = s.toLocaleUpperCase(locale);
  const shouted = s.length > 1 && s === upper && s !== s.toLocaleLowerCase(locale);
  const rest = s.slice(1);
  return s[0]!.toLocaleUpperCase(locale) + (shouted ? rest.toLocaleLowerCase(locale) : rest);
}

/** A moment a person can place at a glance: today and yesterday are said in words, the
 * rest carries its date, and the year only appears once it is not this one. The browser's
 * own locale is not asked -- the platform's language is the one on screen, so a Turkish
 * page never says "Sep 23" and an English one never says "23 Eyl". */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const tr = currentLang() === "tr";
  const locale = tr ? "tr-TR" : "en-GB";
  const clock = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const now = new Date();
  const midnight = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((midnight(now) - midnight(d)) / 86_400_000);
  if (days === 0) return `${tr ? "Bugün" : "Today"} ${clock}`;
  if (days === 1) return `${tr ? "Dün" : "Yesterday"} ${clock}`;
  const day = d.toLocaleDateString(locale, {
    day: "numeric",
    month: "long",
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
  return `${day} ${clock}`;
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

/** The tone tints the tile's mark. It is the state the number is about -- running,
 *  waiting, done -- so the colour says what the label says, never something else. */
export type Tone = "neutral" | "run" | "wait" | "done";

export function StatTile({
  label,
  value,
  sub,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="tile" data-tone={tone}>
      <div className="tile-head">
        <div className="label">{label}</div>
        {icon && <span className="tile-mark">{icon}</span>}
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

/**
 * Pages a long list. A list shorter than one page draws nothing at all, so the control
 * appears exactly when it is needed. It states where you are ("11-20 / 34") rather than
 * only offering arrows, because a number of developments is worth knowing.
 */
export function Pager({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number; // zero-based
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const tx = useT();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  const first = page * pageSize + 1;
  const last = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="pager">
      <span className="faint small">
        {tx("{from}-{to} of {total}", { from: first, to: last, total })}
      </span>
      <div className="row" style={{ gap: 6 }}>
        <button className="btn small" onClick={() => onPage(page - 1)} disabled={page === 0}>
          {tx("Previous")}
        </button>
        <span className="faint tiny mono">{`${page + 1} / ${pages}`}</span>
        <button className="btn small" onClick={() => onPage(page + 1)} disabled={page >= pages - 1}>
          {tx("Next")}
        </button>
      </div>
    </div>
  );
}
