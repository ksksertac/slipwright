// The project's pipeline: one lane per development. A lane opens with what was asked --
// a short headline over the brief -- and then reads left to right as a flow: the steps
// grouped into the four stages every development goes through, linked by arrows, each
// card coloured by state. Cards waiting for the human carry a checkbox for bulk approval;
// clicking any card opens a side panel with that step's output, and editable gates edit
// in place.
import { useEffect, useMemo, useRef, useState, type ComponentType } from "react";
import { Link } from "react-router-dom";
import { describeError, type Job, type Lane, type Profile, type StepCard } from "../api/client";
import {
  useApprove,
  useJob,
  usePipeline,
  useReject,
  useRerunStep,
  useSetBacklog,
  useSetPlan,
  useSetProfile,
  useSetTestCases,
  useTransition,
} from "../api/hooks";
import { AgentIcon, DomainBadge, ROLE_LABEL } from "../components/agents";
import { BulkBar } from "../components/BulkBar";
import { RetryActions } from "../components/GateActions";
import { Detail } from "../components/Detail";
import { ReviewDetail } from "../components/Review";
import {
  BacklogEditor,
  PlanEditor,
  TestCasesEditor,
  type BreakdownShape,
  type PlanShape,
  type TestCaseShape,
} from "../components/GateEditors";
import {
  IconCheck,
  IconCpu,
  IconFlask,
  IconGit,
  IconLayers,
  IconUsers,
  IconX,
} from "../components/icons";
import { ProfileForm } from "../components/ProfileForm";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, Loading, ProgressBar, StateBadge, timeAgo } from "../components/ui";
import { useT, type T } from "../i18n";

export function PipelineTab({ projectId }: { projectId: string }) {
  const tx = useT();
  const pipeline = usePipeline(projectId);
  const [chosen, setSelected] = useState<string[]>([]);
  const [open, setOpen] = useState<{ jobId: string; key: string } | null>(null);
  const lanes = useMemo(() => pipeline.data?.lanes ?? [], [pipeline.data]);

  // a job that moved on is no longer selectable: the selection is read through the lanes
  const waiting = useMemo(
    () => new Set(lanes.filter((l) => l.pending_approval).map((l) => l.job_id)),
    [lanes],
  );
  const selected = useMemo(() => chosen.filter((id) => waiting.has(id)), [chosen, waiting]);
  const recommended = useMemo(
    () =>
      lanes
        .filter((l) =>
          l.steps.some((s) => s.status === "waiting" && s.recommendation === "approve"),
        )
        .map((l) => l.job_id),
    [lanes],
  );

  if (pipeline.isLoading) return <Loading rows={4} />;
  if (pipeline.error) return <ErrorBox error={pipeline.error} />;
  if (lanes.length === 0) {
    return (
      <Empty
        title={tx("No development yet")}
        action={
          <Link className="btn primary" to={`/projects/${projectId}/developments`}>
            {tx("Start one")}
          </Link>
        }
      >
        {tx(
          "Every development shows up here as a lane of steps: what the agents did, what runs now, and what waits for you.",
        )}
      </Empty>
    );
  }
  const toggle = (jobId: string, on: boolean) =>
    setSelected((ids) => (on ? [...new Set([...ids, jobId])] : ids.filter((i) => i !== jobId)));
  const requests = new Map(lanes.map((l) => [l.job_id, l.request]));

  return (
    <div className="stack">
      <div className="row spread">
        <div className="muted small">
          {waiting.size === 0
            ? tx("Nothing waits for you.")
            : tx("{n} development(s) waiting for your approval", { n: waiting.size })}
        </div>
        <div className="row">
          {recommended.length > 0 && (
            <button
              className="btn small"
              onClick={() => setSelected(recommended)}
              title={tx("the gates the supervisor recommends approving")}
            >
              {tx("Select all recommended ({n})", { n: recommended.length })}
            </button>
          )}
          {waiting.size > 0 && (
            <button
              className="btn small"
              onClick={() => setSelected([...waiting])}
              disabled={selected.length === waiting.size}
            >
              {tx("Select all waiting")}
            </button>
          )}
        </div>
      </div>
      {lanes.map((lane) => (
        <LaneRow
          key={lane.job_id}
          lane={lane}
          projectId={projectId}
          selected={selected.includes(lane.job_id)}
          onSelect={(on) => toggle(lane.job_id, on)}
          onOpen={(key) => setOpen({ jobId: lane.job_id, key })}
          openKey={open?.jobId === lane.job_id ? open.key : null}
        />
      ))}
      <BulkBar
        selected={selected}
        onClear={() => setSelected([])}
        labelOf={(id) => requests.get(id) ?? id}
      />
      {open && (
        <StepPanel
          jobId={open.jobId}
          stepKey={open.key}
          projectId={projectId}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  );
}

/** The four stages every development goes through. Grouping the cards under them is what
 * turns a long row into something you can read: you see where the work is, not twenty
 * equal boxes. A card whose key is not one of the fixed ones (the decision gate, which is
 * inserted wherever it interrupted) stays in the stage it was inserted into. */
const STAGE_LABEL: Record<string, string> = {
  plan: "Planning",
  build: "Building",
  test: "Testing",
  ship: "Delivery",
};
/** What each stage is for, and the icon that says it at a glance. */
const STAGE_NOTE: Record<string, string> = {
  plan: "What to build, and how it will be built and tested",
  build: "One phase per task, each behind the build gate",
  test: "The cases you approve, then the tests that cover them",
  ship: "The branch, the pull request and its checks",
};

const STAGE_ICON: Record<string, ComponentType<{ className?: string }>> = {
  plan: IconLayers,
  build: IconCpu,
  test: IconFlask,
  ship: IconGit,
};

type Stage = { key: string; steps: StepCard[] };

function stageOf(step: StepCard): string | null {
  switch (step.key.split(":")[0]) {
    case "backlog":
    case "backlog_gate":
    case "architecture":
    case "architecture_gate":
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

function stages(steps: StepCard[]): Stage[] {
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

function stageStatus(steps: StepCard[]): string {
  if (steps.some((s) => s.status === "waiting")) return "waiting";
  if (steps.some((s) => s.status === "failed")) return "failed";
  if (steps.some((s) => s.status === "running")) return "running";
  return steps.every((s) => s.status === "done") ? "done" : "pending";
}

/** A one-line title for a development whose request is a paragraph: the first sentence,
 * clipped. The whole request is right below it, so nothing is lost by cutting here. */
function headline(request: string): string {
  const first = request.trim().split(/\r?\n/, 1)[0]!.trim();
  const stop = first.search(/[;:.!?](\s|$)/);
  const title = stop > 12 ? first.slice(0, stop) : first;
  return title.length > 76 ? `${title.slice(0, 73).trimEnd()}…` : title;
}

function LaneRow({
  lane,
  projectId,
  selected,
  onSelect,
  onOpen,
  openKey,
}: {
  lane: Lane;
  projectId: string;
  selected: boolean;
  onSelect: (on: boolean) => void;
  onOpen: (key: string) => void;
  openKey: string | null;
}) {
  const tx = useT();
  const groups = useMemo(() => stages(lane.steps), [lane.steps]);
  const done = lane.steps.filter((s) => s.status === "done").length;
  let place = 0; // the step's place in the whole flow, so the cards read as an order

  return (
    <section className={`lane ${lane.pending_approval ? "waiting" : ""}`}>
      <div className="lane-head">
        {lane.pending_approval && (
          <input
            type="checkbox"
            checked={selected}
            onChange={(e) => onSelect(e.target.checked)}
            aria-label={`select ${headline(lane.request)}`}
          />
        )}
        <div className="lane-id">
          <Link to={`/projects/${projectId}/jobs/${lane.job_id}`} className="lane-title">
            {headline(lane.request)}
          </Link>
          <div className="lane-sub">
            <StateBadge state={lane.state} />
            <span className="faint tiny">
              {tx("started {ago}", { ago: timeAgo(lane.created_at) })}
            </span>
          </div>
        </div>
        <div className="lane-progress">
          <ProgressBar done={done} total={lane.steps.length} showText={false} />
          <span className="faint tiny">
            {tx("{done} of {total} steps", { done, total: lane.steps.length })}
          </span>
        </div>
        {lane.state === "failed" && <LaneRetry jobId={lane.job_id} />}
      </div>

      <LaneBrief request={lane.request} summary={lane.summary} />

      <div className="lane-flow">
        {groups.map((group) => (
          <div key={group.key} className={`flow-stage ${stageStatus(group.steps)}`}>
            <StageHead stage={group} />
            <ol className="flow-rail">
              {group.steps.map((step, i) => (
                <li key={step.key} className="flow-node">
                  <span className={`flow-link ${i === 0 ? "first" : ""}`} aria-hidden="true" />
                  <StepCardView
                    step={step}
                    place={++place}
                    active={openKey === step.key}
                    onOpen={() => onOpen(step.key)}
                  />
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}

/** A stage's header: the icon does the naming at a glance, the line under it says what the
 * stage is for, and the count and bar say how much of it is behind you. */
function StageHead({ stage }: { stage: Stage }) {
  const tx = useT();
  const done = stage.steps.filter((s) => s.status === "done").length;
  const Icon = STAGE_ICON[stage.key] ?? IconLayers;
  return (
    <div className="flow-stage-head">
      <span className="flow-stage-icon">
        <Icon />
      </span>
      <span className="flow-stage-id">
        <span className="flow-stage-title">{tx(STAGE_LABEL[stage.key] ?? stage.key)}</span>
        <span className="flow-stage-note">{tx(STAGE_NOTE[stage.key] ?? "")}</span>
      </span>
      <span className="flow-stage-progress">
        <span className="count mono">
          {done}/{stage.steps.length}
        </span>
        <span className="track">
          <span
            className="fill"
            style={{ width: `${stage.steps.length ? (done / stage.steps.length) * 100 : 0}%` }}
          />
        </span>
      </span>
    </div>
  );
}

/** What this development is, in the space above the flow: the request as it was written,
 * two lines with the rest a click away, and under it the one line the architect settled
 * on once there is a plan. A wall of prompt as the lane's title is what made this
 * unreadable. */
function LaneBrief({ request, summary }: { request: string; summary?: string | null }) {
  const tx = useT();
  const [open, setOpen] = useState(false);
  const [clipped, setClipped] = useState(false);
  const para = useRef<HTMLParagraphElement>(null);
  const asked = request.trim();
  const plan = (summary ?? "").trim();
  // the unfold button only earns its place when two lines really do cut the request off,
  // which depends on how wide the lane is drawn -- so it is measured, not guessed
  useEffect(() => {
    const el = para.current;
    if (!el || open) return;
    const measure = () => setClipped(el.scrollHeight > el.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [asked, open]);
  if (!asked && !plan) return null;
  return (
    <div className="lane-brief">
      {asked && (
        <>
          <div className="lane-brief-label">{tx("What was asked")}</div>
          <p ref={para} className={open ? "" : "clamp-2"}>
            {asked}
          </p>
          {clipped && (
            <button type="button" className="text-btn tiny" onClick={() => setOpen(!open)}>
              {open ? tx("show less") : tx("show more")}
            </button>
          )}
        </>
      )}
      {plan && (
        <div className="lane-brief-plan">
          <span className="lane-brief-label">{tx("The plan")}</span>
          <span className="truncate">{plan}</span>
        </div>
      )}
    </div>
  );
}

function LaneRetry({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  return job.data ? <RetryActions job={job.data} compact /> : null;
}

/** Card labels come from the server in English; the fixed ones translate, a phase
 * label ("Backend: <goal>") keeps its goal and translates the agent. */
function stepLabel(tx: T, step: StepCard): string {
  const m = /^([^:]+): (.*)$/.exec(step.label);
  if (step.phase && m) return `${tx(m[1]!)}: ${m[2]!}`;
  const gate = /^Review approval: phase (\d+)$/.exec(step.label);
  if (gate) return tx("Review approval: phase {n}", { n: gate[1]! });
  return tx(step.label);
}

function elapsed(s: number | null | undefined): string {
  if (s === null || s === undefined) return "";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function StepCardView({
  step,
  place,
  active,
  onOpen,
}: {
  step: StepCard;
  place: number;
  active: boolean;
  onOpen: () => void;
}) {
  const tx = useT();
  const who = step.role ? tx(ROLE_LABEL[step.role] ?? step.role) : step.gate ? tx("you") : "";
  return (
    <button
      type="button"
      className={`step-card ${step.status} ${step.gate ? "is-gate" : ""} ${active ? "active" : ""}`}
      onClick={onOpen}
      title={step.label}
      data-agent={step.role ?? undefined}
    >
      <div className="who">
        {step.role ? (
          <span className="role-ink">
            <AgentIcon role={step.role} />
          </span>
        ) : (
          <span className="role-ink gate-ink">{step.gate ? <IconUsers /> : <IconCheck />}</span>
        )}
        {who && <span className="truncate">{who}</span>}
        <span className="step-no">{place}</span>
      </div>
      <div className="label">{stepLabel(tx, step)}</div>
      {step.task_title && <div className="task truncate">{step.task_title}</div>}
      {step.recommendation && (
        <div
          className={`chip ${step.recommendation === "approve" ? (step.risk === "low" ? "ok" : "work") : "bad"}`}
          title={`the supervisor recommends ${step.recommendation}`}
        >
          {step.recommendation === "approve" ? tx("recommends approve") : tx("recommends reject")} ·{" "}
          {(step.confidence ?? 0).toFixed(2)}
        </div>
      )}
      {step.auto_approved && <div className="chip idle">{tx("approved by supervisor")}</div>}
      <div className="meta">
        <span className={`badge ${STATUS_CLASS[step.status]} plain`}>
          {step.status === "waiting"
            ? tx("needs {pending}", { pending: tx(step.pending ?? "") })
            : tx(step.status)}
        </span>
        <DomainBadge domain={step.domain ?? undefined} />
        {step.elapsed_s !== null && step.elapsed_s !== undefined && (
          <span className="faint tiny took">{elapsed(step.elapsed_s)}</span>
        )}
      </div>
    </button>
  );
}

const STATUS_CLASS: Record<StepCard["status"], string> = {
  pending: "idle",
  running: "work",
  done: "ok",
  failed: "bad",
  waiting: "wait",
};

// -- the side panel ----------------------------------------------------------------------

function StepPanel({
  jobId,
  stepKey,
  projectId,
  onClose,
}: {
  jobId: string;
  stepKey: string;
  projectId: string;
  onClose: () => void;
}) {
  const tx = useT();
  const pipeline = usePipeline(projectId);
  const job = useJob(jobId);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const lane = pipeline.data?.lanes.find((l) => l.job_id === jobId);
  const step = lane?.steps.find((s) => s.key === stepKey);
  return (
    <aside className="drawer" role="dialog" aria-label={step?.label ?? "step"}>
      <div className="drawer-head">
        <div style={{ minWidth: 0 }}>
          <div className="faint tiny truncate">{lane?.request}</div>
          <h3 className="truncate">{step ? stepLabel(tx, step) : "…"}</h3>
        </div>
        <button className="btn ghost icon" onClick={onClose} aria-label={tx("Close")}>
          <IconX />
        </button>
      </div>
      <div className="drawer-body">
        {!step || !job.data ? (
          <Loading />
        ) : (
          <>
            <div className="row" style={{ marginBottom: 12 }}>
              <span className={`badge ${STATUS_CLASS[step.status]}`}>{step.status}</span>
              {step.role && (
                <span className="muted small">
                  {tx(ROLE_LABEL[step.role] ?? step.role)}
                  {step.elapsed_s !== null && step.elapsed_s !== undefined
                    ? ` · ${elapsed(step.elapsed_s)}`
                    : ""}
                </span>
              )}
              <Link className="small" to={`/projects/${projectId}/jobs/${jobId}`}>
                {tx("open development →")}
              </Link>
            </div>
            {step.status === "waiting" && <GateEditor job={job.data} step={step} />}
            <RerunStep
              jobId={jobId}
              projectId={projectId}
              role={step.role}
              laneState={lane?.state}
            />
            {step.outputs.map((index) => (
              <Output key={index} jobId={jobId} index={index} />
            ))}
            {step.outputs.length === 0 && step.status !== "waiting" && (
              <div className="muted small">{tx("Nothing recorded for this step yet.")}</div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

/**
 * Run a finished step again. The QA step re-runs the tests over the work that is already
 * there: green and it stops, red and the specialist picks it up with the output, which is
 * the ordinary failed-gate path. The DevOps step pushes the branch and opens the pull
 * request again — the way a development that finished with nowhere to push reaches GitHub
 * once the project names a repository.
 */
function RerunStep({
  jobId,
  projectId,
  role,
  laneState,
}: {
  jobId: string;
  projectId: string;
  role: string | null | undefined;
  laneState: string | undefined;
}) {
  const tx = useT();
  const rerun = useRerunStep(jobId, projectId);
  const step = role === "qa" ? "tests" : role === "devops" ? "devops" : null;
  // only a development that has stopped: a running one is left alone
  if (!step || (laneState !== "done" && laneState !== "failed")) return null;
  return (
    <div className="row spread" style={{ marginBottom: 12, gap: 8 }}>
      <button
        className="btn"
        disabled={rerun.isPending}
        onClick={() => rerun.mutate(step)}
        title={
          step === "tests"
            ? tx("Runs the test command over this development's worktree.")
            : tx("Writes the pull request again, pushes the branch and opens it.")
        }
      >
        {rerun.isPending
          ? tx("Starting…")
          : step === "tests"
            ? tx("Run the tests again")
            : tx("Run DevOps again")}
      </button>
      {rerun.error && <span className="small bad-text">{describeError(rerun.error)}</span>}
    </div>
  );
}

function Output({ jobId, index }: { jobId: string; index: number }) {
  const entry = useTransition(jobId, index);
  if (!entry.data) return <Loading rows={1} />;
  const note = entry.data.note ?? "";
  const open = !note.startsWith("standards");
  return (
    <details className="output" open={open}>
      <summary>{note || `${entry.data.from_state} → ${entry.data.to_state}`}</summary>
      {note.startsWith("review phase") ? (
        <ReviewDetail text={entry.data.detail ?? ""} />
      ) : (
        <Detail text={entry.data.detail} />
      )}
    </details>
  );
}

/** What the human can change before approving, with Save / Save & approve. */
function GateEditor({ job, step }: { job: Job; step: StepCard }) {
  const tx = useT();
  const approve = useApprove(job.id);
  const reject = useReject(job.id);
  const toast = useToast();
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const error = approve.error ?? reject.error;

  return (
    <div className="gate" style={{ marginBottom: 14 }}>
      <div style={{ marginBottom: 8 }}>
        {tx("Waiting for your approval of the")} <strong>{tx(step.pending ?? "")}</strong>
      </div>
      {step.key === "backlog_gate" && <BacklogGateEditor job={job} />}
      {step.key === "architecture_gate" && <ArchitectureGateEditor job={job} />}
      {step.key === "test_gate:1" && <TestCasesGateEditor job={job} />}
      {!step.editable && (
        <div className="row">
          <button
            className="btn ok small"
            disabled={approve.isPending}
            onClick={() => approve.mutate(undefined, { onSuccess: () => toast.ok("Approved") })}
          >
            <IconCheck /> {tx("Approve")}
          </button>
          {!rejecting ? (
            <button className="btn bad small" onClick={() => setRejecting(true)}>
              {tx("Reject…")}
            </button>
          ) : (
            <>
              <input
                type="text"
                placeholder={tx("what should change?")}
                value={feedback}
                autoFocus
                onChange={(e) => setFeedback(e.target.value)}
              />
              <button
                className="btn bad small"
                disabled={!feedback.trim() || reject.isPending}
                onClick={() =>
                  reject.mutate(feedback.trim(), { onSuccess: () => setRejecting(false) })
                }
              >
                {tx("Send rejection")}
              </button>
            </>
          )}
        </div>
      )}
      {error && <div className="callout error">{describeError(error)}</div>}
    </div>
  );
}

/** Shared Save / Save & approve / Reject… row for the editable gates. */
function SaveRow({
  jobId,
  dirty,
  saving,
  onSave,
  error,
}: {
  jobId: string;
  dirty: boolean;
  saving: boolean;
  onSave: () => Promise<boolean>;
  error: string | null;
}) {
  const tx = useT();
  const approve = useApprove(jobId);
  const reject = useReject(jobId);
  const toast = useToast();
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const busy = saving || approve.isPending || reject.isPending;
  const saveAndApprove = async () => {
    if (dirty && !(await onSave())) return;
    approve.mutate(undefined, { onSuccess: () => toast.ok("Approved") });
  };
  const err = error ?? (approve.error ? describeError(approve.error) : null);
  return (
    <div style={{ marginTop: 10 }}>
      <div className="row">
        <button className="btn small" disabled={!dirty || busy} onClick={() => void onSave()}>
          {saving ? tx("Saving…") : tx("Save")}
        </button>
        <button className="btn ok small" disabled={busy} onClick={() => void saveAndApprove()}>
          <IconCheck /> {dirty ? tx("Save & approve") : tx("Approve")}
        </button>
        {!rejecting ? (
          <button className="btn bad small" disabled={busy} onClick={() => setRejecting(true)}>
            {tx("Reject…")}
          </button>
        ) : (
          <>
            <input
              type="text"
              placeholder={tx("what should change?")}
              value={feedback}
              autoFocus
              onChange={(e) => setFeedback(e.target.value)}
            />
            <button
              className="btn bad small"
              disabled={!feedback.trim() || busy}
              onClick={() =>
                reject.mutate(feedback.trim(), { onSuccess: () => setRejecting(false) })
              }
            >
              {tx("Send rejection")}
            </button>
          </>
        )}
      </div>
      {err && <div className="callout error">{err}</div>}
    </div>
  );
}

function BacklogGateEditor({ job }: { job: Job }) {
  const tx = useT();
  const server = job.data.backlog as BreakdownShape | null;
  const save = useSetBacklog(job.id);
  const [draft, setDraft] = useState<BreakdownShape | null>(server);
  const [dirty, setDirty] = useState(false);
  const [seen, setSeen] = useState(server);
  if (seen !== server) {
    setSeen(server);
    if (!dirty) setDraft(server);
  }
  if (!draft) return null;
  const onSave = () =>
    new Promise<boolean>((resolve) =>
      save.mutate(draft as unknown as Record<string, unknown>, {
        onSuccess: () => {
          setDirty(false);
          resolve(true);
        },
        onError: () => resolve(false),
      }),
    );
  return (
    <>
      <p className="muted small">
        {tx(
          "Rename epics, stories and tasks or add and remove tasks; the Architect designs one phase per task from what you approve.",
        )}
      </p>
      <BacklogEditor
        value={draft}
        onChange={(next) => {
          setDraft(next);
          setDirty(true);
        }}
      />
      <SaveRow
        jobId={job.id}
        dirty={dirty}
        saving={save.isPending}
        onSave={onSave}
        error={save.error ? describeError(save.error) : null}
      />
    </>
  );
}

function ArchitectureGateEditor({ job }: { job: Job }) {
  const serverPlan = job.data.plan as PlanShape | null;
  const serverProfile = job.profile;
  const savePlan = useSetPlan(job.id);
  const saveProfile = useSetProfile(job.id);
  const [plan, setPlan] = useState<PlanShape | null>(serverPlan);
  const [profile, setProfile] = useState<Profile | null>(serverProfile ?? null);
  const [dirtyPlan, setDirtyPlan] = useState(false);
  const [dirtyProfile, setDirtyProfile] = useState(false);
  const [seen, setSeen] = useState({ plan: serverPlan, profile: serverProfile });
  if (seen.plan !== serverPlan || seen.profile !== serverProfile) {
    setSeen({ plan: serverPlan, profile: serverProfile });
    if (!dirtyPlan) setPlan(serverPlan);
    if (!dirtyProfile) setProfile(serverProfile ?? null);
  }
  const [tab, setTab] = useState<"plan" | "profile">("plan");
  if (!plan) return null;

  const onSave = async () => {
    if (dirtyPlan) {
      const ok = await new Promise<boolean>((resolve) =>
        savePlan.mutate(
          {
            summary: plan.summary ?? null,
            decisions: plan.decisions ?? null,
            phases: plan.phases as unknown as Record<string, unknown>[],
            breakdown: (plan.breakdown ?? null) as unknown as Record<string, unknown> | null,
          },
          { onSuccess: () => resolve(true), onError: () => resolve(false) },
        ),
      );
      if (!ok) return false;
      setDirtyPlan(false);
    }
    if (dirtyProfile && profile) {
      const ok = await new Promise<boolean>((resolve) =>
        saveProfile.mutate(profile, {
          onSuccess: () => resolve(true),
          onError: () => resolve(false),
        }),
      );
      if (!ok) return false;
      setDirtyProfile(false);
    }
    return true;
  };
  const error = savePlan.error
    ? describeError(savePlan.error)
    : saveProfile.error
      ? describeError(saveProfile.error)
      : null;

  return (
    <>
      {plan.summary && <p className="small">{plan.summary}</p>}
      {plan.decisions && plan.decisions.length > 0 && (
        <ul className="small" style={{ margin: "4px 0 10px 18px" }}>
          {plan.decisions.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      )}
      <nav className="tabs small" style={{ marginBottom: 10 }}>
        <a className={tab === "plan" ? "active" : ""} onClick={() => setTab("plan")}>
          Phases{dirtyPlan ? " •" : ""}
        </a>
        <a className={tab === "profile" ? "active" : ""} onClick={() => setTab("profile")}>
          Profile{dirtyProfile ? " •" : ""}
        </a>
      </nav>
      {tab === "plan" && (
        <PlanEditor
          value={plan}
          onChange={(next) => {
            setPlan(next);
            setDirtyPlan(true);
          }}
        />
      )}
      {tab === "profile" && profile && (
        <ProfileForm
          value={profile}
          onChange={(next) => {
            setProfile(next);
            setDirtyProfile(true);
          }}
        />
      )}
      <SaveRow
        jobId={job.id}
        dirty={dirtyPlan || dirtyProfile}
        saving={savePlan.isPending || saveProfile.isPending}
        onSave={onSave}
        error={error}
      />
    </>
  );
}

function TestCasesGateEditor({ job }: { job: Job }) {
  const tx = useT();
  const server = job.data.test_cases as unknown as TestCaseShape[];
  const save = useSetTestCases(job.id);
  const [draft, setDraft] = useState<TestCaseShape[]>(server);
  const [dirty, setDirty] = useState(false);
  const [seen, setSeen] = useState(server);
  if (seen !== server) {
    setSeen(server);
    if (!dirty) setDraft(server);
  }
  const onSave = () =>
    new Promise<boolean>((resolve) =>
      save.mutate(
        draft.filter((c) => c.name.trim() && c.description.trim()),
        {
          onSuccess: () => {
            setDirty(false);
            resolve(true);
          },
          onError: () => resolve(false),
        },
      ),
    );
  return (
    <>
      <p className="muted small">
        {tx("QA proposed these cases; edit the list, then approve it.")}
      </p>
      <TestCasesEditor
        value={draft}
        onChange={(next) => {
          setDraft(next);
          setDirty(true);
        }}
      />
      <SaveRow
        jobId={job.id}
        dirty={dirty}
        saving={save.isPending}
        onSave={onSave}
        error={save.error ? describeError(save.error) : null}
      />
    </>
  );
}
