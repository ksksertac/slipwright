// The feed's notes are the engine's own words: "qa: 12 test cases proposed", "review
// phase 2/7: 3 violation(s), 1 blocking, 2 advisory", "backend phase 1/7, fix attempt 2:
// ... (4 files)". They are written once, in English, by the code that emits them -- so
// unlike an agent's prose they are a closed set, and the Activity tab can read them back
// in the platform's language: a pattern recognises the note, the numbers, names and the
// model's own sentence inside it are kept as they are, and only the scaffolding around
// them is rewritten -- plainly, and without the role prefix the badge beside it already
// shows. A note no rule matches is shown exactly as it came; nothing is ever swallowed.
import type { JobState } from "../api/client";
import { ROLE_LABEL } from "../components/agents";
import { STATE_LABEL } from "../components/ui";
import type { T } from "../i18n";

type Rule = {
  /** the note as the engine writes it; capture groups become {1}, {2}, ... */
  re: RegExp;
  /** what a person reads, in English; tr.ts carries the other language */
  out: string;
  /** groups holding a role name ("devops"), a job state ("build_gate"), an error kind */
  roles?: number[];
  states?: number[];
  kinds?: number[];
  /** groups that are themselves a note (a gate note with the supervisor's word after it) */
  notes?: number[];
  /** groups holding a ", "-joined list of notes ("4 done, 1 queued") */
  lists?: number[];
  /** groups the *agent* wrote, not the engine: they go through `say` (i18n/said.tsx),
   *  which is the same text slipwright/translate.py lifted out and had translated */
  prose?: number[];
};

/** Why an invocation ended badly, as `InvokeErrorKind` spells it. */
const ERROR_LABEL: Record<string, string> = {
  timeout: "timed out",
  provider_error: "provider error",
  provider_unavailable: "provider unavailable",
  provider_rejected: "the provider refused the account",
  refused: "refused by the model",
  malformed_output: "unusable answer",
  budget: "budget spent",
  loop: "went in circles",
  truncated: "answer cut off",
};

const RULES: Rule[] = [
  // -- what a person did at a gate -------------------------------------------------------
  { re: /^job started$/, out: "Development started" },
  {
    re: /^(approved[^:]*) by (.+?): continue with (\w+)$/,
    out: "{1}, by {2}; continues with {3}",
    notes: [1, 2],
    states: [3],
  },
  {
    re: /^(approved[^:]*): continue with (\w+)$/,
    out: "{1}; continues with {2}",
    notes: [1],
    states: [2],
  },
  { re: /^(approved[^:]*) by (.+)$/, out: "{1}, by {2}", notes: [1, 2] },
  // the supervisor signs its own approvals with the confidence it had
  {
    re: /^supervisor \(confidence ([\d.]+)\): (.*)$/,
    out: "Supervisor (confidence {1}): {2}",
  },
  { re: /^approved$/, out: "Approved" },
  { re: /^approved (\d+) test cases$/, out: "{1} test cases approved" },
  { re: /^approved phase (\d+) despite the review$/, out: "Phase {1} approved despite the review" },
  { re: /^rejected: (.*)$/, out: "Sent back: {1}" },
  { re: /^undo: (.*)$/, out: "Taken back: {1}" },
  // `rerun` takes a step name, not a state: only these two exist
  { re: /^re-run by hand: tests$/, out: "Tests re-run by hand" },
  { re: /^re-run by hand: devops$/, out: "DevOps step re-run by hand" },
  { re: /^retried: continuing with (\w+)$/, out: "Retried, continuing from {1}", states: [1] },
  {
    re: /^retried: continuing with (\w+) \((.*)\)$/,
    out: "Retried, continuing from {1} ({2})",
    states: [1],
  },
  { re: /^tests re-run by hand: passed$/, out: "Tests re-run by hand: passed" },

  // -- the roles' own work ---------------------------------------------------------------
  {
    re: /^po: backlog ready — (\d+) epics, (\d+) stories, (\d+) tasks$/,
    out: "Backlog ready: {1} epics, {2} stories, {3} tasks",
  },
  {
    re: /^architect: plan ready — (\d+) phases, (\d+) decisions$/,
    out: "Plan ready: {1} phases, {2} decisions",
  },
  {
    re: /^\w+ phase (\d+)\/(\d+), fix attempt (\d+): (.*) \((\d+) files(?: in \d+ parts)?\)$/,
    out: "Phase {1}/{2}, build fix {3}: {4} ({5} files)",
    prose: [4],
  },
  {
    re: /^\w+ phase (\d+)\/(\d+), review fix (\d+): (.*) \((\d+) files(?: in \d+ parts)?\)$/,
    out: "Phase {1}/{2}, review fix {3}: {4} ({5} files)",
    prose: [4],
  },
  {
    re: /^\w+ phase (\d+)\/(\d+) part (\d+): (.*) \((\d+) files, more to come\)$/,
    out: "Phase {1}/{2}, part {3}: {4} ({5} files so far)",
    prose: [4],
  },
  {
    re: /^\w+ phase (\d+)\/(\d+): (.*) \((\d+) files in (\d+) parts\)$/,
    out: "Phase {1}/{2} built in {5} parts: {3} ({4} files)",
    prose: [3],
  },
  {
    re: /^\w+ phase (\d+)\/(\d+): (.*) \((\d+) files\)$/,
    out: "Phase {1}/{2} built: {3} ({4} files)",
    prose: [3],
  },

  // -- the build gate, and what the supervisor said about a failed one --------------------
  { re: /^build gate passed for phase (\d+)\/(\d+)$/, out: "Build gate passed — phase {1}/{2}" },
  { re: /^build gate, phase (\d+)$/, out: "Build gate — phase {1}" },
  {
    re: /^build gate failed on phase (\d+) \(attempt (\d+)\/(\d+)\)$/,
    out: "Build gate failed — phase {1} (attempt {2}/{3})",
  },
  {
    re: /^build gate failed (\d+) times on phase (\d+)$/,
    out: "Build gate failed {1} times on phase {2} — giving up",
  },

  // -- what the tester said about a failed gate before anyone fixed code -----------------
  {
    re: /^qa: phase (\d+): the test was wrong, corrected \((\d+) files\) — (.*)$/,
    out: "The test was wrong, not the code — phase {1}, corrected ({2} files): {3}",
    prose: [3],
  },
  {
    re: /^qa: phase (\d+): the code is wrong, not the test — (.*)$/,
    out: "The code is wrong, not the test — phase {1}: {2}",
    prose: [2],
  },
  {
    re: /^qa: phase (\d+): test fix refused, it changed (.*) — not a test file$/,
    out: "Test fix refused — it changed {2}, which is not a test",
  },
  {
    re: /^qa: phase (\d+): called the test wrong but sent no correction$/,
    out: "Called the test wrong but sent no correction",
  },
  {
    re: /^qa: phase (\d+): test fix not written \((.*)\)$/,
    out: "Test fix not written ({2})",
  },
  {
    re: /^(.*); supervisor: re-plan \((.*)\)$/,
    out: "{1}; Supervisor: re-plan ({2})",
    notes: [1],
    prose: [2],
  },
  {
    re: /^(.*); supervisor: asks you \((.*)\)$/,
    out: "{1}; Supervisor: asks you ({2})",
    notes: [1],
    prose: [2],
  },
  {
    re: /^(.*); supervisor: same specialist fixes \((.*)\)$/,
    out: "{1}; Supervisor: the same specialist fixes it ({2})",
    notes: [1],
    prose: [2],
  },
  {
    re: /^supervisor: recommends (\w+) \(confidence ([\d.]+), risk (\w+)\)$/,
    out: "Supervisor recommends {1} (confidence {2}, risk {3})",
  },
  {
    re: /^(supervisor: recommends .*); waits for you: (.*)$/,
    out: "{1}; waits for you: {2}",
    notes: [1],
    prose: [2],
  },
  {
    re: /^supervisor failed: (\w+); the gate waits for you$/,
    out: "Supervisor failed ({1}) — the gate waits for you",
    kinds: [1],
  },
  { re: /^supervisor: (\w+) \((.*)\)$/, out: "Supervisor: {1} ({2})", prose: [2] },

  // -- the standards review --------------------------------------------------------------
  { re: /^review phase (\d+)\/(\d+): (.*)$/, out: "Review of phase {1}/{2}: {3}", notes: [3] },
  { re: /^clean$/, out: "nothing to fix" },
  {
    re: /^(\d+) violation\(s\), (\d+) blocking, (\d+) advisory$/,
    out: "{1} findings, {2} blocking, {3} advisory",
  },
  { re: /^(.*); fix round (\d+)\/(\d+)$/, out: "{1} — fix round {2}/{3}", notes: [1] },
  {
    re: /^(.*) after (\d+) fix round\(s\); needs your decision$/,
    out: "{1}, after {2} fix rounds — needs your decision",
    notes: [1],
  },

  // -- QA --------------------------------------------------------------------------------
  { re: /^qa: (\d+) test cases proposed$/, out: "{1} test cases proposed" },
  {
    re: /^qa: no test cases in the answer; asking again for the list$/,
    out: "No test cases came back — asking again",
  },
  {
    re: /^qa: tests written and green \((\d+) files\) — (.*)$/,
    out: "Tests written and passing ({1} files): {2}",
    prose: [2],
  },

  // -- Jira and the standards library ----------------------------------------------------
  { re: /^jira \(retry\): (.*)$/, out: "Jira, second try: {1}", lists: [1] },
  { re: /^jira \(\w+\): (.*)$/, out: "Jira: {1}", lists: [1] },
  { re: /^jira: (\d+) update\(s\)$/, out: "Jira: {1} updates" },
  { re: /^jira: sync failed, will retry$/, out: "Jira could not be reached — will retry" },
  { re: /^(\d+) done$/, out: "{1} written" },
  { re: /^(\d+) refused$/, out: "{1} refused" },
  { re: /^(\d+) queued$/, out: "{1} queued" },
  { re: /^(\d+) skipped$/, out: "{1} unchanged" },
  {
    re: /^standards \(\w+ phase (\d+)\): (\d+) section\(s\)$/,
    out: "Standards read for phase {1}: {2} sections",
  },
  { re: /^standards \(\w+\): (\d+) section\(s\)$/, out: "Standards read: {1} sections" },
  {
    re: /^inbox: (\d+) message\(s\) consumed by (\w+)$/,
    out: "{1} messages from you went to {2}",
    roles: [2],
  },

  // -- retries and failures --------------------------------------------------------------
  {
    re: /^\w+ attempt (\d+) failed: (\w+); retrying in ([\d.]+)s \((\d+)\/(\d+) retries used\)$/,
    out: "Attempt {1} failed ({2}) — trying again in {3}s, {4} of {5} retries used",
    kinds: [2],
  },
  {
    re: /^\w+ attempt (\d+): (.*); asking for a smaller part \((\d+)\/(\d+)\)$/,
    out: "Attempt {1} hit the answer limit — asking for a smaller part ({3}/{4})",
  },
  {
    re: /^(\w+) failed: (\w+) after (\d+) attempts$/,
    out: "{1} gave up after {3} attempts: {2}",
    roles: [1],
    kinds: [2],
  },
  { re: /^(\w+) failed: (\w+)$/, out: "{1} failed: {2}", roles: [1], kinds: [2] },
  { re: /^(\w+) crashed: (.*)$/, out: "{1} crashed: {2}", roles: [1] },
  { re: /^loop detected: (.*)$/, out: "Went in circles: {1}" },
  { re: /^devops: (.*)$/, out: "DevOps could not finish: {1}" },
  { re: /^CI still pending after (\d+)s$/, out: "CI was still running after {1}s" },
  { re: /^CI red after (\d+) fix attempts$/, out: "CI still red after {1} fix attempts" },

  // -- how a development ends ------------------------------------------------------------
  { re: /^PR (\S+) \((\w+)\)$/, out: "Pull request {1} ({2})" },
  {
    re: /^nothing was pushed: the checkout (.*) has no remote\. Branch (\S+) is ready there — merge it with `git merge \S+`, or set the project's GitHub repository so the next development pushes and opens a pull request$/,
    out: "Nothing was pushed: the checkout {1} has no remote. The branch {2} is ready there — merge it with `git merge {2}`, or give the project a GitHub repository so the next development pushes and opens a pull request.",
  },
];

/** A note that says the model was asked again -- a retry after a provider error, a smaller
 * part after an answer ran past the limit. Each one is true, and none of them is what the
 * step is *on*: a run of twenty buries the four lines that say where the work got to. The
 * panel folds them in the list and skips them when it names what is happening now. */
export function isRetryNote(note: string): boolean {
  const text = note.trim();
  return RETRIES.some((re) => re.test(text));
}

const RETRIES: RegExp[] = [
  /^\w+ attempt \d+: .*; asking for a smaller part \(\d+\/\d+\)$/,
  /^\w+ attempt \d+ failed: \w+; retrying in [\d.]+s \(\d+\/\d+ retries used\)$/,
];

/** Which phase of how many a note is about, when it says. Every phase note carries it the
 * same way -- "backend phase 2/6 part 1: ..." -- so one pattern reads them all. */
export function phaseOf(note: string): { at: number; of: number } | null {
  const m = /\bphase (\d+)\/(\d+)\b/.exec(note.trim());
  if (!m) return null;
  return { at: Number(m[1]), of: Number(m[2]) };
}

/** The note, in the platform's language. Unknown notes come back untouched.
 *
 * `say` is the bridge to what the agents wrote (i18n/said.tsx): the engine's scaffolding
 * is rewritten from the rules here, while the model's own sentence inside it is looked up.
 * Left out, the agent's words are shown as they were written. */
export function noteText(tx: T, note: string, say?: (text: string) => string): string {
  const text = note.trim();
  for (const rule of RULES) {
    const m = rule.re.exec(text);
    if (!m) continue;
    const vars: Record<string, string> = {};
    for (let i = 1; i < m.length; i++) {
      let v = m[i] ?? "";
      if (rule.roles?.includes(i)) v = tx(ROLE_LABEL[v] ?? v);
      else if (rule.states?.includes(i)) v = tx(STATE_LABEL[v as JobState] ?? v);
      else if (rule.kinds?.includes(i)) v = tx(ERROR_LABEL[v] ?? v);
      else if (rule.notes?.includes(i)) v = noteText(tx, v, say);
      else if (rule.prose?.includes(i)) v = say ? say(v) : v;
      else if (rule.lists?.includes(i))
        v = v
          .split(", ")
          .map((part) => noteText(tx, part, say))
          .join(", ");
      vars[String(i)] = v;
    }
    return tx(rule.out, vars);
  }
  return text;
}
