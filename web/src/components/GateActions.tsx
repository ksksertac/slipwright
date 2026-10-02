import { useState } from "react";
import { describeError, type Job } from "../api/client";
import { hasFinished } from "./ui";
import {
  useApprove,
  useCancelJob,
  useMyTeam,
  useReject,
  useReplanJob,
  useRetryJob,
  useSkipDeployment,
  useSkipTests,
} from "../api/hooks";
import { isOwner, mayActAt } from "../api/gates";
import { IconStop } from "./icons";
import { Modal } from "./Modal";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";

export function pendingApproval(job: Job): string | null {
  switch (job.state) {
    case "awaiting_backlog_approval":
      return "backlog";
    case "awaiting_architecture_approval":
      return "architecture";
    case "awaiting_design_approval":
      return "design";
    case "awaiting_review_approval":
      return "review";
    case "awaiting_decision":
      return "decision";
    case "awaiting_deploy_approval":
      return "deployment";
    case "awaiting_test_approval":
      return job.data.qa_stage === 1 ? "test cases" : "written tests";
    default:
      return null;
  }
}

/** The real failure of a failed job: the transition that entered `failed`, not the
 * bookkeeping (Jira sync, retrieval) recorded on it afterwards. */
export function failureOf(job: Job) {
  return [...job.history]
    .reverse()
    .find((t) => t.to_state === "failed" && t.from_state !== "failed");
}

/** What a failed development can be offered: carry on from where it stopped, or -- when the
 * plan itself is what failed -- have it planned a different way, which is where a note
 * belongs. */
/** Stopping a development, wherever it is. Not a failure and not a step: the answer to
 *  "this is not worth what it is spending", which can be true mid-phase or at a gate
 *  nobody is going to answer. Whatever call is in flight finishes -- it is already paid
 *  for -- and nothing further starts. The owner's, like retry and replan. */
export function StopAction({
  job,
  compact = false,
  lane = false,
}: {
  job: Job;
  compact?: boolean;
  /** drawn in a lane's head, as the twin of the Details button beside it */
  lane?: boolean;
}) {
  const tx = useT();
  const stop = useCancelJob(job.id);
  const team = useMyTeam();
  const [sure, setSure] = useState(false);
  const running = !hasFinished(job.state);
  if (!running || !isOwner(team.data)) return null;
  if (lane) {
    return sure ? (
      <span className="lane-confirm">
        <button
          type="button"
          className="lane-btn danger"
          disabled={stop.isPending}
          onClick={() => stop.mutate(undefined, { onSettled: () => setSure(false) })}
        >
          <IconStop />
          {stop.isPending ? tx("Stopping…") : tx("Yes, stop it")}
        </button>
        <button type="button" className="lane-btn" onClick={() => setSure(false)}>
          {tx("Cancel")}
        </button>
        {stop.error && <span className="error small">{describeError(stop.error)}</span>}
      </span>
    ) : (
      <button
        type="button"
        className="lane-btn lane-stop"
        onClick={() => setSure(true)}
        title={tx("stop this development; what it has built stays")}
      >
        <IconStop />
        {tx("Stop")}
      </button>
    );
  }
  if (!sure) {
    return (
      <button
        className={`btn ghost ${compact ? "tiny" : "small"}`}
        onClick={() => setSure(true)}
        title={tx("stop this development; what it has built stays")}
      >
        {tx("Stop")}
      </button>
    );
  }
  return (
    <span className="row">
      <button
        className={`btn bad ${compact ? "tiny" : "small"}`}
        disabled={stop.isPending}
        onClick={() => stop.mutate(undefined, { onSettled: () => setSure(false) })}
      >
        {stop.isPending ? tx("Stopping…") : tx("Yes, stop it")}
      </button>
      <button className={`btn ${compact ? "tiny" : "small"}`} onClick={() => setSure(false)}>
        {tx("Cancel")}
      </button>
      {stop.error && <span className="error small">{describeError(stop.error)}</span>}
    </span>
  );
}

export function RetryActions({ job }: { job: Job }) {
  const tx = useT();
  const retry = useRetryJob(job.id);
  const team = useMyTeam();
  const [replanning, setReplanning] = useState(false);
  // a development that has stopped is moved by whoever owns the account: a member holds
  // an agent, and a failed job is not waiting at anybody's gate
  if (job.state !== "failed" || !isOwner(team.data)) return null;
  return (
    <div className="row">
      <button
        className="btn primary small"
        disabled={retry.isPending}
        onClick={() => retry.mutate(null)}
        title={tx("continue from the step that failed; what was built stays")}
      >
        {retry.isPending ? tx("Retrying…") : tx("Retry")}
      </button>
      <button className="btn small" onClick={() => setReplanning(true)}>
        {tx("Try a different way…")}
      </button>
      {retry.error && <span className="error small">{describeError(retry.error)}</span>}
      {replanning && <ReplanModal job={job} onClose={() => setReplanning(false)} />}
    </div>
  );
}

/** Retrying continues with the same plan and the same phase, which is the right answer when
 * the step was unlucky and the wrong one when the plan is what failed -- a phase whose scope
 * cannot reach the error, a task nobody wrote down. This is the other door: what you say
 * here goes to the Product Owner with the failure beside it, the backlog can gain the task
 * it was missing, the Architect plans the phases again, and both come back to you at the
 * usual gates. The branch and everything already committed on it stay. */
function ReplanModal({ job, onClose }: { job: Job; onClose: () => void }) {
  const tx = useT();
  const replan = useReplanJob(job.id);
  const [note, setNote] = useState("");
  const last = failureOf(job);
  return (
    <Modal title={tx("Try a different way")} onClose={onClose} wide>
      <p className="muted small">
        {tx(
          "Say what should be tried instead. It goes to the Product Owner together with what failed: the backlog is written again and can gain tasks it was missing, the Architect plans the phases again, and you approve both as usual. The branch and everything built on it stay.",
        )}
      </p>
      {last?.note && (
        <div className="callout" style={{ display: "block", marginBottom: 12 }}>
          <div className="faint tiny">{tx("What failed")}</div>
          <div className="small">{last.note}</div>
        </div>
      )}
      <textarea
        autoFocus
        rows={6}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={tx(
          "e.g. split the API phase in two and let the routing package be exported in its own phase",
        )}
      />
      {replan.error && <div className="error small">{describeError(replan.error)}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button
          className="btn primary"
          disabled={!note.trim() || replan.isPending}
          onClick={() => replan.mutate(note.trim(), { onSuccess: onClose })}
        >
          {replan.isPending ? tx("Planning…") : tx("Plan it again")}
        </button>
        <button className="btn ghost" onClick={onClose}>
          {tx("Cancel")}
        </button>
        <span className="faint small">
          {tx("Nothing is thrown away; the phases are simply walked again from the first.")}
        </span>
      </div>
    </Modal>
  );
}

type Supervision = {
  decision?: string;
  confidence?: number;
  risk?: string;
  reasons?: string[];
  feedback?: string;
  acted?: string;
  blockers?: string[];
  error?: string;
};

/** What the supervisor said about the gate this job is waiting at, or null when it did not
 *  speak, could not be reached, or already acted on its own. */
function supervision(job: Job): Supervision | null {
  const s = job.data.supervision as Supervision | null | undefined;
  if (!s || !pendingApproval(job) || !s.decision || s.acted !== "none") return null;
  return s;
}

/** The rewrite the supervisor asked for, as it wrote it. Never translated: it is about to
 *  become the person's own feedback, which is saved and read by the agent that continues. */
function suggestedFeedback(job: Job): string {
  const s = supervision(job);
  return s && s.decision !== "approve" ? (s.feedback ?? "").trim() : "";
}

/** The supervisor's view of the gate the job waits at (assisted / auto modes). */
export function Recommendation({ job, detailed = false }: { job: Job; detailed?: boolean }) {
  const tx = useT();
  // the reasons and the suggested feedback are the supervisor's own prose
  const say = useSay();
  const s = job.data.supervision as Supervision | null | undefined;
  if (!s || !pendingApproval(job)) return null;
  if (s.acted === "error") {
    return (
      <span className="badge plain idle" title={s.error ?? ""}>
        {tx("supervisor unavailable")}
      </span>
    );
  }
  if (!s.decision || s.acted !== "none") return null;
  const cls = s.decision === "approve" ? (s.risk === "low" ? "ok" : "work") : "bad";
  const chip = (
    <span className={`badge plain ${cls}`} title={(s.reasons ?? []).join("; ")}>
      {tx("supervisor recommends {decision} · {confidence} · risk {risk}", {
        decision: tx(s.decision),
        confidence: (s.confidence ?? 0).toFixed(2),
        risk: tx(s.risk ?? ""),
      })}
    </span>
  );
  if (!detailed) return chip;
  return (
    <div className="recommendation">
      {chip}
      {s.reasons && s.reasons.length > 0 && (
        <ul className="small" style={{ margin: "6px 0 0 18px" }}>
          {s.reasons.map((r, i) => (
            <li key={i}>{say(r)}</li>
          ))}
        </ul>
      )}
      {s.decision === "reject" && s.feedback && (
        <div className="small muted" style={{ marginTop: 4 }}>
          {tx("suggested feedback: ")}
          {say(s.feedback)}
        </div>
      )}
      {s.blockers && s.blockers.length > 0 && (
        <div className="small muted" style={{ marginTop: 4 }}>
          {tx("not approved automatically: ")}
          {s.blockers.join(", ")}
        </div>
      )}
    </div>
  );
}

/** Approve / reject buttons for a job at a gate; reject asks for feedback inline. */
export function GateActions({ job, compact = false }: { job: Job; compact?: boolean }) {
  const tx = useT();
  const approve = useApprove(job.id);
  const reject = useReject(job.id);
  const skipTests = useSkipTests(job.id);
  const skipDeployment = useSkipDeployment(job.id);
  const team = useMyTeam();
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  // writing the tests is the most expensive step in a development, so the test-cases gate
  // has a third answer: not "these cases are wrong" but "this one is not worth testing".
  // Rejecting keeps the meaning it has everywhere else -- QA writes the cases again.
  const canSkipTests = job.state === "awaiting_test_approval" && job.data.qa_stage === 1;
  // the same at the deployment gate: somebody who deploys by hand, or not at all, has no
  // proposal they would accept, and rejecting only pays DevOps to propose again
  const canSkipDeployment = job.state === "awaiting_deploy_approval";
  // What the supervisor asked for, already written out. Retyping a numbered paragraph of
  // it into the box was the only way to act on it, so the box opens holding it -- to send
  // as it stands, to edit, or to clear and say something else entirely.
  const suggested = suggestedFeedback(job);
  const openReject = () => {
    setFeedback((typed) => typed || suggested);
    setRejecting(true);
  };
  const pending = pendingApproval(job);
  if (!pending) return null;
  // somebody who holds another agent sees the gate and who it belongs to, but not the
  // buttons: the server would refuse them, and a button that cannot work is a lie
  if (!mayActAt(job.state, team.data)) {
    return compact ? null : (
      <div className="gate">
        <span className="muted small">
          {tx("Waiting for the {agent} agent.", { agent: tx(pending) })}
        </span>
      </div>
    );
  }
  const error = approve.error ?? reject.error ?? skipTests.error ?? skipDeployment.error;
  if (job.state === "awaiting_decision" && job.data.decision_kind === "phase_budget") {
    return <BudgetAnswer job={job} compact={compact} />;
  }

  return (
    <div className={compact ? "row" : "gate"}>
      {!compact && (
        <div style={{ marginBottom: 8 }}>
          {tx("Waiting for your approval of the")} <strong>{tx(pending)}</strong>
        </div>
      )}
      <div className="row">
        <button
          className="btn ok small"
          disabled={approve.isPending}
          onClick={() => approve.mutate()}
          title={suggested ? tx("the supervisor asked for changes; approving sets them aside") : ""}
        >
          {tx("Approve")} · {tx(pending)}
        </button>
        {!rejecting ? (
          <>
            {suggested && (
              <button
                className="btn bad small"
                disabled={reject.isPending}
                onClick={() => reject.mutate(suggested, { onSuccess: () => setFeedback("") })}
                title={suggested}
              >
                {reject.isPending ? tx("Sending…") : tx("Send the supervisor's changes")}
              </button>
            )}
            <button className="btn bad small" onClick={openReject}>
              {suggested ? tx("Reject, my own words…") : tx("Reject…")}
            </button>
            {canSkipTests && (
              <button
                className="btn small"
                disabled={skipTests.isPending}
                onClick={() => skipTests.mutate()}
                title={tx(
                  "no tests are written and the development goes straight to delivery; the cases stay on the record",
                )}
              >
                {skipTests.isPending ? tx("Skipping…") : tx("Go on without tests")}
              </button>
            )}
            {canSkipDeployment && <SkipDeploymentButton mutation={skipDeployment} />}
          </>
        ) : (
          <>
            <textarea
              rows={compact ? 4 : 6}
              style={{ width: compact ? 260 : 480 }}
              placeholder={tx("what should change?")}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              autoFocus
            />
            <button
              className="btn bad small"
              disabled={!feedback.trim() || reject.isPending}
              onClick={() => {
                reject.mutate(feedback.trim(), {
                  onSuccess: () => {
                    setRejecting(false);
                    setFeedback("");
                  },
                });
              }}
            >
              {tx("Send rejection")}
            </button>
            <button className="btn small" onClick={() => setRejecting(false)}>
              {tx("Cancel")}
            </button>
          </>
        )}
      </div>
      {suggested && !rejecting && (
        <div className="faint small" style={{ marginTop: 6 }}>
          {tx("The supervisor asked for changes. Approving goes ahead without them.")}
        </div>
      )}
      {error && <div className="callout error">{describeError(error)}</div>}
    </div>
  );
}

/**
 * A phase that spent its budget of calls (T15.5) waits for words, not a yes: a plain
 * "continue" would spend another budget the same way. The box opens holding QA's
 * recommendation -- to send as it stands, or to rewrite -- and what is sent is the
 * developer's instruction for the next try, on a fresh budget.
 */
export function BudgetAnswer({ job, compact }: { job: Job; compact: boolean }) {
  const tx = useT();
  const say = useSay();
  const reject = useReject(job.id);
  const recommendation = job.data.recommendation ?? "";
  const [open, setOpen] = useState(!compact);
  const [answer, setAnswer] = useState<string | null>(null);
  // the recommendation is the agent's prose: shown in the reader's language, but the box
  // holds it as written, since what is sent goes to the developer as it stands
  const text = answer ?? recommendation;
  const send = () => reject.mutate(text.trim(), { onSuccess: () => setAnswer(null) });
  if (!open) {
    return (
      <div className="row">
        <button className="btn primary small" onClick={() => setOpen(true)}>
          {tx("Answer…")}
        </button>
      </div>
    );
  }
  return (
    <div className={compact ? "stack tight" : "gate"}>
      {!compact && (
        <div style={{ marginBottom: 8 }}>
          {tx("This phase spent its budget. Say what to do next; it is sent to the developer.")}
        </div>
      )}
      {recommendation && (
        <div className="callout notice small" style={{ marginBottom: 8 }}>
          <strong>{tx("QA recommends")}:</strong> {say(recommendation)}
        </div>
      )}
      <textarea
        rows={compact ? 4 : 5}
        style={{ width: "100%", maxWidth: compact ? 320 : 640 }}
        placeholder={tx("what should the developer do next?")}
        value={text}
        onChange={(e) => setAnswer(e.target.value)}
        aria-label={tx("what should the developer do next?")}
      />
      <div className="row" style={{ marginTop: 6 }}>
        <button
          className="btn primary small"
          disabled={!text.trim() || reject.isPending}
          onClick={send}
        >
          {reject.isPending
            ? tx("Sending…")
            : recommendation && text.trim() === recommendation.trim()
              ? tx("Send QA's recommendation")
              : tx("Send")}
        </button>
        {compact && (
          <button className="btn small" onClick={() => setOpen(false)}>
            {tx("Cancel")}
          </button>
        )}
      </div>
      {reject.error && <div className="callout error">{describeError(reject.error)}</div>}
    </div>
  );
}

/** "Open the pull request without deployment files" -- shared by the gate row here and
 *  the pipeline drawer, which answers the deployment gate with its own buttons. */
export function SkipDeploymentButton({
  mutation,
  onSkipped,
}: {
  mutation: ReturnType<typeof useSkipDeployment>;
  onSkipped?: () => void;
}) {
  const tx = useT();
  return (
    <button
      className="btn small"
      disabled={mutation.isPending}
      onClick={() => mutation.mutate(undefined, { onSuccess: onSkipped })}
      title={tx(
        "no deployment files are written; the pull request carries the code alone and the plan stays on the record",
      )}
    >
      {mutation.isPending ? tx("Skipping…") : tx("Go on without deployment")}
    </button>
  );
}
