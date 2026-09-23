// What a development will do, before it does any of it: one group per agent, in the order
// the work happens, down to QA and DevOps. The wording of a task or a phase is edited here
// and saved through the editors that already exist; the list is the job itself, so closing
// the tab — or the whole application — loses nothing.
import { useEffect, useState } from "react";
import {
  describeError,
  type Job,
  type PlanEdit,
  type WorkGroup,
  type WorkList as List,
} from "../api/client";
import { useApprove, useReject, useSetBacklog, useSetPlan, useWorkList } from "../api/hooks";
import { AgentIcon } from "./agents";
import { IconCheck, IconPlay, IconX } from "./icons";
import { ErrorBox, Loading } from "./ui";
import { useT } from "../i18n";

type Edits = Record<string, string>;

export function WorkListPanel({ job, onStarted }: { job: Job; onStarted?: () => void }) {
  const tx = useT();
  const list = useWorkList(job.id);
  const approve = useApprove(job.id);
  const reject = useReject(job.id);
  const setBacklog = useSetBacklog(job.id);
  const setPlan = useSetPlan(job.id);
  const [edits, setEdits] = useState<Edits>({});
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setEdits({}), [job.id]);

  if (list.isLoading) return <Loading rows={4} />;
  if (list.error) return <ErrorBox error={list.error} />;
  const data = list.data!;
  const dirty = Object.keys(edits).length > 0;

  const save = async (): Promise<boolean> => {
    setError(null);
    try {
      const backlog = applyBacklog(job, edits);
      if (backlog) await setBacklog.mutateAsync(backlog);
      const plan = applyPlan(job, edits);
      if (plan) await setPlan.mutateAsync(plan);
      setEdits({});
      await list.refetch();
      return true;
    } catch (err) {
      setError(describeError(err));
      return false;
    }
  };

  const start = async () => {
    if (dirty && !(await save())) return;
    approve.mutate(undefined, { onSuccess: () => onStarted?.() });
  };

  return (
    <div className="worklist">
      <div className="row spread worklist-head">
        <div style={{ minWidth: 0 }}>
          <strong>{tx("What the agents will do")}</strong>
          <div className="muted small">
            {tx("{tasks} task(s) in {phases} phase(s) — reword anything before it starts.", {
              tasks: data.tasks,
              phases: data.phases,
            })}
          </div>
        </div>
        <span className="badge wait">{tx("waiting for you")}</span>
      </div>
      {data.plan_summary && <p className="muted small worklist-summary">{data.plan_summary}</p>}

      <ol className="worklist-groups">
        {data.groups.map((group, i) => (
          <Group
            key={`${group.role}-${i}`}
            group={group}
            index={i + 1}
            edits={edits}
            onEdit={(id, value) => setEdits({ ...edits, [id]: value })}
            editable={data.editable}
          />
        ))}
      </ol>

      {error && <div className="callout error">{error}</div>}
      {approve.error && <div className="callout error">{describeError(approve.error)}</div>}
      {data.editable && (
        <div className="row worklist-actions">
          <button
            className="btn primary"
            disabled={approve.isPending || setBacklog.isPending || setPlan.isPending}
            onClick={() => void start()}
          >
            <IconPlay /> {approve.isPending ? tx("Starting…") : tx("Everything is fine — start")}
          </button>
          {dirty && (
            <button className="btn" onClick={() => void save()}>
              <IconCheck /> {tx("Save the wording")}
            </button>
          )}
          {feedback === null ? (
            <button className="btn bad" onClick={() => setFeedback("")}>
              <IconX /> {tx("Have it written again…")}
            </button>
          ) : null}
        </div>
      )}
      {feedback !== null && (
        <div className="card worklist-reject">
          <label htmlFor="worklist-feedback">{tx("What should change?")}</label>
          <textarea
            id="worklist-feedback"
            value={feedback}
            autoFocus
            onChange={(e) => setFeedback(e.target.value)}
          />
          <div className="row">
            <button
              className="btn bad"
              disabled={!feedback.trim() || reject.isPending}
              onClick={() => reject.mutate(feedback.trim(), { onSuccess: () => setFeedback(null) })}
            >
              {tx("Send")}
            </button>
            <button className="btn ghost" onClick={() => setFeedback(null)}>
              {tx("Cancel")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Group({
  group,
  index,
  edits,
  onEdit,
  editable,
}: {
  group: WorkGroup;
  index: number;
  edits: Edits;
  onEdit: (id: string, value: string) => void;
  editable: boolean;
}) {
  const tx = useT();
  return (
    <li className="worklist-group">
      <div className="worklist-group-head">
        <span className="worklist-n">{index}</span>
        <span className="worklist-agent">
          <AgentIcon role={group.role} />
          <span>
            <strong>{tx(group.label)}</strong>
            <span className="muted small">{tx(group.summary)}</span>
          </span>
        </span>
        <span className="faint tiny">{tx("{n} item(s)", { n: group.items.length })}</span>
      </div>
      <ul className="worklist-items">
        {group.items.map((item) => (
          <li key={item.id} className={item.editable ? "" : "fixed"}>
            <span className="worklist-line">
              {item.phase !== null && item.phase !== undefined && item.kind === "phase" && (
                <span className="chip">{tx("phase {n}", { n: item.phase })}</span>
              )}
              {editable && item.editable ? (
                <input
                  type="text"
                  value={edits[item.id] ?? item.title}
                  onChange={(e) => onEdit(item.id, e.target.value)}
                />
              ) : (
                <span className="title">{item.kind === "step" ? tx(item.title) : item.title}</span>
              )}
              {item.domain && <span className="tag">{tx(item.domain)}</span>}
            </span>
            {item.detail && <span className="faint tiny detail">{item.detail}</span>}
          </li>
        ))}
      </ul>
    </li>
  );
}

/** The backlog with the edited wording in it, or null when nothing in it changed. */
function applyBacklog(job: Job, edits: Edits): Record<string, unknown> | null {
  const backlog = job.data.backlog as
    { epics: { stories: { tasks: { id: string; title: string }[] }[] }[] } | null | undefined;
  if (!backlog?.epics) return null;
  let touched = false;
  const epics = backlog.epics.map((epic) => ({
    ...epic,
    stories: epic.stories.map((story) => ({
      ...story,
      tasks: story.tasks.map((task) => {
        const next = edits[task.id];
        if (next === undefined || next === task.title) return task;
        touched = true;
        return { ...task, title: next };
      }),
    })),
  }));
  return touched ? { ...backlog, epics } : null;
}

/** The plan with the edited phase titles in it, or null when no phase changed. */
function applyPlan(job: Job, edits: Edits): PlanEdit | null {
  const plan = job.data.plan as { phases?: { title?: string }[] } | null | undefined;
  if (!plan?.phases) return null;
  let touched = false;
  const phases = plan.phases.map((phase, i) => {
    const next = edits[`phase:${i}`];
    if (next === undefined || next === phase.title) return phase;
    touched = true;
    return { ...phase, title: next };
  });
  return touched ? ({ ...plan, phases } as PlanEdit) : null;
}

export type { List };
