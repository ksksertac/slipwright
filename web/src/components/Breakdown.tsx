// The backlog as people read it: epics -> stories -> tasks, with the plan phase each task
// became when the Architect has already mapped it. Shared by the approval gates and by the
// history detail, so a backlog looks the same wherever it is shown.
import type { StackChoice } from "../api/client";
import { DomainBadge } from "./agents";
import { useSay } from "../i18n/said";

export interface BreakdownShape {
  epics: {
    id: string;
    title: string;
    description?: string;
    stories: {
      id: string;
      title: string;
      description?: string;
      tasks: { id: string; title: string; description?: string; phase?: number | null }[];
    }[];
  }[];
}

export interface PlanShape {
  summary?: string;
  /** One entry per part of the product: which language and framework (T11.5). */
  stack?: StackChoice[];
  decisions?: string[];
  phases: { goal: string; files?: string[]; domain?: string; task_id?: string | null }[];
  breakdown?: BreakdownShape;
}

export function BreakdownTree({ plan }: { plan: PlanShape }) {
  const say = useSay();
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
                                phase {task.phase}: {say(phase.goal)}{" "}
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
