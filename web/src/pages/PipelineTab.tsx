// The project's pipeline: one lane per development. A lane is a single line -- what was
// asked, where it got to, how far along -- with "Details" on the right; ten developments
// are ten lines instead of ten walls of step cards. Opening one unfolds the development's
// own detail in place: the four stages, whatever needs a decision, and the tabs, the same
// view its page shows. The step-by-step flow -- the cards grouped into stages and linked
// by arrows, with a side panel per step -- is the first of those tabs.
import { useEffect, useMemo, useRef, useState } from "react";
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
import { DesignGate } from "../components/DesignGate";
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
import { IconCheck, IconChevron, IconLayers, IconUsers, IconX } from "../components/icons";
import { ProfileForm } from "../components/ProfileForm";
import {
  STAGE_ICON,
  STAGE_LABEL,
  STAGE_NOTE,
  stageAgent,
  stageStatus,
  stages,
  type Stage,
} from "../components/stages";
import { StepDetailView } from "../components/StepDetail";
import { useToast } from "../components/Toast";
import {
  Empty,
  ErrorBox,
  Loading,
  Pager,
  ProgressBar,
  StateBadge,
  sentence,
  timeAgo,
} from "../components/ui";
import { useT, type T } from "../i18n";
import { useSay } from "../i18n/said";
import { JobDetail } from "./JobPage";

/** How many developments a page of the pipeline shows: the ten most recent, newest first. */
const PAGE_SIZE = 10;

export function PipelineTab({ projectId }: { projectId: string }) {
  const tx = useT();
  const pipeline = usePipeline(projectId);
  const [chosen, setSelected] = useState<string[]>([]);
  const [open, setOpen] = useState<{ jobId: string; key: string } | null>(null);
  const [wanted, setPage] = useState(0);
  const lanes = useMemo(() => pipeline.data?.lanes ?? [], [pipeline.data]);
  // a development finishing can empty the page you are standing on, so the page is clamped
  // here rather than corrected afterwards: the last page always has something on it
  const page = Math.min(wanted, Math.max(0, Math.ceil(lanes.length / PAGE_SIZE) - 1));
  // the page the list actually shows; the selection and the counts above still read every lane
  const shown = useMemo(
    () => lanes.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE),
    [lanes, page],
  );

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
      {shown.map((lane) => (
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
      <Pager
        page={page}
        pageSize={PAGE_SIZE}
        total={lanes.length}
        onPage={(n) => {
          setOpen(null);
          setPage(n);
        }}
      />
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

/** The colour of the arrow into a step: the state of the step it comes from. */
function linkState(previous: StepCard | undefined): string {
  if (previous?.status === "done") return "done";
  if (previous?.status === "running") return "running";
  return "";
}

/** A one-line title for a development whose request is a paragraph: the first sentence,
 * clipped. The whole request is right below it, so nothing is lost by cutting here. */
function headline(request: string): string {
  const first = request.trim().split(/\r?\n/, 1)[0]!.trim();
  const stop = first.search(/[;:.!?](\s|$)/);
  const title = sentence(stop > 12 ? first.slice(0, stop) : first);
  return title.length > 76 ? `${title.slice(0, 73).trimEnd()}…` : title;
}

/** Keeps a click on a control inside the head from also folding the lane. */
const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

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
  const done = lane.steps.filter((s) => s.status === "done").length;
  // closed is the resting state: the tab is a list of developments until you ask for one
  const [open, setOpen] = useState(false);

  return (
    <section className={`lane ${lane.pending_approval ? "waiting" : ""} ${open ? "open" : ""}`}>
      {/* the whole head is the target: the title used to be a link to the development's own
          page, which is a second way to say "detail" right next to the button that says it */}
      <div className="lane-head" onClick={() => setOpen(!open)}>
        {lane.pending_approval && (
          <input
            type="checkbox"
            checked={selected}
            onChange={(e) => onSelect(e.target.checked)}
            onClick={stop}
            aria-label={`select ${headline(lane.request)}`}
          />
        )}
        <div className="lane-id">
          <span className="lane-title">{headline(lane.request)}</span>
          <div className="lane-sub">
            <StateBadge state={lane.state} />
            {/* the badge says what kind of work is happening; this says whose, which is
                the question "build gate" on its own never answered */}
            {lane.running_label && (
              <span className="lane-running" data-agent={lane.running_role ?? undefined}>
                {lane.running_role && (
                  <span className="role-ink">
                    <AgentIcon role={lane.running_role} />
                  </span>
                )}
                <span className="truncate">{stepTitle(tx, lane.running_label)}</span>
              </span>
            )}
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
        {/* the failure is spelled out inside the detail, so the shortcut is for the
            closed lane, where nothing else offers it */}
        {lane.state === "failed" && !open && (
          <span onClick={stop}>
            <LaneRetry jobId={lane.job_id} />
          </span>
        )}
        {/* the button is what a keyboard reaches; the click on the head is the mouse's */}
        <button type="button" className="lane-toggle" aria-expanded={open}>
          {tx("Details")}
          <IconChevron />
        </button>
      </div>

      {open && (
        <div className="lane-detail">
          <LaneBrief request={lane.request} summary={lane.summary} />
          <LaneDetail lane={lane} projectId={projectId} onOpen={onOpen} openKey={openKey} />
        </div>
      )}
    </section>
  );
}

/** The development's own detail, drawn inside the lane: the same four stages, gate and tabs
 * its page shows. The job is only fetched once the lane is opened -- a project with twenty
 * developments would otherwise fetch twenty of them to draw a list. */
function LaneDetail({
  lane,
  projectId,
  onOpen,
  openKey,
}: {
  lane: Lane;
  projectId: string;
  onOpen: (key: string) => void;
  openKey: string | null;
}) {
  const job = useJob(lane.job_id);
  if (job.isLoading) return <Loading rows={3} />;
  if (job.error) return <ErrorBox error={job.error} />;
  if (!job.data) return null;
  return (
    <JobDetail
      job={job.data}
      projectId={projectId}
      flow={<LaneFlow lane={lane} onOpen={onOpen} openKey={openKey} />}
    />
  );
}

/** The flow itself: the steps under the stage they belong to, linked left to right, each
 * card coloured by state and opening a side panel with that step's output. */
function LaneFlow({
  lane,
  onOpen,
  openKey,
}: {
  lane: Lane;
  onOpen: (key: string) => void;
  openKey: string | null;
}) {
  const groups = useMemo(() => stages(lane.steps), [lane.steps]);
  let place = 0; // the step's place in the whole flow, so the cards read as an order
  return (
    <div className="lane-flow">
      {groups.map((group) => (
        <div
          key={group.key}
          className={`flow-stage ${stageStatus(group.steps)}`}
          data-agent={stageAgent(group.steps)}
        >
          <StageHead stage={group} />
          <ol className="flow-rail">
            {group.steps.map((step, i) => (
              <li key={step.key} className="flow-node">
                {/* the arrow carries the state of the step it comes from, so the flow is
                    green up to the card the work is sitting on */}
                <span
                  className={`flow-link ${i === 0 ? "first" : linkState(group.steps[i - 1])}`}
                  aria-hidden="true"
                />
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
  );
}

/** A stage's header: the icon does the naming at a glance, the line under it says what the
 * stage is for, and the count and bar say how much of it is behind you. */
function StageHead({ stage }: { stage: Stage }) {
  const tx = useT();
  const done = stage.steps.filter((s) => s.status === "done").length;
  const Icon = STAGE_ICON[stage.key] ?? IconLayers;
  const agent = stageAgent(stage.steps);
  return (
    <div className="flow-stage-head">
      <span className="flow-stage-icon">{agent ? <AgentIcon role={agent} /> : <Icon />}</span>
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

/** What this development is, in the space above the flow: the request as it was written
 * and, once there is a plan, the one the architect settled on -- each labelled, two lines,
 * the rest a click away. A wall of prompt as the lane's title is what made this
 * unreadable, and the plan squeezed onto a single clipped line said just as little. */
function LaneBrief({ request, summary }: { request: string; summary?: string | null }) {
  const tx = useT();
  const say = useSay();
  const asked = request.trim(); // the person's own words, shown as they typed them
  const plan = say(summary ?? "").trim();
  if (!asked && !plan) return null;
  return (
    <div className="lane-brief">
      {asked && <BriefPart label={tx("What was asked")} text={asked} />}
      {plan && <BriefPart label={tx("The plan")} text={plan} className="lane-brief-plan" />}
    </div>
  );
}

/** One labelled piece of the brief: two lines, and an unfold button that only earns its
 * place when two lines really do cut the text off -- which depends on how wide the lane
 * is drawn and on how long the same sentence runs in the language it was written in, so
 * it is measured, not guessed. */
function BriefPart({
  label,
  text,
  className,
}: {
  label: string;
  text: string;
  className?: string;
}) {
  const tx = useT();
  const [open, setOpen] = useState(false);
  const [clipped, setClipped] = useState(false);
  const para = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    const el = para.current;
    if (!el || open) return;
    const measure = () => setClipped(el.scrollHeight > el.clientHeight + 1);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, open]);
  return (
    <div className={className}>
      <div className="lane-brief-label">{label}</div>
      <p ref={para} className={open ? "" : "clamp-2"}>
        {text}
      </p>
      {clipped && (
        <button type="button" className="text-btn tiny" onClick={() => setOpen(!open)}>
          {open ? tx("show less") : tx("show more")}
        </button>
      )}
    </div>
  );
}

function LaneRetry({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  return job.data ? <RetryActions job={job.data} /> : null;
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

/** A running step's label in the lane header: the agent translated, its goal clipped.
 *  "Backend Developer: add the endpoint" is the whole card's title; here there is room
 *  for who and roughly what, not the sentence. */
function stepTitle(tx: T, label: string): string {
  const m = /^([^:]+): (.*)$/.exec(label);
  if (!m) return tx(label);
  const goal = m[2]!.trim();
  return `${tx(m[1]!)} · ${goal.length > 48 ? `${goal.slice(0, 48)}…` : goal}`;
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
  const say = useSay();
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
      {step.task_title && <div className="task truncate">{say(step.task_title)}</div>}
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
          <div className="faint tiny truncate">{lane && sentence(lane.request)}</div>
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
              <span className={`badge ${STATUS_CLASS[step.status]}`}>{tx(step.status)}</span>
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
            {/* the screens are worth seeing after they are signed off too */}
            {step.key === "design" && <DesignGate jobId={jobId} readOnly />}
            {step.status === "failed" && (
              <div className="gate" style={{ marginBottom: 12 }}>
                <div className="muted small" style={{ marginBottom: 8 }}>
                  {tx("Retry continues from the step that failed")}
                </div>
                <RetryActions job={job.data} />
              </div>
            )}
            <RerunStep
              jobId={jobId}
              projectId={projectId}
              stepKey={step.key}
              laneState={lane?.state}
            />
            <StepDetailView jobId={jobId} stepKey={step.key} />
            {step.outputs.length > 0 && (
              <details className="step-raw">
                <summary>{tx("The agent's record, as it was written")}</summary>
                {step.outputs.map((index) => (
                  <Output key={index} jobId={jobId} index={index} />
                ))}
              </details>
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
/** What re-running this card actually does. The two QA cards are different steps and used
 * to share one button: on "QA: test cases" it said it would run the tests again and then
 * ran the test command, which can never produce the scenarios that card is about. Each
 * card now offers its own step, or none. */
const RERUN: Record<
  string,
  { step: "test_cases" | "tests" | "devops"; label: string; hint: string }
> = {
  "qa:1": {
    step: "test_cases",
    label: "Propose the test cases again",
    hint: "Asks QA for the list of scenarios again, from the top.",
  },
  "qa:2": {
    step: "tests",
    label: "Run the tests again",
    hint: "Runs the test command over this development's worktree.",
  },
  devops: {
    step: "devops",
    label: "Run DevOps again",
    hint: "Writes the pull request again, pushes the branch and opens it.",
  },
};

function RerunStep({
  jobId,
  projectId,
  stepKey,
  laneState,
}: {
  jobId: string;
  projectId: string;
  stepKey: string;
  laneState: string | undefined;
}) {
  const tx = useT();
  const rerun = useRerunStep(jobId, projectId);
  const action = RERUN[stepKey];
  // only a development that has stopped: a running one is left alone
  if (!action || (laneState !== "done" && laneState !== "failed")) return null;
  return (
    <div className="row spread" style={{ marginBottom: 12, gap: 8 }}>
      <button
        className="btn"
        disabled={rerun.isPending}
        onClick={() => rerun.mutate(action.step)}
        title={tx(action.hint)}
      >
        {rerun.isPending ? tx("Starting…") : tx(action.label)}
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
      {step.key === "design_gate" && <DesignGate jobId={job.id} />}
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
  // the summary and the decisions are read here, so they follow the platform's language;
  // the phase goals below are edited and saved, so the editor keeps the project's words
  const tx = useT();
  const say = useSay();
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
      {plan.summary && <p className="small">{say(plan.summary)}</p>}
      {plan.decisions && plan.decisions.length > 0 && (
        <ul className="small" style={{ margin: "4px 0 10px 18px" }}>
          {plan.decisions.map((d, i) => (
            <li key={i}>{say(d)}</li>
          ))}
        </ul>
      )}
      <nav className="tabs small" style={{ marginBottom: 10 }}>
        <a className={tab === "plan" ? "active" : ""} onClick={() => setTab("plan")}>
          {tx("Phases")}
          {dirtyPlan ? " •" : ""}
        </a>
        <a className={tab === "profile" ? "active" : ""} onClick={() => setTab("profile")}>
          {tx("Preferences")}
          {dirtyProfile ? " •" : ""}
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
