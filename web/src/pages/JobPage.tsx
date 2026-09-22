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
import { DomainBadge } from "../components/agents";
import { Crumbs } from "../components/Crumbs";
import { Detail } from "../components/Detail";
import { Diff } from "../components/Diff";
import { ReviewDetail, ViolationsTable, type ReviewRecord } from "../components/Review";
import {
  GateActions,
  Recommendation,
  RetryActions,
  failureOf,
  pendingApproval,
} from "../components/GateActions";
import { IconCheck, IconExternal, IconTrash, IconX } from "../components/icons";
import { JiraLink } from "../components/JiraLink";
import { ConfirmModal } from "../components/Modal";
import { ProfileForm } from "../components/ProfileForm";
import { useToast } from "../components/Toast";
import { ErrorBox, Loading, StateBadge, formatTime } from "../components/ui";
import { useT } from "../i18n";
import { Copyable } from "../components/Copyable";

const STEPS: { state: JobState; label: string; gate?: boolean }[] = [
  { state: "backlog", label: "backlog" },
  { state: "awaiting_backlog_approval", label: "backlog approval", gate: true },
  { state: "architecture", label: "architecture" },
  { state: "awaiting_architecture_approval", label: "architecture approval", gate: true },
  { state: "developing", label: "develop" },
  { state: "build_gate", label: "build gate" },
  { state: "review", label: "review" },
  { state: "awaiting_review_approval", label: "review decision", gate: true },
  { state: "qa", label: "qa" },
  { state: "awaiting_test_approval", label: "test approval", gate: true },
  { state: "devops", label: "devops" },
  { state: "done", label: "done" },
];

export function JobPage() {
  const tx = useT();
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
              <IconExternal /> {tx("Pull request")}
            </a>
          )}
          <DeleteJobButton job={j} projectId={projectId} />
        </div>
      </div>

      <Stepper job={j} />
      <GatePanel job={j} />
      <Phases job={j} />
      <QaSection job={j} />
      <Invocations job={j} />
      <Steering job={j} />
      <History job={j} projectId={projectId} />
    </div>
  );
}

// -- stepper ---------------------------------------------------------------------------

function Stepper({ job }: { job: Job }) {
  const tx = useT();
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
              {tx(step.label)}
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
  const tx = useT();
  const remove = useDeleteJob();
  const toast = useToast();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (job.state !== "done" && job.state !== "failed") return null;
  return (
    <>
      <button className="btn danger" onClick={() => setOpen(true)}>
        <IconTrash /> {tx("Delete")}
      </button>
      {open && (
        <ConfirmModal
          title={tx("Delete development")}
          body={
            <>
              {tx("Delete")} <strong>{job.request}</strong>
              {tx(
                "? Its worktree, branch, history and test runs are removed. A pull request already opened stays on GitHub.",
              )}
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
  const tx = useT();
  const pending = pendingApproval(job);
  if (!pending) {
    if (job.state === "failed") {
      const last = failureOf(job);
      return (
        <div className="callout error" style={{ display: "block" }}>
          <div className="row spread">
            <span>
              <strong>{tx("Failed:")}</strong> {last?.note}
            </span>
            <RetryActions job={job} compact />
          </div>
          {last?.detail && (
            <details style={{ marginTop: 6 }}>
              <summary>detail</summary>
              <Detail text={last.detail} />
            </details>
          )}
          <div className="small muted" style={{ marginTop: 6 }}>
            Retry continues from the step that failed (<code>{last?.from_state ?? "backlog"}</code>
            ); everything built so far stays.
          </div>
        </div>
      );
    }
    return null;
  }
  return (
    <div className="gate">
      <div className="row spread">
        <strong>
          {tx("Waiting for your approval of the {pending}", { pending: tx(pending) })}
        </strong>
        <GateActions job={job} compact />
      </div>
      <Recommendation job={job} detailed />
      {job.state === "awaiting_backlog_approval" && <BacklogGate job={job} />}
      {job.state === "awaiting_architecture_approval" && <ArchitectureGate job={job} />}
      {job.state === "awaiting_review_approval" && <ReviewGate job={job} />}
      {job.state === "awaiting_decision" && <DecisionGate job={job} />}
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
  const tx = useT();
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
        The Architect proposes how the project is built, tested and run. Edit anything before
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
          {saving ? tx("Saving…") : tx("Save changes")}
        </button>
        {dirty && (
          <span className="muted small">{tx("unsaved changes — save before approving")}</span>
        )}
      </div>
    </div>
  );
}

/** The Product Owner's backlog: the epic / story / task tree, before any design. */
function BacklogGate({ job }: { job: Job }) {
  const tx = useT();
  const backlog = job.data.backlog as BreakdownShape | null;
  if (!backlog) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <p className="muted small">
        {tx(
          "The Product Owner turned the request into epics, stories and tasks. Once approved they are mirrored to Jira and the Architect designs one phase per task.",
        )}
      </p>
      <BreakdownTree plan={{ phases: [], breakdown: backlog }} />
    </div>
  );
}

/** The Architect's proposal: profile, decisions and the phases mapped onto the backlog. */
function ArchitectureGate({ job }: { job: Job }) {
  const tx = useT();
  const plan = job.data.plan as PlanShape | null;
  if (!plan) return null;
  return (
    <div style={{ marginTop: 12 }}>
      {plan.summary && <p>{plan.summary}</p>}
      {plan.decisions && plan.decisions.length > 0 && (
        <>
          <h3>{tx("Decisions")}</h3>
          <ul>
            {plan.decisions.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </>
      )}
      <h3>{tx("Phases")}</h3>
      <BreakdownTree plan={plan} />
      {job.profile && (
        <>
          <h3>{tx("Profile")}</h3>
          <ProfileGate job={job} profile={job.profile} />
        </>
      )}
    </div>
  );
}

/** The job stopped mid-step (a loop, or the supervisor asked): continue, or send
 * feedback that reaches the role that continues. */
function DecisionGate({ job }: { job: Job }) {
  const tx = useT();
  const stop = [...job.history].reverse().find((t) => t.to_state === "awaiting_decision");
  const resume = job.data.resume_state ?? "the interrupted step";
  return (
    <div style={{ marginTop: 12 }}>
      <p>
        <strong>{stop?.note}</strong>
      </p>
      <p className="muted small">
        {tx("Approving continues with")} <code>{resume}</code> as it was; rejecting continues too,
        with your feedback delivered to the agent that runs next. Nothing more is spent until you
        decide.
      </p>
      {stop?.detail && (
        <details>
          <summary className="small">{tx("what happened")}</summary>
          <Detail text={stop.detail} />
        </details>
      )}
    </div>
  );
}

/** The findings QA could not get the specialist to fix: accept them or send it back. */
function ReviewGate({ job }: { job: Job }) {
  const reviews = job.data.reviews as unknown as ReviewRecord[];
  const last = reviews[reviews.length - 1];
  if (!last) return null;
  return (
    <div style={{ marginTop: 12 }}>
      <p className="muted small">
        Phase {last.phase} passed the build but still breaks {last.blocking} blocking standard
        {last.blocking === 1 ? "" : "s"} after {last.round} fix round{last.round === 1 ? "" : "s"}.
        Approving keeps the phase as built and continues; rejecting sends it back to the specialist
        with your feedback.
      </p>
      <ViolationsTable violations={last.violations} />
    </div>
  );
}

interface BreakdownShape {
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

interface PlanShape {
  summary?: string;
  decisions?: string[];
  phases: { goal: string; files?: string[]; domain?: string; task_id?: string | null }[];
  breakdown?: BreakdownShape;
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
                    const phase = task.phase ? plan.phases[task.phase - 1] : undefined;
                    return (
                      <li key={task.id} className="depth-2">
                        <div className="node">
                          <span className="kind">task</span>
                          <span className="title">
                            {task.title}
                            {task.description && (
                              <div className="muted small">{task.description}</div>
                            )}
                            {phase && (
                              <div className="muted small">
                                phase {task.phase}: {phase.goal}{" "}
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

function TestCasesGate({ job }: { job: Job }) {
  const tx = useT();
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
            <th style={{ width: 220 }}>{tx("Name")}</th>
            <th>{tx("What it checks")}</th>
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
          {tx("Add case")}
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
          {save.isPending ? tx("Saving…") : tx("Save list")}
        </button>
        {dirty && (
          <span className="muted small">{tx("unsaved changes — save before approving")}</span>
        )}
      </div>
    </div>
  );
}

function WrittenTestsGate({ job }: { job: Job }) {
  const tx = useT();
  const entry = [...job.history]
    .reverse()
    .find((t) => t.to_state === "awaiting_test_approval" && (t.note ?? "").startsWith("qa: tests"));
  return (
    <div style={{ marginTop: 12 }}>
      <p className="muted small">
        {tx(
          "QA wrote tests for the approved cases and they passed the build gate. Approving hands the branch to DevOps.",
        )}
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
  domain?: string;
  entries: Transition[];
}

function groupByPhase(job: Job): PhaseGroup[] {
  const plan = job.data.plan as PlanShape | null;
  if (!plan) return [];
  const groups: PhaseGroup[] = plan.phases.map((p, i) => ({
    number: i + 1,
    goal: p.goal,
    files: p.files ?? [],
    domain: p.domain,
    entries: [],
  }));
  for (const t of job.history) {
    const note = t.note ?? "";
    const m = /(?:\w+ phase|build gate (?:passed for|failed on) phase) (\d+)/.exec(note);
    if (m) {
      const n = Number(m[1]);
      groups[n - 1]?.entries.push(t);
    }
  }
  return groups;
}

function Phases({ job }: { job: Job }) {
  const tx = useT();
  const groups = useMemo(() => groupByPhase(job), [job]);
  const active =
    job.state !== "awaiting_architecture_approval" &&
    job.state !== "architecture" &&
    groups.length > 0;
  if (!active) return null;
  return (
    <section>
      <h2>{tx("Phases")}</h2>
      {groups.map((g) => (
        <div key={g.number} className="card" id={`phase-${g.number}`}>
          <div className="row spread">
            <div>
              <strong>{tx("Phase {n}: {goal}", { n: g.number, goal: g.goal })}</strong>
              <DomainBadge domain={g.domain} />
              {g.files.length > 0 && <div className="muted small mono">{g.files.join(", ")}</div>}
            </div>
            <span className="muted small">
              {(job.state === "review" || job.state === "awaiting_review_approval") &&
              job.data.phase_index === g.number
                ? tx("in review")
                : job.data.phase_index > g.number - 1
                  ? tx("done")
                  : job.data.phase_index === g.number - 1 &&
                      (job.state === "developing" || job.state === "build_gate")
                    ? tx("in progress")
                    : job.state === "failed" && job.data.phase_index === g.number - 1
                      ? tx("failed")
                      : tx("pending")}
            </span>
          </div>
          {g.entries.map((t, i) => {
            const note = t.note ?? "";
            const isGate = note.startsWith("build gate");
            const isStandards = note.startsWith("standards");
            const isReview = note.startsWith("review phase");
            const badge = isReview
              ? "review"
              : isStandards
                ? "standards"
                : isGate
                  ? "gate"
                  : "diff";
            const cls = isReview
              ? note.includes("clean")
                ? "ok"
                : note.includes("blocking, 0 advisory") || note.includes("needs your decision")
                  ? "bad"
                  : "work"
              : isStandards
                ? "idle"
                : isGate
                  ? note.includes("passed")
                    ? "ok"
                    : "bad"
                  : "work";
            return (
              <details
                key={i}
                open={!isGate && !isStandards && !isReview && i === g.entries.length - 1}
              >
                <summary>
                  <span className={`badge ${cls}`}>{badge}</span> {note}{" "}
                  <span className="muted small">· {formatTime(t.at)}</span>
                </summary>
                {isReview ? (
                  <ReviewDetail text={t.detail ?? ""} />
                ) : isStandards ? (
                  <StandardsList text={t.detail ?? ""} />
                ) : isGate ? (
                  <Copyable text={t.detail ?? ""}>
                    <pre>{t.detail}</pre>
                  </Copyable>
                ) : (
                  <Copyable text={t.detail ?? ""}>
                    <Diff text={t.detail ?? ""} />
                  </Copyable>
                )}
              </details>
            );
          })}
        </div>
      ))}
    </section>
  );
}

/** The retrieval record: query and budget on top, then one line per section given. */
function StandardsList({ text }: { text: string }) {
  const lines = text.split("\n").filter(Boolean);
  const meta = lines.filter((l) => /^(domain|query|budget):/.test(l));
  const sections = lines.filter((l) => !/^(domain|query|budget):/.test(l) && !l.startsWith("("));
  const tail = lines.find((l) => l.startsWith("("));
  return (
    <div className="small">
      {meta.map((l) => (
        <div key={l} className="muted">
          {l}
        </div>
      ))}
      <ul style={{ margin: "6px 0 0 18px" }}>
        {sections.map((l) => {
          const [id, rest] = l.split("  ", 2);
          return (
            <li key={id}>
              <span className="mono muted">{id}</span> {rest}
            </li>
          );
        })}
      </ul>
      {tail && <div className="muted">{tail}</div>}
    </div>
  );
}

interface InvocationEntry {
  role: string;
  state: string;
  phase: number | null;
  attempts: number;
  prompt_chars: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  ok: boolean;
  error: string | null;
  at: string;
}

/** Every model call: who, when, how big the prompt was, what it cost (T9.7). */
function Invocations({ job }: { job: Job }) {
  const tx = useT();
  const log = job.data.invocation_log as unknown as InvocationEntry[];
  if (log.length === 0) return null;
  const tokens = log.reduce((n, e) => n + (e.input_tokens ?? 0) + (e.output_tokens ?? 0), 0);
  return (
    <section>
      <h2>{tx("Model calls")}</h2>
      <details className="card">
        <summary>
          {tx("{calls} call(s) · {attempts} attempt(s) · {tokens} tokens", {
            calls: log.length,
            attempts: job.data.invocations,
            tokens: tokens.toLocaleString(),
          })}
        </summary>
        <table style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>{tx("When")}</th>
              <th>{tx("Role")}</th>
              <th>{tx("Step")}</th>
              <th>{tx("Prompt")}</th>
              <th>{tx("Tokens in / out")}</th>
              <th>{tx("Attempts")}</th>
              <th>{tx("Result")}</th>
            </tr>
          </thead>
          <tbody>
            {log.map((e, i) => (
              <tr key={i}>
                <td className="muted small">{formatTime(e.at)}</td>
                <td>{e.role}</td>
                <td className="small">
                  {e.state}
                  {e.phase ? ` · phase ${e.phase}` : ""}
                </td>
                <td className="mono small">
                  {e.prompt_chars !== null ? `${(e.prompt_chars / 1000).toFixed(1)}k chars` : "—"}
                </td>
                <td className="mono small">
                  {e.input_tokens ?? "—"} / {e.output_tokens ?? "—"}
                </td>
                <td>{e.attempts}</td>
                <td>
                  <span className={`badge plain ${e.ok ? "ok" : "bad"}`}>
                    {e.ok ? "ok" : (e.error ?? "failed")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}

function QaSection({ job }: { job: Job }) {
  const tx = useT();
  const cases = job.data.test_cases as { name: string; description: string }[];
  if (cases.length === 0 || job.state === "awaiting_test_approval") return null;
  return (
    <section>
      <h2>{tx("Test cases")}</h2>
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
  const tx = useT();
  const send = useSendMessage(job.id);
  const [text, setText] = useState("");
  const inbox = job.data.inbox;
  return (
    <section>
      <h2>{tx("Steering")}</h2>
      <div className="card">
        <p className="muted small">
          {tx("Messages reach the next role that runs; each is delivered exactly once.")}
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
                        {tx("read by")} <strong>{m.consumed_by}</strong> {formatTime(m.consumed_at)}
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
              placeholder={tx("message for the next role")}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <button className="btn small" disabled={!text.trim() || send.isPending}>
              {tx("Send")}
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
  const tx = useT();
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
      <h2>{tx("History")}</h2>
      <div className="card">
        <ul className="feed">
          {items.map((item) => (
            <ActivityRow key={item.index} item={item} projectId={projectId} showJob={false} />
          ))}
        </ul>
      </div>
      {job.profile && job.state !== "awaiting_architecture_approval" && (
        <details className="card" style={{ marginTop: 12 }}>
          <summary>{tx("Approved profile")}</summary>
          <Copyable text={JSON.stringify(job.profile, null, 2)}>
            <pre>{JSON.stringify(job.profile, null, 2)}</pre>
          </Copyable>
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
  if (note.startsWith("standards")) return "standards";
  if (note.startsWith("approved") || note.startsWith("rejected")) return "approval";
  if (note.startsWith("build gate")) return "gate";
  if (t.to_state === "done") return "done";
  if (t.to_state === "failed") return note.includes("crashed") ? "crash" : "failed";
  return "role";
}
