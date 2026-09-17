// The project's pipeline: one lane per development, a row of step cards each, coloured
// by state. Cards waiting for the human carry a checkbox for bulk approval; clicking any
// card opens a side panel with that step's output, and editable gates edit in place.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { describeError, type Job, type Lane, type Profile, type StepCard } from "../api/client";
import {
  useApprove,
  useJob,
  usePipeline,
  useReject,
  useSetBacklog,
  useSetPlan,
  useSetProfile,
  useSetTestCases,
  useTransition,
} from "../api/hooks";
import { AgentIcon, DomainBadge, ROLE_LABEL } from "../components/agents";
import { BulkBar } from "../components/BulkBar";
import { Detail } from "../components/Detail";
import {
  BacklogEditor,
  PlanEditor,
  TestCasesEditor,
  type BreakdownShape,
  type PlanShape,
  type TestCaseShape,
} from "../components/GateEditors";
import { IconCheck, IconX } from "../components/icons";
import { ProfileForm } from "../components/ProfileForm";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, Loading, StateBadge, timeAgo } from "../components/ui";

export function PipelineTab({ projectId }: { projectId: string }) {
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

  if (pipeline.isLoading) return <Loading rows={4} />;
  if (pipeline.error) return <ErrorBox error={pipeline.error} />;
  if (lanes.length === 0) {
    return (
      <Empty
        title="No development yet"
        action={
          <Link className="btn primary" to={`/projects/${projectId}/developments`}>
            Start one
          </Link>
        }
      >
        Every development shows up here as a lane of steps: what the agents did, what runs now, and
        what waits for you.
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
            ? "Nothing waits for you."
            : `${waiting.size} development${waiting.size === 1 ? "" : "s"} waiting for your approval`}
        </div>
        {waiting.size > 0 && (
          <button
            className="btn small"
            onClick={() => setSelected([...waiting])}
            disabled={selected.length === waiting.size}
          >
            Select all waiting
          </button>
        )}
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
  return (
    <div className={`lane ${lane.pending_approval ? "waiting" : ""}`}>
      <div className="lane-head">
        {lane.pending_approval ? (
          <input
            type="checkbox"
            checked={selected}
            onChange={(e) => onSelect(e.target.checked)}
            aria-label={`select ${lane.request}`}
          />
        ) : (
          <span style={{ width: 16 }} />
        )}
        <Link to={`/projects/${projectId}/jobs/${lane.job_id}`} className="lane-title truncate">
          {lane.request}
        </Link>
        <StateBadge state={lane.state} />
        <span className="faint tiny">started {timeAgo(lane.created_at)}</span>
      </div>
      <div className="lane-steps">
        {lane.steps.map((step) => (
          <StepCardView
            key={step.key}
            step={step}
            active={openKey === step.key}
            onOpen={() => onOpen(step.key)}
          />
        ))}
      </div>
    </div>
  );
}

function elapsed(s: number | null | undefined): string {
  if (s === null || s === undefined) return "";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function StepCardView({
  step,
  active,
  onOpen,
}: {
  step: StepCard;
  active: boolean;
  onOpen: () => void;
}) {
  const who = step.role ? (ROLE_LABEL[step.role] ?? step.role) : step.gate ? "you" : "";
  return (
    <button
      type="button"
      className={`step-card ${step.status} ${step.gate ? "is-gate" : ""} ${active ? "active" : ""}`}
      onClick={onOpen}
      title={step.label}
    >
      <div className="who">
        {step.role ? <AgentIcon role={step.role} /> : null}
        <span>{who}</span>
        {step.status === "running" && <span className="pulse-dot" aria-label="running" />}
      </div>
      <div className="label">{step.label}</div>
      {step.task_title && <div className="task truncate">{step.task_title}</div>}
      <div className="meta">
        <span className={`badge ${STATUS_CLASS[step.status]} plain`}>
          {step.status === "waiting" ? `needs ${step.pending}` : step.status}
        </span>
        <DomainBadge domain={step.domain ?? undefined} />
        {step.elapsed_s !== null && step.elapsed_s !== undefined && (
          <span className="faint tiny">{elapsed(step.elapsed_s)}</span>
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
          <h3 className="truncate">{step?.label ?? "…"}</h3>
        </div>
        <button className="btn ghost icon" onClick={onClose} aria-label="Close">
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
                  {ROLE_LABEL[step.role] ?? step.role}
                  {step.elapsed_s !== null && step.elapsed_s !== undefined
                    ? ` · ${elapsed(step.elapsed_s)}`
                    : ""}
                </span>
              )}
              <Link className="small" to={`/projects/${projectId}/jobs/${jobId}`}>
                open development →
              </Link>
            </div>
            {step.status === "waiting" && <GateEditor job={job.data} step={step} />}
            {step.outputs.map((index) => (
              <Output key={index} jobId={jobId} index={index} />
            ))}
            {step.outputs.length === 0 && step.status !== "waiting" && (
              <div className="muted small">Nothing recorded for this step yet.</div>
            )}
          </>
        )}
      </div>
    </aside>
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
      <Detail text={entry.data.detail} />
    </details>
  );
}

/** What the human can change before approving, with Save / Save & approve. */
function GateEditor({ job, step }: { job: Job; step: StepCard }) {
  const approve = useApprove(job.id);
  const reject = useReject(job.id);
  const toast = useToast();
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const error = approve.error ?? reject.error;

  return (
    <div className="gate" style={{ marginBottom: 14 }}>
      <div style={{ marginBottom: 8 }}>
        Waiting for your approval of the <strong>{step.pending}</strong>.
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
            <IconCheck /> Approve
          </button>
          {!rejecting ? (
            <button className="btn bad small" onClick={() => setRejecting(true)}>
              Reject…
            </button>
          ) : (
            <>
              <input
                type="text"
                placeholder="what should change?"
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
                Send rejection
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
          {saving ? "Saving…" : "Save"}
        </button>
        <button className="btn ok small" disabled={busy} onClick={() => void saveAndApprove()}>
          <IconCheck /> {dirty ? "Save & approve" : "Approve"}
        </button>
        {!rejecting ? (
          <button className="btn bad small" disabled={busy} onClick={() => setRejecting(true)}>
            Reject…
          </button>
        ) : (
          <>
            <input
              type="text"
              placeholder="what should change?"
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
              Send rejection
            </button>
          </>
        )}
      </div>
      {err && <div className="callout error">{err}</div>}
    </div>
  );
}

function BacklogGateEditor({ job }: { job: Job }) {
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
        Rename epics, stories and tasks or add and remove tasks; the Architect designs one phase per
        task from what you approve.
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
      <p className="muted small">QA proposed these cases; edit the list, then approve it.</p>
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
