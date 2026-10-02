// The pieces several pages share: icons, the switch, an agent's card, and how an agent's
// state is read off the app state.

import type { ReactNode } from "react";
import type { AgentId, AppState, ModelChoice, TaskView } from "@shared/types";
import { t } from "./i18n";

const svg = (children: ReactNode, round = true) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap={round ? "round" : undefined}>
    {children}
  </svg>
);

export const Icon = {
  now: svg(<path d="M3 12h4l3-8 4 16 3-8h4" />),
  history: svg(
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>,
  ),
  team: svg(
    <>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6" />
    </>,
  ),
  models: svg(
    <>
      <rect x="5" y="5" width="14" height="14" rx="2" />
      <rect x="9" y="9" width="6" height="6" />
      <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" />
    </>,
    false,
  ),
  source: svg(
    <>
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="6" cy="18" r="2.5" />
      <circle cx="18" cy="8" r="2.5" />
      <path d="M6 8.5v7M18 10.5c0 4-5 3-8 5" />
    </>,
    false,
  ),
  jira: svg(<path d="M3 9V7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a2 2 0 0 0 0 6v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-6z" />, false),
  settings: svg(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" />
    </>,
  ),
  pause: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M9 5v14M15 5v14" />
    </svg>
  ),
  play: (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M8 5v14l11-7z" />
    </svg>
  ),
  check: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </svg>
  ),
  cross: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  ),
  backend: svg(
    <>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <path d="M7 7.5h.01M7 16.5h.01" />
    </>,
  ),
  web: svg(
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M7 6.5h.01M10 6.5h.01" />
    </>,
  ),
  mobile: svg(
    <>
      <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
      <path d="M11 18.5h2" />
    </>,
  ),
  devops: svg(
    <>
      <path d="M12 3v4M12 17v4M5 12H3M21 12h-2M7 7l-1.5-1.5M18.5 18.5 17 17M7 17l-1.5 1.5M18.5 5.5 17 7" />
      <circle cx="12" cy="12" r="4" />
    </>,
  ),
};

export const AGENT_NAME: Record<AgentId, string> = { backend: "Backend", web: "Web", mobile: "Mobile", devops: "DevOps" };
export const DOMAINS: Record<AgentId, string[]> = {
  backend: ["backend", "general", "docs"],
  web: ["web"],
  mobile: ["mobile"],
  devops: ["infra"],
};

export function Switch({ on, onChange, label, disabled }: { on: boolean; onChange: (on: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} className={`switch${on ? " on" : ""}`} onClick={() => onChange(!on)} />;
}

export function modelLabel(choice: ModelChoice | null): string {
  if (!choice) return "—";
  const name = { "claude-code": "Claude Code", codex: "Codex", anthropic: "Anthropic API", openai: "OpenAI API" }[choice.provider];
  return choice.model ? `${name} · ${choice.model}` : name;
}

export function usable(state: AppState, choice: ModelChoice | null): boolean {
  if (!choice) return false;
  const d = state.detected;
  switch (choice.provider) {
    case "claude-code":
      return d.claude.installed && d.claude.signedIn !== false;
    case "codex":
      return d.codex.installed && d.codex.signedIn !== false;
    case "anthropic":
      return !!state.secrets.anthropic;
    case "openai":
      return !!state.secrets.openai;
  }
}

export type AgentStatus = "run" | "idle" | "off";

export function agentStatus(state: AppState, agent: AgentId): { status: AgentStatus; task: TaskView | null; why: string | null } {
  const task = state.tasks.find((x) => x.agent === agent) ?? null;
  if (task) return { status: "run", task, why: null };
  const own = state.settings.agents[agent];
  if (!own.enabled) return { status: "off", task: null, why: t("off on this machine") };
  if (!usable(state, own.model)) return { status: "off", task: null, why: t("no model") };
  return { status: "idle", task: null, why: null };
}

export function minutes(ms: number): string {
  const m = Math.floor(ms / 60_000);
  return m < 1 ? t("<1 min") : t("{min} min", { min: m });
}

export function platformsLine(state: AppState): string | null {
  const can = [state.detected.ios.ok ? "iOS" : null, state.detected.android.ok ? "Android" : null].filter(Boolean);
  return can.length ? can.join(", ") : null;
}

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function TaskBox({ task, now }: { task: TaskView; now: number }) {
  const elapsed = now - task.startedAt;
  // a model call has no "percent done"; the bar is time against its allowance, so a call
  // near the end of it shows as near the end
  const pct = Math.min(96, Math.max(3, (elapsed / (task.timeoutS * 1000)) * 100));
  const stage = { writing: t("writing"), checkout: t("fetching code"), starting: t("starting"), building: t("building") }[task.status] ?? task.status;
  return (
    <div className="task">
      <div className="l1">
        <b>{task.goal || task.project}</b>
        <span>{task.phase ? t("Phase {n}/{m}", { n: task.phase, m: task.phases ?? "?" }) : (task.platform ?? "")}</span>
      </div>
      <div className="prog">
        <i style={{ width: `${pct}%` }} />
      </div>
      <div className="meta">
        {task.project && (
          <span>
            <b>{task.project}</b>
          </span>
        )}
        <span>
          {stage} · {minutes(elapsed)}
        </span>
        {task.jiraKey && <span className="mono">{task.jiraKey}</span>}
      </div>
    </div>
  );
}

export function LiveLog({ task }: { task: TaskView }) {
  if (!task.log.length) return <div className="empty">{t("Nothing yet")}</div>;
  return (
    <pre className="log" aria-label={t("Live log")}>
      {task.log.map((line, n) => (
        <div key={n}>
          <span className="t">{time(line.at)}</span> <span className={line.tone ?? ""}>{line.text}</span>
        </div>
      ))}
    </pre>
  );
}

export function AgentCard({ state, agent, full, now, onOpen }: { state: AppState; agent: AgentId; full: boolean; now: number; onOpen?: () => void }) {
  const { status, task, why } = agentStatus(state, agent);
  const own = state.settings.agents[agent];
  const pill = { run: "p-run", idle: "p-idle", off: "p-off" }[status];
  const label = status === "run" ? (task?.kind === "build" ? t("building") : t("writing")) : status === "idle" ? t("idle") : why;
  const platforms = agent === "mobile" ? platformsLine(state) : null;
  let sub: string;
  if (!own.enabled) sub = t("This machine does not take {agent} phases", { agent: AGENT_NAME[agent] });
  else if (!usable(state, own.model)) sub = t("Choose a model for this agent under Models");
  else if (platforms) {
    const d = state.detected;
    const versions = [d.ios.ok ? d.ios.detail : null, d.android.ok ? `Android ${d.android.detail}` : null].filter(Boolean).join(", ");
    sub = t("Can build {what}", { what: versions ? `${platforms} (${versions})` : platforms });
  } else sub = t("Waiting for a phase");
  return (
    <div className={`card agent${onOpen ? " link" : ""}`} onClick={onOpen} role={onOpen ? "button" : undefined} tabIndex={onOpen ? 0 : undefined} onKeyDown={(e) => onOpen && e.key === "Enter" && onOpen()}>
      <div className="top">
        <div className="av">{Icon[agent]}</div>
        <div>
          <b>{AGENT_NAME[agent]}</b>
          <small>{modelLabel(own.enabled || task ? own.model : null)}</small>
        </div>
        <span className={`pill ${pill}`}>{label}</span>
      </div>
      {task ? <TaskBox task={task} now={now} /> : <div className="empty">{sub}</div>}
      {task && full && <LiveLog task={task} />}
    </div>
  );
}
