// Editors for what the human can change at a gate: the backlog tree, the plan (phase
// order, domains, task titles) and the test-case list. Each is a controlled component;
// the caller decides when to save. The shapes mirror the engine's dicts.
import { DOMAIN_LABEL } from "./agents";
import { IconPlus, IconTrash } from "./icons";
import { useT } from "../i18n";

export interface TaskShape {
  id: string;
  title: string;
  description?: string;
  phase?: number | null;
}
export interface StoryShape {
  id: string;
  title: string;
  description?: string;
  tasks: TaskShape[];
}
export interface EpicShape {
  id: string;
  title: string;
  description?: string;
  stories: StoryShape[];
}
export interface BreakdownShape {
  epics: EpicShape[];
}
export interface PhaseShape {
  goal: string;
  files?: string[];
  domain?: string;
  task_id?: string | null;
}
export interface PlanShape {
  summary?: string;
  decisions?: string[];
  phases: PhaseShape[];
  breakdown?: BreakdownShape;
}
export interface TestCaseShape {
  name: string;
  description: string;
}

const DOMAINS = Object.keys(DOMAIN_LABEL);

function newId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Rename epics, stories and tasks; add or remove tasks and stories. */
export function BacklogEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: BreakdownShape;
  onChange: (next: BreakdownShape) => void;
  disabled?: boolean;
}) {
  const tx = useT();
  const update = (fn: (draft: BreakdownShape) => void) => {
    const draft: BreakdownShape = JSON.parse(JSON.stringify(value)) as BreakdownShape;
    fn(draft);
    onChange(draft);
  };
  return (
    <ul className="tree editor">
      {value.epics.map((epic, ei) => (
        <li key={epic.id}>
          <div className="node">
            <span className="kind">epic</span>
            <input
              className="title"
              value={epic.title}
              disabled={disabled}
              onChange={(e) => update((d) => (d.epics[ei]!.title = e.target.value))}
            />
          </div>
          <ul className="tree">
            {epic.stories.map((story, si) => (
              <li key={story.id} className="depth-1">
                <div className="node">
                  <span className="kind">story</span>
                  <input
                    className="title"
                    value={story.title}
                    disabled={disabled}
                    onChange={(e) =>
                      update((d) => (d.epics[ei]!.stories[si]!.title = e.target.value))
                    }
                  />
                  <button
                    className="btn ghost icon small"
                    title={tx("Add task")}
                    disabled={disabled}
                    onClick={() =>
                      update((d) =>
                        d.epics[ei]!.stories[si]!.tasks.push({ id: newId("t"), title: "" }),
                      )
                    }
                  >
                    <IconPlus />
                  </button>
                </div>
                <ul className="tree">
                  {story.tasks.map((task, ti) => (
                    <li key={task.id} className="depth-2">
                      <div className="node">
                        <span className="kind">task</span>
                        <input
                          className="title"
                          value={task.title}
                          placeholder={tx("task title")}
                          disabled={disabled}
                          onChange={(e) =>
                            update(
                              (d) => (d.epics[ei]!.stories[si]!.tasks[ti]!.title = e.target.value),
                            )
                          }
                        />
                        <button
                          className="btn ghost icon small"
                          title={tx("Remove task")}
                          disabled={disabled || story.tasks.length === 1}
                          onClick={() =>
                            update((d) => d.epics[ei]!.stories[si]!.tasks.splice(ti, 1))
                          }
                        >
                          <IconTrash />
                        </button>
                      </div>
                      {task.description && (
                        <div className="muted small" style={{ marginLeft: 52 }}>
                          {task.description}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

/** Reorder phases, retag their domain, edit goals; rename the tasks they implement. */
export function PlanEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: PlanShape;
  onChange: (next: PlanShape) => void;
  disabled?: boolean;
}) {
  const tx = useT();
  const update = (fn: (draft: PlanShape) => void) => {
    const draft: PlanShape = JSON.parse(JSON.stringify(value)) as PlanShape;
    fn(draft);
    onChange(draft);
  };
  const tasks = new Map<string, TaskShape>();
  for (const epic of value.breakdown?.epics ?? []) {
    for (const story of epic.stories) {
      for (const task of story.tasks) tasks.set(task.id, task);
    }
  }
  const renameTask = (id: string, title: string) =>
    update((d) => {
      for (const epic of d.breakdown?.epics ?? []) {
        for (const story of epic.stories) {
          for (const task of story.tasks) if (task.id === id) task.title = title;
        }
      }
    });
  const move = (from: number, to: number) =>
    update((d) => {
      if (to < 0 || to >= d.phases.length) return;
      const [phase] = d.phases.splice(from, 1);
      d.phases.splice(to, 0, phase!);
    });

  return (
    <div className="stack" style={{ gap: 8 }}>
      {value.phases.map((phase, i) => {
        const task = phase.task_id ? tasks.get(phase.task_id) : undefined;
        return (
          <div key={`${phase.task_id ?? "p"}-${i}`} className="phase-row">
            <div className="phase-order">
              <span className="dot">{i + 1}</span>
              <button
                className="btn ghost icon small"
                title={tx("Move up")}
                disabled={disabled || i === 0}
                onClick={() => move(i, i - 1)}
              >
                ↑
              </button>
              <button
                className="btn ghost icon small"
                title={tx("Move down")}
                disabled={disabled || i === value.phases.length - 1}
                onClick={() => move(i, i + 1)}
              >
                ↓
              </button>
            </div>
            <div className="phase-fields">
              <div className="row">
                <select
                  value={phase.domain ?? "general"}
                  disabled={disabled}
                  onChange={(e) => update((d) => (d.phases[i]!.domain = e.target.value))}
                >
                  {DOMAINS.map((d) => (
                    <option key={d} value={d}>
                      {tx(DOMAIN_LABEL[d] ?? d)}
                    </option>
                  ))}
                </select>
                <input
                  value={phase.goal}
                  placeholder={tx("what this phase builds")}
                  disabled={disabled}
                  style={{ flex: 1 }}
                  onChange={(e) => update((d) => (d.phases[i]!.goal = e.target.value))}
                />
              </div>
              {task && (
                <div className="row">
                  <span className="kind">task</span>
                  <input
                    value={task.title}
                    disabled={disabled}
                    style={{ flex: 1 }}
                    onChange={(e) => renameTask(task.id, e.target.value)}
                  />
                </div>
              )}
              <input
                className="mono small"
                value={(phase.files ?? []).join(", ")}
                placeholder={tx("files, comma separated")}
                disabled={disabled}
                onChange={(e) =>
                  update(
                    (d) =>
                      (d.phases[i]!.files = e.target.value
                        .split(",")
                        .map((f) => f.trim())
                        .filter(Boolean)),
                  )
                }
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function TestCasesEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: TestCaseShape[];
  onChange: (next: TestCaseShape[]) => void;
  disabled?: boolean;
}) {
  const tx = useT();
  const set = (i: number, patch: Partial<TestCaseShape>) =>
    onChange(value.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <div className="stack" style={{ gap: 6 }}>
      {value.map((c, i) => (
        <div key={i} className="row" style={{ alignItems: "flex-start" }}>
          <input
            style={{ width: 200 }}
            value={c.name}
            placeholder="name"
            disabled={disabled}
            onChange={(e) => set(i, { name: e.target.value })}
          />
          <input
            style={{ flex: 1 }}
            value={c.description}
            placeholder={tx("what it checks")}
            disabled={disabled}
            onChange={(e) => set(i, { description: e.target.value })}
          />
          <button
            className="btn ghost icon small"
            title={tx("Remove")}
            disabled={disabled}
            onClick={() => onChange(value.filter((_, j) => j !== i))}
          >
            <IconTrash />
          </button>
        </div>
      ))}
      <div>
        <button
          className="btn small"
          disabled={disabled}
          onClick={() => onChange([...value, { name: "", description: "" }])}
        >
          <IconPlus /> {tx("Add case")}
        </button>
      </div>
    </div>
  );
}
