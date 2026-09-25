// The four stages every development goes through, and how a list of step cards is cut
// into them. Two pages draw the same four stages -- the project's pipeline lane and a
// development's own page -- so the names, the grouping, the colour and the icon live here
// rather than being written twice and drifting apart.
//
// A stage wears the colour and the icon of the agent whose work it is: the first of its
// steps that has a role, which is also the first one you read.
import type { ComponentType } from "react";
import type { StepCard } from "../api/client";
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
  return steps.find((s) => s.role)?.role ?? undefined;
}

export function stageStatus(steps: StepCard[]): string {
  if (steps.some((s) => s.status === "waiting")) return "waiting";
  if (steps.some((s) => s.status === "failed")) return "failed";
  if (steps.some((s) => s.status === "running")) return "running";
  return steps.every((s) => s.status === "done") ? "done" : "pending";
}
