import { useEffect, useState } from "react";
import type { Job, Transition } from "../api/client";
import { currentLang, useT } from "../i18n";
import { usd } from "../pages/CostsTab";
import { noteText } from "../i18n/notes";
import { useSay } from "../i18n/said";
import { AgentIcon, ROLE_LABEL } from "./agents";
import type { BreakdownShape, PlanShape } from "./Breakdown";
import {
  cut,
  PHASE_STATES,
  sectionOf,
  stageOfState,
  type Call,
  type Entry,
  type Section,
} from "./nowSections";
import { phaseName, STAGE_LABEL } from "./stages";
import { hasDetail, useEntryDetail } from "./EntryDetail";
import { formatTime, hasFinished, Loading, StateBadge, timeAgo } from "./ui";

/** The call being waited on, written before the answer exists (``JobData.inflight``). */
interface InFlight {
  role: string;
  provider?: string | null;
  model?: string | null;
  phase?: number | null;
  started_at: string;
}

/**
 * What a development is doing right now, and what it has done, newest first.
 *
 * No provider streams, so nothing here is the answer being typed: an answer arrives whole
 * when the call ends. What the page can say in between is who was asked, on which model,
 * and how long ago -- that card sits on top, counting, until the answer replaces it with
 * what was written. Everything else is the history and the call log, merged by time.
 *
 * The feed is cut by phase. One list of everything read as phase 3's standards beside
 * phase 2's review and nobody could tell which work a card was about; under a "Phase 3 of
 * 8" heading each card belongs to the heading above it, and the phases before the one at
 * work fold away.
 */
export function NowFeed({ job }: { job: Job }) {
  const tx = useT();
  const say = useSay();
  const calls = (job.data.invocation_log ?? []) as unknown as Call[];
  const inflight = (job.data.inflight ?? null) as InFlight | null;
  const plan = job.data.plan as PlanShape | null;
  const total = plan?.phases?.length ?? null;
  const entries: Entry[] = [
    ...calls.map((call): Entry => ({ kind: "call", at: call.at, call })),
    // the moves between states are the headings the notes already give; a move with no
    // note says nothing a person would read
    ...job.history.filter((t) => t.note).map((t): Entry => ({ kind: "note", at: t.at, t })),
  ].sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
  const sections = cut(entries);
  const waiting = inflight && !hasFinished(job.state) ? inflight : null;
  // the call in the air goes on top of its own phase; a new phase starts a section of its own
  const top = sections[sections.length - 1];
  // the log names the phase only while developing; a review of it is still that phase
  const waitingPhase =
    waiting?.phase ?? (PHASE_STATES.has(job.state) && top?.phase != null ? top.phase : null);
  const waitingSection = waiting
    ? sectionOf(waitingPhase, waitingPhase !== null ? "build" : stageOfState(job.state))
    : null;
  if (waitingSection && (!top || top.key !== waitingSection.key)) sections.push(waitingSection);

  const heading = (s: Section): string => {
    if (s.phase === null) return tx(STAGE_LABEL[s.stage] ?? s.stage);
    const goal = plan?.phases?.[s.phase - 1]?.goal;
    return `${phaseName(tx, s.phase, total)}${goal ? ` · ${say(goal)}` : ""}`;
  };

  // the phases whose answers are written alongside this one (T16.3), in phase order
  const ahead = hasFinished(job.state)
    ? []
    : Object.entries((job.data.ahead ?? {}) as Record<string, { role: string; started_at: string }>)
        .map(([n, a]) => ({ phase: Number(n), role: a.role, started_at: a.started_at }))
        .sort((a, b) => a.phase - b.phase);

  return (
    <div className="now">
      <NowHead job={job} inflight={inflight} calls={calls} />
      {ahead.length > 0 && (
        <section className="now-ahead">
          <div className="faint small">
            {tx(
              "Written alongside: these phases need nothing still being built, so their answers are being written now and are ready when their turn comes.",
            )}
          </div>
          <ol className="now-feed">
            {ahead.map((a) => (
              <Waiting
                key={a.phase}
                call={a}
                label={`${phaseName(tx, a.phase, total)}${
                  plan?.phases?.[a.phase - 1]?.goal
                    ? ` · ${say(plan.phases[a.phase - 1]!.goal)}`
                    : ""
                }`}
              />
            ))}
          </ol>
        </section>
      )}
      <div className="now-sections">
        {[...sections].reverse().map((s, i) => (
          <details key={`${s.key}-${i}`} className="now-section" open={i === 0}>
            <summary>
              <span className={`now-section-mark ${s.phase !== null ? "phase" : ""}`} />
              <span className="now-section-title">{heading(s)}</span>
              <span className="faint tiny">
                {tx("{n} record(s)", { n: s.entries.length + (i === 0 && waiting ? 1 : 0) })}
              </span>
            </summary>
            <ol className="now-feed">
              {i === 0 && waiting && <Waiting call={waiting} />}
              {[...s.entries]
                .reverse()
                .map((e, j) =>
                  e.kind === "call" ? (
                    <CallItem key={`c${j}`} call={e.call} />
                  ) : (
                    <NoteItem key={`n${j}`} job={job} t={e.t} />
                  ),
                )}
            </ol>
          </details>
        ))}
        {entries.length === 0 && !waiting && (
          <p className="now-empty muted small">{tx("Nothing has happened yet.")}</p>
        )}
      </div>
    </div>
  );
}

/** Where the development is: the stage, the phase and the task it is on, and who has it. */
function NowHead({ job, inflight, calls }: { job: Job; inflight: InFlight | null; calls: Call[] }) {
  const tx = useT();
  // the development so far, from the same log the cards below are drawn from, so the
  // total is always the sum of what the page shows
  const sent = sum(calls.map((c) => c.input_tokens));
  const got = sum(calls.map((c) => c.output_tokens));
  const say = useSay();
  const plan = job.data.plan as PlanShape | null;
  const index = job.data.phase_index ?? 0;
  const phase = plan?.phases?.[index];
  const developing = job.state === "developing" && phase;
  // the head sits over one phase, so a bare total there was read as that phase's: the
  // phase's own calls are counted beside it, and each says which it is
  const here = developing ? calls.filter((c) => c.phase === index + 1) : [];
  const phaseSent = sum(here.map((c) => c.input_tokens));
  const phaseGot = sum(here.map((c) => c.output_tokens));
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
        {(sent !== null || got !== null) && (
          <span className="now-right">
            {developing && (phaseSent !== null || phaseGot !== null) && (
              <span className="now-sum">
                <span className="now-sum-label">{tx("This phase")}</span>
                <Tokens input={phaseSent} output={phaseGot} />
              </span>
            )}
            <span className="now-sum" title={tx("This development so far")}>
              <span className="now-sum-label">{tx("In total")}</span>
              <Tokens
                input={sent}
                output={got}
                cost={job.data.cost_usd ? job.data.cost_usd : null}
              />
            </span>
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
function Waiting({ call, label }: { call: InFlight; label?: string }) {
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
        <span>{label ?? tx("Waiting for the answer")}</span>
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
  const counted = call.input_tokens != null || call.output_tokens != null;
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
        <span className="now-right">
          {counted ? (
            <Tokens input={call.input_tokens} output={call.output_tokens} cost={call.cost_usd} />
          ) : call.unreported_attempts ? (
            // a call given up on was still written, and billed; no vendor says how much
            <span
              className="now-tokens unknown"
              title={tx("The call was given up on; it was billed, but no count came back.")}
            >
              {tx("tokens not reported")}
            </span>
          ) : null}
          <span className="now-time faint small" title={formatTime(call.at)}>
            {took && <span className="mono">{took} · </span>}
            {timeAgo(call.at)}
          </span>
        </span>
      </div>
      {call.summary && <p className="now-summary">{say(call.summary)}</p>}
      <div className="now-meta faint tiny mono">
        {[
          // the phase is the heading this card sits under
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

function NoteItem({ job, t }: { job: Job; t: Transition }) {
  const tx = useT();
  const say = useSay();
  const [open, setOpen] = useState(false);
  const detail = useEntryDetail(job, t, open);
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
      {hasDetail(t) && (
        <details className="now-output" onToggle={(e) => setOpen(e.currentTarget.open)}>
          <summary>{tx("Details")}</summary>
          {detail.loading ? (
            <Loading rows={1} />
          ) : (
            <pre>{detail.text.length > 4000 ? `${detail.text.slice(0, 4000)}…` : detail.text}</pre>
          )}
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

/** What went to the model and what came back, small enough for a card's corner: the
 *  rounded figures to read at a glance, the exact ones (and the price) under the pointer. */
function Tokens({
  input,
  output,
  cost,
}: {
  input?: number | null;
  output?: number | null;
  cost?: number | null;
}) {
  const tx = useT();
  const exact = new Intl.NumberFormat(currentLang());
  const title = [
    input != null ? tx("{n} tokens sent", { n: exact.format(input) }) : null,
    output != null ? tx("{n} tokens received", { n: exact.format(output) }) : null,
    cost != null ? usd(cost) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return (
    <span className="now-tokens mono" title={title}>
      <span className="now-tok in">
        <i aria-hidden="true">↑</i>
        {compact(input)}
      </span>
      <span className="now-tok out">
        <i aria-hidden="true">↓</i>
        {compact(output)}
      </span>
      {cost != null && <span className="now-cost">{usd(cost)}</span>}
    </span>
  );
}

/** 12431 -> "12.4k": the size of a prompt is read in thousands, not to the token. */
function compact(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${trim(n / 1000)}k`;
  return `${trim(n / 1_000_000)}M`;
}

function trim(x: number): string {
  return (x < 10 ? x.toFixed(1) : Math.round(x).toString()).replace(/\.0$/, "");
}

/** The sum of what is known; null when nothing is, so "no count" never reads as zero. */
function sum(values: (number | null | undefined)[]): number | null {
  const known = values.filter((v): v is number => v != null);
  return known.length ? known.reduce((a, b) => a + b, 0) : null;
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
