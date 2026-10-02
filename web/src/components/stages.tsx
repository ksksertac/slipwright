// The four stages every development goes through, and how a list of step cards is cut
// into them. Two pages draw the same four stages -- the project's pipeline lane and a
// development's own page -- so the names, the grouping, the colour and the icon live here
// rather than being written twice and drifting apart.
//
// A stage wears the colour and the icon of the agent whose work it is: the first of its
// steps that has a role, which is also the first one you read.
import type { ComponentType } from "react";
import type { StepCard } from "../api/client";
import type { T } from "../i18n";
import { IconCpu, IconFlask, IconGit, IconLayers } from "./icons";

export type Stage = { key: string; steps: StepCard[] };

export const STAGE_LABEL: Record<string, string> = {
  plan: "Planning",
  build: "Building",
  test: "Testing",
  ship: "Delivery",
};

/** What each stage is for, in one line under its name. */
export const STAGE_NOTE: Record<string, string> = {
  plan: "What to build, and how it will be built and tested",
  build: "One phase per task, each behind the build gate",
  test: "The cases you approve, then the tests that cover them",
  ship: "The branch, the pull request and its checks",
};

/** The fallback icon, for a stage whose steps carry no role at all. */
export const STAGE_ICON: Record<string, ComponentType<{ className?: string }>> = {
  plan: IconLayers,
  build: IconCpu,
  test: IconFlask,
  ship: IconGit,
};

function stageOf(step: StepCard): string | null {
  switch (step.key.split(":")[0]) {
    case "backlog":
    case "backlog_gate":
    case "architecture":
    case "architecture_gate":
    case "design":
      return "plan";
    case "develop":
    case "phase":
    case "review_gate":
    // the Architect reading what people did by hand while it was paused, and its gate:
    // they decide which phases are left, so they sit with the phases
    case "reconcile":
    case "reconcile_gate":
      return "build";
    case "qa":
    case "test_gate":
      return "test";
    case "devops":
    case "done":
      return "ship";
    default:
      return null;
  }
}

/** Group the cards into stages in order. A card whose key is not one of the fixed ones
 * (the decision gate, inserted wherever it interrupted) stays in the stage it fell into. */
export function stages(steps: StepCard[]): Stage[] {
  const out: Stage[] = [];
  let current = "plan";
  for (const step of steps) {
    current = stageOf(step) ?? current;
    if (out.length === 0 || out[out.length - 1]!.key !== current)
      out.push({ key: current, steps: [] });
    out[out.length - 1]!.steps.push(step);
  }
  return out;
}

/** The agent a stage belongs to: the first of its steps that has one. */
export function stageAgent(steps: StepCard[]): string | undefined {
  // the Architect's reading of work done by hand can open the build stage; the stage is
  // still the specialists'
  return steps.find((s) => s.role && s.key !== "reconcile")?.role ?? undefined;
}

// -- how a phase is named -----------------------------------------------------------------
//
// One way, everywhere: "Phase 4 of 8" ("Faz 4/8"). A count of finished steps is written
// differently ("3/8 done"), because the two side by side -- a stage reading 3/8 while the
// card under it said phase 4 -- looked like two answers to one question.

/** "Phase 4 of 8", or "Phase 4" where the total is not known. */
export function phaseName(tx: T, n: number, total?: number | null): string {
  return total ? tx("Phase {i} of {n}", { i: n, n: total }) : tx("Phase {n}", { n });
}

/** How many phases the plan behind these cards has. */
export function phaseTotal(steps: StepCard[]): number {
  return steps.filter((s) => s.key.startsWith("phase:")).length;
}

/** A phase card's title: its goal alone. The server writes "<agent>: <goal>", and the agent
 *  is already the card's header -- in the title it pushed the goal off the end. */
export function phaseGoal(step: StepCard): string {
  const m = /^[^:]+: (.*)$/s.exec(step.label);
  return (m ? m[1]! : step.label).trim();
}

/** What a stage's corner says: the phase being worked on while the build stage is under
 *  way, otherwise how many of its steps are done -- written as a count, not as a phase. */
export function stageCount(tx: T, stage: Stage): string {
  const phases = stage.steps.filter((s) => s.key.startsWith("phase:"));
  const running = phases.find(
    (s) => s.status === "running" || s.status === "failed" || s.status === "paused",
  );
  if (running?.phase) return phaseName(tx, running.phase, phases.length);
  const { done, total } = stageTally(stage);
  return tx("{done}/{total} done", { done, total });
}

/** Done out of all, for the bar: a build stage counts its phases, not the review gates
 *  between them, so the bar and the phase it names agree. */
export function stageTally(stage: Stage): { done: number; total: number } {
  const phases = stage.steps.filter((s) => s.key.startsWith("phase:"));
  const counted = phases.length ? phases : stage.steps;
  const done = counted.filter((s) => s.status === "done" || s.status === "skipped").length;
  return { done, total: counted.length };
}

export function stageStatus(steps: StepCard[]): string {
  if (steps.some((s) => s.status === "waiting")) return "waiting";
  if (steps.some((s) => s.status === "failed")) return "failed";
  if (steps.some((s) => s.status === "running")) return "running";
  if (steps.some((s) => s.status === "paused")) return "paused";
  // a step that was deliberately passed over is settled, not outstanding: a stage whose
  // tests were skipped is finished with, and must not sit at "pending" for ever
  return steps.every((s) => s.status === "done" || s.status === "skipped") ? "done" : "pending";
}
