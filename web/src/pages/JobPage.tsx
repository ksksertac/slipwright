import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  describeError,
  type Job,
  type JobState,
  type Profile,
  type Transition,
} from "../api/client";
import { useNavigate } from "react-router-dom";
import {
  keys,
  useDeleteJob,
  useJob,
  useProject,
  useSendMessage,
  useSetTestCases,
} from "../api/hooks";
import { api } from "../api/client";
import { ActivityRow } from "../components/ActivityRow";
import { Crumbs } from "../components/Crumbs";
import { Detail } from "../components/Detail";
import { Diff } from "../components/Diff";
import { GateActions, pendingApproval } from "../components/GateActions";
import { IconCheck, IconExternal, IconTrash, IconX } from "../components/icons";
import { JiraLink } from "../components/JiraLink";
import { ConfirmModal } from "../components/Modal";
import { ProfileForm } from "../components/ProfileForm";
import { useToast } from "../components/Toast";
import { ErrorBox, Loading, StateBadge, formatTime } from "../components/ui";

const STEPS: { state: JobState; label: string; gate?: boolean }[] = [
  { state: "analyzing", label: "analyze" },
  { state: "awaiting_profile_approval", label: "profile approval", gate: true },
  { state: "planning", label: "plan" },
  { state: "awaiting_plan_approval", label: "plan approval", gate: true },
  { state: "developing", label: "develop" },
  { state: "build_gate", label: "build gate" },
  { state: "qa", label: "qa" },
  { state: "awaiting_test_approval", label: "test approval", gate: true },
  { state: "devops", label: "devops" },
  { state: "done", label: "done" },
];

export function JobPage() {
  const { projectId = "", jobId = "" } = useParams();
  const job = useJob(jobId);
  const project = useProject(projectId);
  if (job.isLoading) return <Loading />;
  if (job.error) return <ErrorBox error={job.error} />;
  if (!job.data) return null;
  const j = job.data;

  return (
    <div>
      <Crumbs
        items={[
          { label: "Projects", to: "/projects" },
          { label: project.data?.name ?? "project", to: `/projects/${projectId}` },
          { label: j.request },
        ]}
      />
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <h1>
            {j.request} <StateBadge state={j.state} />
          </h1>
          <p className="faint small mono">
            {j.id} · branch slipwright/{j.id}
            {j.port ? ` · port ${j.port}` : ""}
          </p>
        </div>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          {j.data.pr_url && (
            <a className="btn" href={j.data.pr_url} target="_blank" rel="noreferrer">
              <IconExternal /> Pull request
            </a>
          )}
          <DeleteJobButton job={j} projectId={projectId} />
        </div>
      </div>

      <Stepper job={j} />
      <GatePanel job={j} />
      <Phases job={j} />
      <QaSection job={j} />
      <Steering job={j} />
      <History job={j} projectId={projectId} />
    </div>
  );
}

// -- stepper ---------------------------------------------------------------------------

function Stepper({ job }: { job: Job }) {
  const reached = new Set(job.history.map((t) => t.to_state));
  reached.add(job.state);
  const currentIndex = STEPS.findIndex((s) => s.state === job.state);
  const failed = job.state === "failed";
  return (
    <div className="stepper">
      {STEPS.map((step, i) => {
        const done = failed ? reached.has(step.state) : i < currentIndex || job.state === "done";
        const current = step.state === job.state;
        let cls = "step";
        if (step.gate) cls += " is-gate";
        if (done) cls += " done";
        if (current) cls += " current";
        return (
          <span key={step.state} style={{ display: "contents" }}>
            {i > 0 && <span className={`step-line ${done || current ? "done" : ""}`} />}
            <span className={cls}>
              <span className="dot">{done ? <IconCheck style={{ width: 12 }} /> : i + 1}</span>
              {step.label}
            </span>
          </span>
        );
      })}
      {failed && (
        <>
          <span className="step-line" />
          <span className="step failed current">
            <span className="dot">
              <IconX style={{ width: 12 }} />
            </span>
            failed
          </span>
        </>
      )}
    </div>
  );
}

function DeleteJobButton({ job, projectId }: { job: Job; projectId: string }) {
  const remove = useDeleteJob();
  const toast = useToast();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (job.state !== "done" && job.state !== "failed") return null;
  return (
    <>
      <button className="btn danger" onClick={() => setOpen(true)}>
        <IconTrash /> Delete
      </button>
      {open && (
        <ConfirmModal
          title="Delete development"
          body={
            <>
              Delete <strong>{job.request}</strong>? Its worktree, branch, history and test runs are
              removed. A pull request already opened stays on GitHub.
            </>
          }
          busy={remove.isPending}
          error={remove.error ? describeError(remove.error) : null}
          onClose={() => setOpen(false)}
          onConfirm={() =>
            remove.mutate(job.id, {
              onSuccess: () => {
                toast.ok("Development deleted");
                navigate(`/projects/${projectId}/developments`);
              },
            })
          }
        />
      )}
    </>
  );
}

// -- gates -----------------------------------------------------------------------------

function GatePanel({ job }: { job: Job }) {
  const pending = pendingApproval(job);
  if (!pending) {
    if (job.state === "failed") {
      const last = [...job.history].reverse().find((t) => t.to_state === "failed");
      return (
        <div className="callout error" style={{ display: "block" }}>
          <strong>Failed:</strong> {last?.note}
          {last?.detail && (
            <details style={{ marginTop: 6 }}>
              <summary>detail</summary>
              <Detail text={last.detail} />
            </details>
          )}
        </div>
      );
    }
    return null;
  }
  return (
    <div className="gate">
      <div className="row spread">
        <strong>Waiting for your approval of the {pending}</strong>
        <GateActions job={job} compact />
      </div>
      {job.state === "awaiting_profile_approval" && job.profile && (
        <ProfileGate job={job} profile={job.profile} />
      )}
      {job.state === "awaiting_plan_approval" && <PlanGate job={job} />}
      {job.state === "awaiting_test_approval" && job.data.qa_stage === 1 && (
        <TestCasesGate job={job} />
      )}
      {job.state === "awaiting_test_approval" && job.data.qa_stage === 2 && (
        <WrittenTestsGate job={job} />
      )}
    </div>
  );
}

function ProfileGate({ job, profile }: { job: Job; profile: Profile }) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Profile>(profile);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // follow the server value until the user starts editing (adjusting state during render)
  const [seen, setSeen] = useState(profile);
  if (seen !== profile) {
    setSeen(profile);
    if (!dirty) setDraft(profile);
  }

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.put<Job>(`/api/jobs/${job.id}/profile`, draft);
      await qc.invalidateQueries({ queryKey: keys.job(job.id) });
      setDirty(false);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginTop: 12 }}>
      <p className="muted small">
        The Analyst proposes how the project is built, tested and run. Edit anything before
        approving; the roles come from the project's seed profile and stay a human decision.
      </p>
      <ProfileForm
        value={draft}
        onChange={(next) => {
          setDraft(next);
          setDirty(true);
        }}
      />
      {error && <div className="error small">{error}</div>}
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn primary small" disabled={!dirty || saving} onClick={save}>
          {saving ? "Saving…" : "Save changes"}
        </button>
        {dirty && <span className="muted small">unsaved changes — save before approving</span>}
      </div>
    </div>
  );
}

function PlanGate({ job }: { job: Job }) {
  const plan = job.data.plan as PlanShape | null;
  if (!plan) return null;
  return (
    <div style={{ marginTop: 12 }}>
      {plan.summary && <p>{plan.summary}</p>}
      <BreakdownTree plan={plan} />
    </div>
  );
}

interface PlanShape {
  summary?: string;
  phases: { goal: string; files?: string[] }[];
  breakdown?: {
    epics: {
      id: string;
      title: string;
      description?: string;
      stories: {
        id: string;
        title: string;
        description?: string;
        tasks: { id: string; title: string; description?: string; phase: number }[];
      }[];
    }[];
  };
}

function BreakdownTree({ plan }: { plan: PlanShape }) {
  if (!plan.breakdown) {
    return (
      <ol>
        {plan.phases.map((p, i) => (
          <li key={i}>
            {p.goal}{" "}
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
              <strong>{epic.title}</strong>
              {epic.description && <div className="muted small">{epic.description}</div>}
            </span>
          </div>
          <ul className="tree">
            {epic.stories.map((story) => (
              <li key={story.id} className="depth-1">
                <div className="node">
                  <span className="kind">story</span>
                  <span className="title">
                    {story.title}
                    {story.description && <div className="muted small">{story.description}</div>}
                  </span>
                </div>
                <ul className="tree">
                  {story.tasks.map((task) => {
                    const phase = plan.phases[task.phase - 1];
                    return (
                      <li key={task.id} className="depth-2">
                        <div className="node">
                          <span className="kind">task</span>
                          <span className="title">
                            {task.title}
                            <div className="muted small">
                              phase {task.phase}: {phase?.goal}
                              {phase?.files && phase.files.length > 0 && (
                                <span className="mono"> — {phase.files.join(", ")}</span>
                              )}
                            </div>
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

function TestCasesGate({ job }: { job: Job }) {
  const save = useSetTestCases(job.id);
  const initial = useMemo(
    () => (job.data.test_cases as { name: string; description: string }[]).map((c) => ({ ...c })),
    [job.data.test_cases],
  );
  const [cases, setCases] = useState(initial);
  const [dirty, setDirty] = useState(false);
  const [seen, setSeen] = useState(initial);
  if (seen !== initial) {
    setSeen(initial);
    if (!dirty) setCases(initial);
  }

  const update = (i: number, patch: Partial<{ name: string; description: string }>) => {
    setCases(cases.map((c, k) => (k === i ? { ...c, ...patch } : c)));
    setDirty(true);
  };

  return (
    <div style={{ marginTop: 12 }}>
      <p className="muted small">
        QA proposes these test cases. Add, remove or rewrite them; the tests written next cover
        exactly this list.
      </p>
      <table>
        <thead>
          <tr>
            <th style={{ width: 220 }}>Name</th>
            <th>What it checks</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {cases.map((c, i) => (
            <tr key={i}>
              <td>
                <input
                  type="text"
                  value={c.name}
                  onChange={(e) => update(i, { name: e.target.value })}
                />
              </td>
              <td>
                <input
                  type="text"
                  value={c.description}
                  onChange={(e) => update(i, { description: e.target.value })}
                />
              </td>
              <td>
                <button
                  className="btn small bad"
                  onClick={() => {
                    setCases(cases.filter((_, k) => k !== i));
                    setDirty(true);
                  }}
                >
                  remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {save.error && <div className="error small">{describeError(save.error)}</div>}
      <div className="row" style={{ marginTop: 8 }}>
        <button
          className="btn small"
          onClick={() => {
            setCases([...cases, { name: "", description: "" }]);
            setDirty(true);
          }}
        >
          Add case
        </button>
        <button
          className="btn primary small"
          disabled={!dirty || save.isPending}
          onClick={() =>
            save.mutate(
              cases.filter((c) => c.name.trim() && c.description.trim()),
              { onSuccess: () => setDirty(false) },
            )
          }
        >
          {save.isPending ? "Saving…" : "Save list"}
        </button>
        {dirty && <span className="muted small">unsaved changes — save before approving</span>}
      </div>
    </div>
  );
}

function WrittenTestsGate({ job }: { job: Job }) {
  const entry = [...job.history]
    .reverse()
    .find((t) => t.to_state === "awaiting_test_approval" && (t.note ?? "").startsWith("qa: tests"));
  return (
    <div style={{ marginTop: 12 }}>
      <p className="muted small">
        QA wrote tests for the approved cases and they passed the build gate. Approving hands the
        branch to DevOps.
      </p>
      {entry?.detail && <Detail text={entry.detail} />}
    </div>
  );
}

// -- phases: diffs and gate output -----------------------------------------------------

interface PhaseGroup {
  number: number;
  goal: string;
  files: string[];
  entries: Transition[];
}

function groupByPhase(job: Job): PhaseGroup[] {
  const plan = job.data.plan as PlanShape | null;
  if (!plan) return [];
  const groups: PhaseGroup[] = plan.phases.map((p, i) => ({
    number: i + 1,
    goal: p.goal,
    files: p.files ?? [],
    entries: [],
  }));
  for (const t of job.history) {
    const note = t.note ?? "";
    const m = /(?:developer phase|build gate (?:passed for|failed on) phase) (\d+)/.exec(note);
    if (m) {
      const n = Number(m[1]);
      groups[n - 1]?.entries.push(t);
    }
  }
  return groups;
}

function Phases({ job }: { job: Job }) {
  const groups = useMemo(() => groupByPhase(job), [job]);
  const active =
    job.state !== "awaiting_plan_approval" && job.state !== "planning" && groups.length > 0;
  if (!active) return null;
  return (
    <section>
      <h2>Phases</h2>
      {groups.map((g) => (
        <div key={g.number} className="card" id={`phase-${g.number}`}>
          <div className="row spread">
            <div>
              <strong>
                Phase {g.number}: {g.goal}
              </strong>
              {g.files.length > 0 && <div className="muted small mono">{g.files.join(", ")}</div>}
            </div>
            <span className="muted small">
              {job.data.phase_index > g.number - 1
                ? "done"
                : job.data.phase_index === g.number - 1 &&
                    (job.state === "developing" || job.state === "build_gate")
                  ? "in progress"
                  : job.state === "failed" && job.data.phase_index === g.number - 1
                    ? "failed"
                    : "pending"}
            </span>
          </div>
          {g.entries.map((t, i) => {
            const note = t.note ?? "";
            const isGate = note.startsWith("build gate");
            return (
              <details key={i} open={!isGate && i === g.entries.length - 1}>
                <summary>
                  <span
                    className={`badge ${isGate ? (note.includes("passed") ? "ok" : "bad") : "work"}`}
                  >
                    {isGate ? "gate" : "diff"}
                  </span>{" "}
                  {note} <span className="muted small">· {formatTime(t.at)}</span>
                </summary>
                {isGate ? <pre>{t.detail}</pre> : <Diff text={t.detail ?? ""} />}
              </details>
            );
          })}
        </div>
      ))}
    </section>
  );
}

function QaSection({ job }: { job: Job }) {
  const cases = job.data.test_cases as { name: string; description: string }[];
  if (cases.length === 0 || job.state === "awaiting_test_approval") return null;
  return (
    <section>
      <h2>Test cases</h2>
      <div className="card">
        <ul>
          {cases.map((c, i) => (
            <li key={i}>
              <strong>{c.name}</strong> — {c.description}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

// -- steering ----------------------------------------------------------------------------

function Steering({ job }: { job: Job }) {
  const send = useSendMessage(job.id);
  const [text, setText] = useState("");
  const inbox = job.data.inbox;
  return (
    <section>
      <h2>Steering</h2>
      <div className="card">
        <p className="muted small">
          Messages reach the next role that runs; each is delivered exactly once.
        </p>
        {inbox.length > 0 && (
          <table>
            <tbody>
              {inbox.map((m) => (
                <tr key={m.id}>
                  <td>{m.text}</td>
                  <td className="muted small" style={{ whiteSpace: "nowrap" }}>
                    {m.consumed_by ? (
                      <>
                        read by <strong>{m.consumed_by}</strong> {formatTime(m.consumed_at)}
                      </>
                    ) : (
                      <span className="badge wait">pending</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {job.state !== "done" && job.state !== "failed" && (
          <form
            className="row"
            style={{ marginTop: 10 }}
            onSubmit={(e) => {
              e.preventDefault();
              send.mutate(text.trim(), { onSuccess: () => setText("") });
            }}
          >
            <input
              type="text"
              style={{ flex: 1 }}
              placeholder="message for the next role"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <button className="btn small" disabled={!text.trim() || send.isPending}>
              Send
            </button>
          </form>
        )}
        {send.error && <div className="error small">{describeError(send.error)}</div>}
      </div>
    </section>
  );
}

// -- history ---------------------------------------------------------------------------

function History({ job, projectId }: { job: Job; projectId: string }) {
  const items = useMemo(
    () =>
      job.history
        .map((t, index) => ({
          job_id: job.id,
          job_request: job.request,
          project_id: job.project_id,
          index,
          at: t.at,
          from_state: t.from_state,
          to_state: t.to_state,
          kind: classify(t) as "role",
          role: null,
          title: t.note ?? `${t.from_state} -> ${t.to_state}`,
          has_detail: !!t.detail,
        }))
        .reverse(),
    [job],
  );
  return (
    <section>
      <h2>History</h2>
      <div className="card">
        <ul className="feed">
          {items.map((item) => (
            <ActivityRow key={item.index} item={item} projectId={projectId} showJob={false} />
          ))}
        </ul>
      </div>
      {job.profile && job.state !== "awaiting_profile_approval" && (
        <details className="card" style={{ marginTop: 12 }}>
          <summary>Approved profile</summary>
          <pre>{JSON.stringify(job.profile, null, 2)}</pre>
        </details>
      )}
      <div className="muted small" style={{ marginTop: 8 }}>
        created {formatTime(job.created_at)}
        {job.data.jira_keys && Object.keys(job.data.jira_keys).length > 0 && (
          <>
            {" "}
            · jira:{" "}
            {Object.values(job.data.jira_keys).map((k) => (
              <JiraLink key={k} issueKey={k} />
            ))}
          </>
        )}
      </div>
    </section>
  );
}

function classify(t: Transition): string {
  const note = t.note ?? "";
  if (note === "job started") return "started";
  if (note.startsWith("inbox:")) return "inbox";
  if (note.startsWith("jira")) return "jira";
  if (note.startsWith("approved") || note.startsWith("rejected")) return "approval";
  if (note.startsWith("build gate")) return "gate";
  if (t.to_state === "done") return "done";
  if (t.to_state === "failed") return note.includes("crashed") ? "crash" : "failed";
  return "role";
}
