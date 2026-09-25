// What a step actually produced, as a list you can read instead of a wall of prose: the
// backlog the Product Owner wrote and which issue each item became, the decisions the
// Architect settled on, the files a phase was supposed to touch against the ones it did,
// the cases you approved, the branch and pull request. Every group comes from the server
// already grouped; this file only lays it out.
//
// Labels arrive in English and are translated here, so the same list reads in whichever
// language the platform is set to. What the agents wrote -- a task title, a goal, a
// decision -- is shown as written, in the language the project asked them to write in.
import { useState } from "react";
import type { StepBadge, StepDetail, StepGroup, StepItem } from "../api/client";
import { useStepDetail } from "../api/hooks";
import { Detail } from "./Detail";
import { IconCheck, IconChevron } from "./icons";
import { Loading, timeAgo } from "./ui";
import { useT } from "../i18n";
import { isRetryNote, noteText, phaseOf } from "../i18n/notes";

const ITEM_CLASS: Record<StepItem["status"], string> = {
  todo: "idle",
  in_progress: "work",
  done: "ok",
  failed: "bad",
  skipped: "idle",
};

const ITEM_LABEL: Record<StepItem["status"], string> = {
  todo: "not started",
  in_progress: "in progress",
  done: "done",
  failed: "failed",
  skipped: "not touched",
};

/** The panel's body: the step's own account, then every list it produced. */
export function StepDetailView({ jobId, stepKey }: { jobId: string; stepKey: string }) {
  const detail = useStepDetail(jobId, stepKey);
  if (detail.isLoading) return <Loading rows={3} />;
  if (!detail.data) return null;
  const step = detail.data;
  return (
    <div className="step-detail">
      <StepNow step={step} />
      <StepTimes step={step} />
      {step.summary && <StepSummary text={step.summary} />}
      {step.groups.map((group) => (
        <Group key={group.key} group={group} />
      ))}
    </div>
  );
}

/** The supervisor's account is not prose: the engine writes its decision and the reasons
 * behind it into one note, the reasons joined with semicolons, and the panel used to print
 * the whole bracket as a paragraph -- an English verb, an opening bracket, and five
 * sentences running into each other. It is a decision and a list of why, so it is drawn as
 * one: the decision in the platform's language, the reasons underneath it, one per line. */
const DECISION = /^(asks you|re-plan|same specialist fixes|fix)\s*\(([\s\S]*)\)$/;

const DECISION_LABEL: Record<string, string> = {
  "asks you": "The supervisor stopped and left the decision to you",
  "re-plan": "The supervisor asked the Architect to plan it again",
  "same specialist fixes": "The supervisor sent it back to the same specialist",
  fix: "The supervisor sent it back to the same specialist",
};

function StepSummary({ text }: { text: string }) {
  const tx = useT();
  const match = DECISION.exec(text.trim());
  if (!match) return <p className="step-summary">{text}</p>;
  const reasons = match[2]!
    .split(/;\s+/)
    .map((reason) => reason.trim().replace(/[;,]$/, ""))
    .filter(Boolean);
  if (reasons.length === 0) return <p className="step-summary">{text}</p>;
  return (
    <div className="step-decision">
      <p className="step-decision-head">{tx(DECISION_LABEL[match[1]!] ?? match[1]!)}</p>
      <ul className="step-reasons">
        {reasons.map((reason, i) => (
          <li key={i}>
            <Ticked text={reason} />
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A reason names files and modules in backticks, the way the agents write them; they read
 * as code here rather than as stray punctuation. */
function Ticked({ text }: { text: string }) {
  const parts = text.split("`");
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? <code key={i}>{part}</code> : <span key={i}>{part}</span>,
      )}
    </>
  );
}

/** When it ran, how long it took, and -- at a gate -- when it was signed off and by whom.
 * "Ne zaman yapıldı, ne zaman onaylandı" is the first question a finished step gets. */
/** What a running step is on, and when it last moved.
 *
 * A step that is working writes as it goes, and the newest of those notes is usually the
 * least useful one: the engine says "asked again, smaller part (3/3)" far more often than
 * it says where the work got to, so the last line was nearly always a retry and the panel
 * answered "what is it doing" with "it is repeating itself". So the headline is the newest
 * note that is *not* a retry -- the phase and part the step is actually on -- and the
 * retrying is a second line underneath, which is where it belongs: it is the weather, not
 * the position.
 *
 * The time stays the deciding fact: a step whose last sign of life was two minutes ago is
 * running, one whose last sign was yesterday is stuck, and nobody should have to read a
 * history of thirty-eight lines to tell those apart.
 */
function StepNow({ step }: { step: StepDetail }) {
  const tx = useT();
  if (step.status !== "running") return null;
  const notes = step.groups
    .flatMap((group) => group.items)
    .flatMap((item) => [item, ...item.children])
    .filter((item) => item.at)
    .sort((a, b) => (a.at! < b.at! ? 1 : -1));
  const latest = notes[0];
  const doing = notes.find((item) => !isRetryNote(item.title)) ?? latest;
  // shown only when it is the *last* thing that happened: an old retry the run recovered
  // from is history, and history is what the list below is for
  const retrying = latest && isRetryNote(latest.title) ? latest : null;
  const phase = doing ? phaseOf(doing.title) : null;
  const since = latest?.at ?? step.started_at;
  return (
    <div className="step-now">
      <span className="pulse-dot" />
      <div style={{ minWidth: 0 }}>
        {phase && (
          <div className="step-now-where">
            {tx("phase {at} of {of}", { at: phase.at, of: phase.of })}
          </div>
        )}
        <div className="step-now-what">
          {doing ? noteText(tx, doing.title) : tx("Working on it")}
        </div>
        {retrying && <div className="step-now-retry">{noteText(tx, retrying.title)}</div>}
        {since && (
          <div className="step-now-when">
            {tx("last sign of life {ago}", { ago: timeAgo(since) })}
          </div>
        )}
      </div>
    </div>
  );
}

function StepTimes({ step }: { step: StepDetail }) {
  const tx = useT();
  const times: [string, string][] = [];
  if (step.started_at) times.push([tx("started"), timeAgo(step.started_at)]);
  if (step.finished_at) times.push([tx("finished"), timeAgo(step.finished_at)]);
  if (step.approved_at)
    times.push([
      tx("approved"),
      `${timeAgo(step.approved_at)} · ${step.approved_by === "supervisor" ? tx("by the supervisor") : tx("by you")}`,
    ]);
  if (times.length === 0) return null;
  return (
    <dl className="step-times">
      {times.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd title={value}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Group({ group }: { group: StepGroup }) {
  const tx = useT();
  return (
    <section className="step-group">
      <div className="step-group-head">
        <h4>{tx(group.label)}</h4>
        <span className="faint tiny">{group.items.length || ""}</span>
      </div>
      {group.note && <div className="muted small">{tx(group.note)}</div>}
      {group.items.length === 0 ? (
        <div className="step-empty">{tx(group.empty)}</div>
      ) : (
        <ul className="step-items">
          {foldRetries(group.items).map((item, i) => (
            <Item key={`${item.kind}-${i}-${item.title}`} item={item} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** A run of "asked the model again" notes becomes one line that opens onto them.
 *
 * The engine's record keeps every attempt, and it should: when a step went wrong, which
 * try it went wrong on is the whole question. But a reader looking at a *working* step is
 * counting the same sentence twenty times to find the four that say what was built, so the
 * run folds into a single line saying how many there were. Nothing is dropped -- the
 * originals are its children, one click away -- and a failed attempt is never folded, ever,
 * because a failure that hides inside a fold is a failure nobody reads.
 */
function foldRetries(items: StepItem[]): StepItem[] {
  const out: StepItem[] = [];
  let run: StepItem[] = [];
  const flush = () => {
    if (run.length > 1) {
      out.push({
        kind: "folded",
        title: "the model was asked again {n} times",
        detail: "",
        status: "skipped",
        at: run[run.length - 1]!.at,
        approved_at: null,
        badges: [],
        children: run,
      });
    } else {
      out.push(...run);
    }
    run = [];
  };
  for (const item of items) {
    if (item.kind === "event" && item.status !== "failed" && isRetryNote(item.title)) {
      run.push(item);
      continue;
    }
    flush();
    out.push(item);
  }
  flush();
  return out;
}

/** One line of a list. It unfolds when there is more underneath -- children, a long
 * description, a diff or a log -- and stays a single line when there is not, so a list of
 * twenty files does not become twenty accordions. */
function Item({ item }: { item: StepItem }) {
  const tx = useT();
  const [open, setOpen] = useState(false);
  const foldable = item.children.length > 0 || isLong(item.detail);
  const short = !foldable && item.detail;
  return (
    <li className={`step-item ${item.kind} ${item.status}`}>
      <div className="step-item-head">
        <button
          type="button"
          className={`step-item-line ${foldable ? "foldable" : ""}`}
          onClick={() => foldable && setOpen(!open)}
          aria-expanded={foldable ? open : undefined}
          disabled={!foldable}
        >
          {foldable && <IconChevron className={open ? "chev open" : "chev"} />}
          <StatusDot status={item.status} />
          <span className="step-item-title">{titleOf(tx, item)}</span>
          {short && <span className="step-item-value">{item.detail}</span>}
        </button>
        <span className="step-item-marks">
          {item.badges.map((badge, i) => (
            <BadgeChip key={i} badge={badge} />
          ))}
          {item.at && <span className="faint tiny">{timeAgo(item.at)}</span>}
        </span>
      </div>
      {open && (
        <div className="step-item-body">
          {isLong(item.detail) && <Detail text={item.detail} />}
          {item.children.length > 0 && (
            <ul className="step-items">
              {item.children.map((kid, i) => (
                <Item key={`${kid.kind}-${i}-${kid.title}`} item={kid} />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

/** An item's title is either a label this file translates, or -- for the engine's own
 * record -- a note, which reads back in the platform language through the same rules the
 * Activity tab uses. */
function titleOf(tx: ReturnType<typeof useT>, item: StepItem): string {
  if (item.kind === "folded") return tx(item.title, { n: item.children.length });
  return item.kind === "event" || item.kind === "jira" || item.kind === "decision"
    ? noteText(tx, item.title)
    : tx(item.title);
}

/** Short enough to sit on the line, or long enough to earn a fold. A diff or a log is
 * always long; a one-line description is not worth hiding. */
function isLong(detail: string): boolean {
  return detail.length > 90 || detail.includes("\n");
}

function StatusDot({ status }: { status: StepItem["status"] }) {
  const tx = useT();
  const label = tx(ITEM_LABEL[status]);
  return (
    <span className={`step-dot ${ITEM_CLASS[status]}`} title={label} aria-label={label}>
      {status === "done" ? <IconCheck /> : null}
    </span>
  );
}

function BadgeChip({ badge }: { badge: StepBadge }) {
  const tx = useT();
  const text = [badge.label ? tx(badge.label) : "", badge.value].filter(Boolean).join(" ");
  if (!text) return null;
  return <span className={`chip ${badge.tone}`}>{text}</span>;
}
