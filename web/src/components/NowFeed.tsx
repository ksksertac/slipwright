import { useEffect, useState } from "react";
import type { Job, Transition } from "../api/client";
import { useT } from "../i18n";
import { noteText } from "../i18n/notes";
import { useSay } from "../i18n/said";
import { AgentIcon, ROLE_LABEL } from "./agents";
import type { BreakdownShape, PlanShape } from "./Breakdown";
import { formatTime, hasFinished, StateBadge, timeAgo } from "./ui";

/** One model call as the job logs it (engine.py ``_account``). Everything is optional:
 * the provider, the model and what it wrote were added to the log over time, and a call
 * made before then has none of them. */
interface Call {
  role: string;
  provider?: string | null;
  model?: string | null;
  phase?: number | null;
  attempts?: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  ok: boolean;
  error?: string | null;
  started_at?: string | null;
  summary?: string | null;
  output?: string | null;
  at: string;
}

/** The call being waited on, written before the answer exists (``JobData.inflight``). */
interface InFlight {
  role: string;
  provider?: string | null;
  model?: string | null;
  phase?: number | null;
  started_at: string;
}

type Entry = { kind: "call"; at: string; call: Call } | { kind: "note"; at: string; t: Transition };

/**
 * What a development is doing right now, and what it has done, newest first.
 *
 * No provider streams, so nothing here is the answer being typed: an answer arrives whole
 * when the call ends. What the page can say in between is who was asked, on which model,
 * and how long ago -- that card sits on top, counting, until the answer replaces it with
 * what was written. Everything else is the history and the call log, merged by time.
 */
export function NowFeed({ job }: { job: Job }) {
  const tx = useT();
  const calls = (job.data.invocation_log ?? []) as unknown as Call[];
  const inflight = (job.data.inflight ?? null) as InFlight | null;
  const entries: Entry[] = [
    ...calls.map((call): Entry => ({ kind: "call", at: call.at, call })),
    // the moves between states are the headings the notes already give; a move with no
    // note says nothing a person would read
    ...job.history.filter((t) => t.note).map((t): Entry => ({ kind: "note", at: t.at, t })),
  ].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0));

  return (
    <div className="now">
      <NowHead job={job} inflight={inflight} />
      <ol className="now-feed">
        {inflight && !hasFinished(job.state) && <Waiting call={inflight} />}
        {entries.map((e, i) =>
          e.kind === "call" ? (
            <CallItem key={`c${i}`} call={e.call} />
          ) : (
            <NoteItem key={`n${i}`} t={e.t} />
          ),
        )}
        {entries.length === 0 && !inflight && (
          <li className="now-empty muted small">{tx("Nothing has happened yet.")}</li>
        )}
      </ol>
    </div>
  );
}

/** Where the development is: the stage, the phase and the task it is on, and who has it. */
function NowHead({ job, inflight }: { job: Job; inflight: InFlight | null }) {
  const tx = useT();
  const say = useSay();
  const plan = job.data.plan as PlanShape | null;
  const index = job.data.phase_index ?? 0;
  const phase = plan?.phases?.[index];
  const developing = job.state === "developing" && phase;
  const task = developing ? taskTitle(job, phase.task_id) : null;
  const done = hasFinished(job.state);
  return (
    <div className="card now-head">
      <div className="now-head-top">
        <span className="now-label">{done ? tx("Finished") : tx("Right now")}</span>
        <StateBadge state={job.state} />
        {!done && inflight && (
          <span className="now-who" data-agent={inflight.role}>
            <span className="role-ink">
              <AgentIcon role={inflight.role} />
            </span>
            {tx(ROLE_LABEL[inflight.role] ?? inflight.role)}
          </span>
        )}
      </div>
      {developing && (
        <div className="now-where">
          <div className="now-phase">
            <span className="faint small">
              {tx("Phase {i} of {n}", { i: index + 1, n: plan!.phases.length })}
            </span>
            <strong>{say(phase.goal)}</strong>
          </div>
          {task && (
            <div className="now-task">
              <span className="faint small">{tx("Task")}</span>
              <span>{say(task)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** The call in the air: who, on what, and a clock that keeps going until it lands. */
function Waiting({ call }: { call: InFlight }) {
  const tx = useT();
  const seconds = useSecondsSince(call.started_at);
  return (
    <li className="now-item now-waiting" data-agent={call.role}>
      <div className="now-item-head">
        <span className="pulse-dot" />
        <span className="role-ink">
          <AgentIcon role={call.role} />
        </span>
        <strong>{tx(ROLE_LABEL[call.role] ?? call.role)}</strong>
        <Model provider={call.provider} model={call.model} />
        <span className="now-time mono small">{clock(seconds)}</span>
      </div>
      <div className="now-writing">
        <span>{tx("Waiting for the answer")}</span>
        <span className="now-dots" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
      </div>
      <div className="now-skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </li>
  );
}

function CallItem({ call }: { call: Call }) {
  const tx = useT();
  const say = useSay();
  const took = duration(call.started_at, call.at);
  const tokens =
    call.input_tokens != null || call.output_tokens != null
      ? `${call.input_tokens ?? "—"} → ${call.output_tokens ?? "—"}`
      : null;
  return (
    <li className={`now-item ${call.ok ? "" : "bad"}`} data-agent={call.role}>
      <div className="now-item-head">
        <span className="role-ink">
          <AgentIcon role={call.role} />
        </span>
        <strong>{tx(ROLE_LABEL[call.role] ?? call.role)}</strong>
        <Model provider={call.provider} model={call.model} />
        <span className={`badge plain ${call.ok ? "ok" : "bad"}`}>
          {call.ok ? tx("answered") : (call.error ?? tx("failed"))}
        </span>
        <span className="now-time faint small" title={formatTime(call.at)}>
          {took && <span className="mono">{took} · </span>}
          {timeAgo(call.at)}
        </span>
      </div>
      {call.summary && <p className="now-summary">{say(call.summary)}</p>}
      <div className="now-meta faint tiny mono">
        {[
          call.phase ? tx("phase {n}", { n: call.phase }) : null,
          tokens ? `${tokens} tokens` : null,
          call.attempts && call.attempts > 1 ? `${call.attempts} ${tx("attempts")}` : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </div>
      {call.output && (
        <details className="now-output">
          <summary>{tx("What it wrote")}</summary>
          <pre>{call.output}</pre>
        </details>
      )}
    </li>
  );
}

function NoteItem({ t }: { t: Transition }) {
  const tx = useT();
  const say = useSay();
  return (
    <li className="now-item note">
      <div className="now-item-head">
        {/* the engine writes its notes in English; the History tab reads them back in the
            platform's language, and so does this */}
        <span className="now-note">{noteText(tx, t.note ?? "", say)}</span>
        <span className="now-time faint small" title={formatTime(t.at)}>
          {timeAgo(t.at)}
        </span>
      </div>
      {t.detail && (
        <details className="now-output">
          <summary>{tx("Details")}</summary>
          <pre>{t.detail.length > 4000 ? `${t.detail.slice(0, 4000)}…` : t.detail}</pre>
        </details>
      )}
    </li>
  );
}

function Model({ provider, model }: { provider?: string | null; model?: string | null }) {
  if (!provider && !model) return null;
  return (
    <span className="now-model mono small">
      {provider ? `${provider} · ` : ""}
      {model ?? ""}
    </span>
  );
}

function taskTitle(job: Job, taskId: string | null | undefined): string | null {
  if (!taskId) return null;
  const backlog = ((job.data.plan as PlanShape | null)?.breakdown ??
    job.data.backlog) as BreakdownShape | null;
  for (const epic of backlog?.epics ?? []) {
    for (const story of epic.stories ?? []) {
      const task = story.tasks?.find((t) => t.id === taskId);
      if (task) return task.title;
    }
  }
  return null;
}

/** Seconds since ``iso``, ticking once a second while the component is shown. */
function useSecondsSince(iso: string): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
}

function clock(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function duration(from: string | null | undefined, to: string): string | null {
  if (!from) return null;
  const s = Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}
