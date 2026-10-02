// The backlog as people read it: epics -> stories -> tasks, with the plan phase each task
// became when the Architect has already mapped it. Shared by the approval gates and by the
// history detail, so a backlog looks the same wherever it is shown.
import type { StackChoice } from "../api/client";
import { DomainBadge } from "./agents";
import { Sources, type SourceRef } from "./Attachments";
import { useSay } from "../i18n/said";
import { useT } from "../i18n";
import { phaseName } from "./stages";

export interface BreakdownShape {
  epics: {
    id: string;
    title: string;
    description?: string;
    stories: {
      id: string;
      title: string;
      description?: string;
      /** the attached files it was drawn from */
      sources?: SourceRef[];
      tasks: { id: string; title: string; description?: string; phase?: number | null }[];
    }[];
  }[];
}

export interface PlanShape {
  summary?: string;
  /** One entry per part of the product: which language and framework (T11.5). */
  stack?: StackChoice[];
  decisions?: string[];
  phases: {
    goal: string;
    files?: string[];
    domain?: string;
    task_id?: string | null;
    depends_on?: number[] | null;
  }[];
  breakdown?: BreakdownShape;
}

/**
 * How a plan runs, read off its `depends_on` (T16.2): the steps it takes when every phase
 * that can start does, and the most phases at any one of them. A phase that does not say
 * what it needs waits for every earlier one, as it always did. Shown before the plan is
 * approved, so a plan that is one long chain is seen to be one.
 */
export function planWidth(plan: PlanShape): { steps: number; widest: number } {
  const step: number[] = [];
  plan.phases.forEach((p, i) => {
    const needs = p.depends_on ?? Array.from({ length: i }, (_, k) => k + 1);
    step.push(1 + Math.max(0, ...needs.map((d) => step[d - 1] ?? 0)));
  });
  const counts = new Map<number, number>();
  for (const s of step) counts.set(s, (counts.get(s) ?? 0) + 1);
  return { steps: counts.size, widest: Math.max(0, ...counts.values()) };
}

export function BreakdownTree({
  plan,
  projectId,
  jobId,
}: {
  plan: PlanShape;
  /** where the files a story came from are looked up; without it they are only named */
  projectId?: string | null;
  jobId?: string;
}) {
  const say = useSay();
  const tx = useT();
  if (!plan.breakdown) {
    return (
      <ol>
        {plan.phases.map((p, i) => (
          <li key={i}>
            {say(p.goal)}{" "}
            {p.files && p.files.length > 0 && (
              <span className="muted small mono">— {p.files.join(", ")}</span>
            )}
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ul className="tree">
      {plan.breakdown.epics.map((epic) => (
        <li key={epic.id}>
          <div className="node">
            <span className="kind">epic</span>
            <span className="title">
              <strong>{say(epic.title)}</strong>
              {epic.description && <div className="muted small">{say(epic.description)}</div>}
            </span>
          </div>
          <ul className="tree">
            {epic.stories.map((story) => (
              <li key={story.id} className="depth-1">
                <div className="node">
                  <span className="kind">story</span>
                  <span className="title">
                    {say(story.title)}
                    {story.description && (
                      <div className="muted small">{say(story.description)}</div>
                    )}
                    <Sources sources={story.sources} projectId={projectId} jobId={jobId} />
                  </span>
                </div>
                <ul className="tree">
                  {story.tasks.map((task) => {
                    const phase = task.phase ? plan.phases[task.phase - 1] : undefined;
                    return (
                      <li key={task.id} className="depth-2">
                        <div className="node">
                          <span className="kind">task</span>
                          <span className="title">
                            {say(task.title)}
                            {task.description && (
                              <div className="muted small">{say(task.description)}</div>
                            )}
                            {phase && (
                              <div className="muted small">
                                {phaseName(tx, task.phase!, plan.phases.length)} · {say(phase.goal)}{" "}
                                <DomainBadge domain={phase.domain} />
                                {phase.files && phase.files.length > 0 && (
                                  <span className="mono"> — {phase.files.join(", ")}</span>
                                )}
                              </div>
                            )}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
