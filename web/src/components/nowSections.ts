// How the Right now feed is cut into runs -- one per phase, or per stage outside the
// phases. Kept apart from the component so it can be run on a development's real
// records without a page around it.
import type { Transition } from "../api/client";

/** One model call as the job logs it (engine.py ``_account``). Everything is optional:
 * the provider, the model and what it wrote were added to the log over time, and a call
 * made before then has none of them. */
export interface Call {
  role: string;
  provider?: string | null;
  model?: string | null;
  phase?: number | null;
  attempts?: number;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: number | null;
  /** attempts that timed out: generated and billed, with no count ever sent back */
  unreported_attempts?: number | null;
  ok: boolean;
  error?: string | null;
  /** the job's state when the call was made */
  state?: string | null;
  started_at?: string | null;
  summary?: string | null;
  output?: string | null;
  at: string;
}

export type Entry =
  { kind: "call"; at: string; call: Call } | { kind: "note"; at: string; t: Transition };

/** A run of the feed that belongs together: one phase, or one stage outside the phases. */
export type Section = { key: string; phase: number | null; stage: string; entries: Entry[] };

// the states a phase's own work happens in: a record from one of these that does not name
// its phase belongs to the phase being worked on
export const PHASE_STATES = new Set([
  "developing",
  "build_gate",
  "review",
  "awaiting_review_approval",
]);

export function stageOfState(state: string | null | undefined): string {
  switch (state) {
    case "created":
    case "backlog":
    case "awaiting_backlog_approval":
    case "architecture":
    case "awaiting_architecture_approval":
    case "design":
    case "awaiting_design_approval":
      return "plan";
    case "qa":
    case "awaiting_test_approval":
      return "test";
    case "devops":
    case "awaiting_deploy_approval":
    case "done":
      return "ship";
    default:
      return "build";
  }
}

export function sectionOf(phase: number | null, stage: string): Section {
  return { key: phase !== null ? `phase:${phase}` : `stage:${stage}`, phase, stage, entries: [] };
}

/** Which phase a record names: the call log says so, and a note says "phase 3" or
 *  "phase 3/8" in one of a few ways ("backend phase 3/8: ...", "build gate failed on phase
 *  3", "qa: phase 3: ...", "standards (mobile phase 3)"). */
function phaseOfEntry(e: Entry): number | null {
  if (e.kind === "call") return e.call.phase ?? null;
  const m = /\bphase (\d+)\b/.exec(e.t.note ?? "");
  return m ? Number(m[1]) : null;
}

/** Cut the records, oldest first, into runs: a record naming a phase joins that phase; one
 *  that does not, made while a phase was at work, joins the phase it came in; anything else
 *  joins its stage. Something that ends a run (a failure, a stop) stays where it happened. */
export function cut(entries: Entry[]): Section[] {
  const out: Section[] = [];
  for (const e of entries) {
    const current = out[out.length - 1];
    const state = e.kind === "call" ? e.call.state : e.t.to_state;
    let phase = phaseOfEntry(e);
    if (phase === null && current?.phase != null && (!state || PHASE_STATES.has(state)))
      phase = current.phase;
    const stage =
      phase !== null
        ? "build"
        : state && stageOfState(state) !== "build"
          ? stageOfState(state)
          : (current?.stage ?? "plan");
    // a failure, a stop or a question to the person carries no stage of its own: it stays
    // with the run it ended
    const ends = !!state && !PHASE_STATES.has(state) && stageOfState(state) === "build";
    const next = ends && current ? current : sectionOf(phase, stage);
    if (!current || current.key !== next.key) out.push(next);
    out[out.length - 1]!.entries.push(e);
  }
  return out;
}
