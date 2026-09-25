import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { describeError, type Job, type Profile, type Transition } from "../api/client";
import { useNavigate } from "react-router-dom";
import {
  keys,
  useDeleteJob,
  useJob,
  useProject,
  useSendMessage,
  usePipeline,
  useSetTestCases,
} from "../api/hooks";
import { api } from "../api/client";
import { ActivityRow } from "../components/ActivityRow";
import { BreakdownTree, type BreakdownShape, type PlanShape } from "../components/Breakdown";
import { AgentIcon, DomainBadge } from "../components/agents";
import { Crumbs } from "../components/Crumbs";
import { DesignGate } from "../components/DesignGate";
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
import { IconExternal, IconLayers, IconTrash } from "../components/icons";
import { JiraLink } from "../components/JiraLink";
import { ConfirmModal } from "../components/Modal";
import { DeploymentGate } from "../components/DeploymentGate";
import { ProfileForm } from "../components/ProfileForm";
import { StackPanel } from "../components/StackPanel";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, Loading, StateBadge, formatTime } from "../components/ui";
import { sentenceCase, useT } from "../i18n";
import { SayProvider, useSay } from "../i18n/said";
import { Copyable } from "../components/Copyable";
import { ResultCard } from "../components/ResultCard";
import { STAGE_ICON, STAGE_LABEL, stageAgent, stageStatus, stages } from "../components/stages";

export function JobPage() {
  const { projectId = "", jobId = "" } = useParams();
  const job = useJob(jobId);
  const project = useProject(projectId);
  if (job.isLoading) return <Loading />;
  if (job.error) return <ErrorBox error={job.error} />;
  if (!job.data) return null;
  const j = job.data;

  return (
    // the plan, the backlog and the write-ups below are read in the platform's language
    <SayProvider projectId={projectId}>
      <div className="job-page">
        <Crumbs
          items={[
            { label: "Projects", to: "/projects" },
            { label: sentenceCase(project.data?.name ?? "project"), to: `/projects/${projectId}` },
            { label: "Development" },
          ]}
        />
        <JobHead job={j} projectId={projectId} />
        <JobDetail job={j} projectId={projectId} />
      </div>
    </SayProvider>
  );
}

/** The head of the page. The request used to be the <h1>, which on a real request meant a
 * fourteen-line heading and no page title at all; it is a paragraph, so it reads as one --
 * two lines with the rest a click away -- under a title that says what this page is. */
function JobHead({ job, projectId }: { job: Job; projectId: string }) {
  const tx = useT();
  const [open, setOpen] = useState(false);
  const long = job.request.length > 220;
  return (
    <header className="job-head">
      <div className="job-head-top">
        <div className="job-head-id">
          <h1>{tx("Development")}</h1>
          <StateBadge state={job.state} />
        </div>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          {job.data.pr_url && (
            <a className="btn" href={job.data.pr_url} target="_blank" rel="noreferrer">
              <IconExternal /> {tx("Pull request")}
            </a>
          )}
          <DeleteJobButton job={job} projectId={projectId} />
        </div>
      </div>
      <div className="job-ask">
        <div className="job-ask-label">{tx("What was asked")}</div>
        <p className={open || !long ? "" : "clamp-2"}>{job.request}</p>
        {long && (
          <button type="button" className="text-btn tiny" onClick={() => setOpen(!open)}>
            {open ? tx("show less") : tx("show more")}
          </button>
        )}
      </div>
      <dl className="job-facts">
        <div>
          <dt>{tx("Development")}</dt>
          <dd className="mono">{job.id}</dd>
        </div>
        <div>
          <dt>{tx("Branch")}</dt>
          <dd className="mono">slipwright/{job.id}</dd>
        </div>
        {job.port !== null && job.port !== undefined && (
          <div>
            <dt>{tx("Port")}</dt>
            <dd className="mono">{job.port}</dd>
          </div>
        )}
      </dl>
    </header>
  );
}

/** Everything a development shows under its title: where the work is, whatever needs a
 * decision from you, and the tabs. Its own page draws this under its header; a lane on the
 * project's flow tab draws the same thing when it is unfolded, so "detail" means one thing
 * in both places. `flow` is the lane's step-by-step view, which only the lane has.
 */
export function JobDetail({
  job,
  projectId,
  flow,
}: {
  job: Job;
  projectId: string;
  flow?: ReactNode;
}) {
  if (flow) {
    // A lane is opened to see the flow, so the flow is what it lands on -- with one thing
    // in front of it. An approval is not repeated here: the flow already shows it as the
    // card the work is sitting on, and clicking that card is what opens the gate, the panel
    // that slides in from the right; drawn above the flow as well, an architecture gate (a
    // whole plan, a profile and a decision list) pushed the thing the lane was opened for
    // two screens down. A failure is the opposite case. It has no card of its own and it is
    // the reason the development stopped, so under the flow it sat below twenty step cards
    // where nobody found it. It belongs directly under the stages, where the eye already is.
    return (
      <>
        <StageStepper job={job} projectId={projectId} />
        {!pendingApproval(job) && <GatePanel job={job} />}
        <JobTabs job={job} projectId={projectId} flow={flow} />
      </>
    );
  }
  return (
    <>
      <StageStepper job={job} projectId={projectId} />
      {/* whatever needs you comes before anything you might only want to read */}
      <GatePanel job={job} />
      <JobTabs job={job} projectId={projectId} />
    </>
  );
}

/** Where the work is, in the four stages the pipeline already draws -- same names, same
 * agent colours -- instead of twelve engine states in a row that wrapped onto three lines
 * and named things ("build gate", "review decision") no one asked about. */
function StageStepper({ job, projectId }: { job: Job; projectId: string }) {
  const tx = useT();
  const pipeline = usePipeline(projectId);
  const lane = pipeline.data?.lanes.find((l) => l.job_id === job.id);
  if (!lane) return null;
  const groups = stages(lane.steps);
  return (
    <ol className="job-stages">
      {groups.map((group) => {
        const done = group.steps.filter((s) => s.status === "done").length;
        const agent = stageAgent(group.steps);
        const Icon = STAGE_ICON[group.key] ?? IconLayers;
        return (
          <li
            key={group.key}
            className={`job-stage ${stageStatus(group.steps)}`}
            data-agent={agent}
          >
            <span className="job-stage-icon">{agent ? <AgentIcon role={agent} /> : <Icon />}</span>
            <span className="job-stage-id">
              <span className="job-stage-title">{tx(STAGE_LABEL[group.key] ?? group.key)}</span>
              <span className="faint tiny mono">
                {done}/{group.steps.length}
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

const TABS = ["result", "phases", "tests", "calls", "steering", "history"] as const;
type Tab = (typeof TABS)[number] | "flow";

const TAB_LABEL: Record<Tab, string> = {
  flow: "Flow",
  result: "What came out",
  phases: "Phases",
  tests: "Tests",
  calls: "Model calls",
  steering: "Steering",
  history: "History",
};

/** The page used to stack every section open at once: the result, the phases with their
 * diffs, the test cases, every model call and the whole history, one after another. They
 * are the same sections, behind tabs, so the page opens on the one answer most people came
 * for and the rest is a click rather than a scroll. */
function JobTabs({ job, projectId, flow }: { job: Job; projectId: string; flow?: ReactNode }) {
  const tx = useT();
  // the flow is what a lane is opened for, so it is the tab a lane opens on; the page has
  // no flow of its own and opens on the result, the one answer most people came for
  const [tab, setTab] = useState<Tab>(flow ? "flow" : "result");
  const tabs: Tab[] = flow ? ["flow", ...TABS] : [...TABS];
  return (
    <>
      <nav className="tabs" role="tablist">
        {tabs.map((key) => (
          <button
            key={key}
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "tab active" : "tab"}
            onClick={() => setTab(key)}
          >
            {tx(TAB_LABEL[key])}
          </button>
        ))}
      </nav>
      <div className="job-tab-body">
        {tab === "flow" && flow}
        {tab === "result" && <ResultCard job={job} />}
        {tab === "phases" && <Phases job={job} />}
        {tab === "tests" && <QaSection job={job} />}
        {tab === "calls" && <Invocations job={job} />}
        {tab === "steering" && <Steering job={job} />}
        {tab === "history" && <History job={job} projectId={projectId} />}
      </div>
    </>
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
            <RetryActions job={job} />
          </div>
          {last?.detail && (
            <details style={{ marginTop: 6 }}>
              <summary>{tx("detail")}</summary>
              <Detail text={last.detail} />
            </details>
          )}
          <div className="small muted" style={{ marginTop: 6 }}>
            {tx("Retry continues from the step that failed")} (
            <code>{last?.from_state ?? "backlog"}</code>); {tx("everything built so far stays.")}
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
      {job.state === "awaiting_design_approval" && <DesignGate jobId={job.id} />}
      {job.state === "awaiting_review_approval" && <ReviewGate job={job} />}
      {job.state === "awaiting_decision" && <DecisionGate job={job} />}
      {job.state === "awaiting_test_approval" && job.data.qa_stage === 1 && (
        <TestCasesGate job={job} />
      )}
      {job.state === "awaiting_test_approval" && job.data.qa_stage === 2 && (
        <WrittenTestsGate job={job} />
      )}
      {job.state === "awaiting_deploy_approval" && <DeploymentGate job={job} />}
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
        {tx(
          "The Architect proposes how the project is built, tested and run. Edit anything before approving; the roles come from the project's seed profile and stay a human decision.",
        )}
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
  const say = useSay();
  const plan = job.data.plan as PlanShape | null;
  if (!plan) return null;
  return (
    <div style={{ marginTop: 12 }}>
      {plan.summary && <p>{say(plan.summary)}</p>}
      <StackPanel job={job} editable />
      {plan.decisions && plan.decisions.length > 0 && (
        <>
          <h3>{tx("Decisions")}</h3>
          <ul>
            {plan.decisions.map((d, i) => (
              <li key={i}>{say(d)}</li>
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
        {tx("Approving continues with")} <code>{resume}</code>{" "}
        {tx(
          "as it was; rejecting continues too, with your feedback delivered to the agent that runs next. Nothing more is spent until you decide.",
        )}
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
        {tx(
          "QA proposes these test cases. Add, remove or rewrite them; the tests written next cover exactly this list.",
        )}
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
    const m = /(?:\w+:? phase|build gate (?:passed for|failed on) phase) (\d+)/.exec(note);
    if (m) {
      const n = Number(m[1]);
      groups[n - 1]?.entries.push(t);
    }
  }
  return groups;
}

type PhaseState = "done" | "in review" | "in progress" | "failed" | "pending";

const PHASE_TONE: Record<PhaseState, string> = {
  done: "ok",
  "in review": "work",
  "in progress": "work",
  failed: "bad",
  pending: "idle",
};

/** Where a phase stands. Read off the job, not off the phase's own entries: what the
 *  engine is doing right now is the only thing that says which phase is live. */
function phaseState(job: Job, number: number): PhaseState {
  const at = job.data.phase_index;
  if ((job.state === "review" || job.state === "awaiting_review_approval") && at === number)
    return "in review";
  if (at > number - 1) return "done";
  if (at === number - 1) {
    if (job.state === "failed") return "failed";
    if (job.state === "developing" || job.state === "build_gate") return "in progress";
  }
  return "pending";
}

type StepKind = "diff" | "gate" | "standards" | "review" | "qa";
type StepBody = "diff" | "output" | "review" | "standards";

/** What one entry under a phase is, how it went, and what its detail holds. The engine
 *  writes these notes, so they are a closed set; anything else reads as a plain diff. */
function stepKind(note: string): { kind: StepKind; tone: string; body: StepBody } {
  if (note.startsWith("qa: phase")) {
    const corrected = note.includes("the test was wrong");
    // a corrected test comes with the diff of the correction; every other verdict
    // carries the failure that prompted it
    return { kind: "qa", tone: corrected ? "ok" : "bad", body: corrected ? "diff" : "output" };
  }
  if (note.startsWith("build gate"))
    return { kind: "gate", tone: note.includes("passed") ? "ok" : "bad", body: "output" };
  if (note.startsWith("standards")) return { kind: "standards", tone: "idle", body: "standards" };
  if (note.startsWith("review phase")) {
    const clean = note.includes("clean");
    const blocked = note.includes("blocking, 0 advisory") || note.includes("needs your decision");
    return { kind: "review", tone: clean ? "ok" : blocked ? "bad" : "work", body: "review" };
  }
  return { kind: "diff", tone: "work", body: "diff" };
}

/** What a collapsed phase says about itself: how many times its specialist had to write
 *  it, and how many gates it lost on the way. Nothing that did not happen is counted. */
function tally(entries: Transition[]): { attempts: number; failures: number } {
  let attempts = 0;
  let failures = 0;
  for (const t of entries) {
    const note = t.note ?? "";
    const { kind } = stepKind(note);
    if (kind === "diff") attempts += 1;
    if (kind === "gate" && !note.includes("passed")) failures += 1;
  }
  return { attempts, failures };
}

function Phases({ job }: { job: Job }) {
  const tx = useT();
  const groups = useMemo(() => groupByPhase(job), [job]);
  // the board links a task straight at its phase (#phase-3): that one opens and is
  // scrolled to, or the link would land on a panel that is shut
  const asked = Number(/^#phase-(\d+)$/.exec(useLocation().hash)?.[1] ?? 0);
  useEffect(() => {
    if (asked) document.getElementById(`phase-${asked}`)?.scrollIntoView({ block: "start" });
  }, [asked]);
  const active =
    job.state !== "awaiting_architecture_approval" &&
    job.state !== "architecture" &&
    groups.length > 0;
  if (!active)
    return <Empty>{tx("Nothing is built yet: the plan has to be approved first.")}</Empty>;
  // otherwise the phase being worked on opens itself and the rest stay shut -- which is
  // the point of the tab: the shape of the work first, a phase's detail when asked for
  const live = groups.find((g) => g.entries.length > 0 && phaseState(job, g.number) !== "done");
  const opened = asked || live?.number;
  return (
    <section>
      <h2>{tx("Phases")}</h2>
      <div className="phase-list">
        {groups.map((g) => (
          <PhasePanel key={g.number} job={job} group={g} open={g.number === opened} />
        ))}
      </div>
    </section>
  );
}

function PhasePanel({ job, group, open }: { job: Job; group: PhaseGroup; open: boolean }) {
  const tx = useT();
  const say = useSay();
  const state = phaseState(job, group.number);
  const { attempts, failures } = tally(group.entries);
  const label: Record<PhaseState, string> = {
    done: tx("done"),
    "in review": tx("in review"),
    "in progress": tx("in progress"),
    failed: tx("failed"),
    pending: tx("pending"),
  };
  return (
    <details className="phase" id={`phase-${group.number}`} open={open} data-state={state}>
      <summary>
        <span className="phase-no">{group.number}</span>
        <span className="phase-head">
          <span className="goal">{say(group.goal)}</span>
          <span className="phase-meta">
            <DomainBadge domain={group.domain} />
            {group.entries.length > 0 && (
              <span className="tag">{tx("{n} step(s)", { n: group.entries.length })}</span>
            )}
            {attempts > 1 && <span className="tag">{tx("{n} attempt(s)", { n: attempts })}</span>}
            {failures > 0 && (
              <span className="tag bad">{tx("{n} gate failure(s)", { n: failures })}</span>
            )}
            {group.files.length > 0 && <span className="tag mono">{group.files.join(", ")}</span>}
          </span>
        </span>
        <span className={`badge ${PHASE_TONE[state]} plain`}>{label[state]}</span>
      </summary>
      <div className="phase-body">
        {group.entries.length === 0 ? (
          <div className="muted small">{tx("Nothing has run in this phase yet.")}</div>
        ) : (
          group.entries.map((t, i) => (
            <Step key={i} entry={t} last={i === group.entries.length - 1} />
          ))
        )}
      </div>
    </details>
  );
}

function Step({ entry, last }: { entry: Transition; last: boolean }) {
  const note = entry.note ?? "";
  const { kind, tone, body } = stepKind(note);
  const detail = entry.detail ?? "";
  return (
    <details className="step-row" open={kind === "diff" && last}>
      <summary>
        <span className={`badge ${tone}`}>{kind}</span> {note}{" "}
        <span className="muted small">· {formatTime(entry.at)}</span>
      </summary>
      {body === "review" ? (
        <ReviewDetail text={detail} />
      ) : body === "standards" ? (
        <StandardsList text={detail} />
      ) : body === "output" ? (
        <Copyable text={detail}>
          <pre>{detail}</pre>
        </Copyable>
      ) : (
        <Copyable text={detail}>
          <Diff text={detail} />
        </Copyable>
      )}
    </details>
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
  if (log.length === 0) return <Empty>{tx("No model call has been recorded yet.")}</Empty>;
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
  const say = useSay();
  const cases = job.data.test_cases as { name: string; description: string }[];
  if (job.state === "awaiting_test_approval") return null;
  if (cases.length === 0)
    return <Empty>{tx("QA has not proposed any test cases for this development.")}</Empty>;
  return (
    <section>
      <h2>{tx("Test cases")}</h2>
      <div className="card">
        <ul>
          {cases.map((c, i) => (
            <li key={i}>
              <strong>{say(c.name)}</strong> — {say(c.description)}
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
                      <span className="badge wait">{tx("pending")}</span>
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
