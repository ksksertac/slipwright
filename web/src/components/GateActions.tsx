import { useState } from "react";
import { describeError, type Job } from "../api/client";
import { useApprove, useMyTeam, useReject, useReplanJob, useRetryJob } from "../api/hooks";
import { isOwner, mayActAt } from "../api/gates";
import { Modal } from "./Modal";
import { useT } from "../i18n";

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

/** The supervisor's view of the gate the job waits at (assisted / auto modes). */
export function Recommendation({ job, detailed = false }: { job: Job; detailed?: boolean }) {
  const tx = useT();
  const s = job.data.supervision as
    | {
        decision?: string;
        confidence?: number;
        risk?: string;
        reasons?: string[];
        feedback?: string;
        acted?: string;
        blockers?: string[];
        error?: string;
      }
    | null
    | undefined;
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
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      {s.decision === "reject" && s.feedback && (
        <div className="small muted" style={{ marginTop: 4 }}>
          suggested feedback: {s.feedback}
        </div>
      )}
      {s.blockers && s.blockers.length > 0 && (
        <div className="small muted" style={{ marginTop: 4 }}>
          not approved automatically: {s.blockers.join(", ")}
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
  const team = useMyTeam();
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
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
  const error = approve.error ?? reject.error;

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
        >
          {tx("Approve")} · {tx(pending)}
        </button>
        {!rejecting ? (
          <button className="btn bad small" onClick={() => setRejecting(true)}>
            {tx("Reject…")}
          </button>
        ) : (
          <>
            <input
              type="text"
              style={{ width: compact ? 220 : 360 }}
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
      {error && <div className="callout error">{describeError(error)}</div>}
    </div>
  );
}
