import { useState } from "react";
import { describeError, type Job } from "../api/client";
import { useApprove, useReject, useRetryJob } from "../api/hooks";
import { useT } from "../i18n";

export function pendingApproval(job: Job): string | null {
  switch (job.state) {
    case "awaiting_backlog_approval":
      return "backlog";
    case "awaiting_architecture_approval":
      return "architecture";
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

/** Continue a failed job from the step it died in, optionally with a note to the agent. */
export function RetryActions({ job, compact = false }: { job: Job; compact?: boolean }) {
  const tx = useT();
  const retry = useRetryJob(job.id);
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  if (job.state !== "failed") return null;
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
      {!open ? (
        <button className="btn small" onClick={() => setOpen(true)}>
          {tx("Retry with a note…")}
        </button>
      ) : (
        <>
          <input
            type="text"
            style={{ width: compact ? 220 : 360 }}
            placeholder={tx("what the agent should know this time")}
            value={feedback}
            autoFocus
            onChange={(e) => setFeedback(e.target.value)}
          />
          <button
            className="btn primary small"
            disabled={!feedback.trim() || retry.isPending}
            onClick={() => retry.mutate(feedback.trim(), { onSuccess: () => setOpen(false) })}
          >
            {tx("Send & retry")}
          </button>
        </>
      )}
      {retry.error && <span className="error small">{describeError(retry.error)}</span>}
    </div>
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
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const pending = pendingApproval(job);
  if (!pending) return null;
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
