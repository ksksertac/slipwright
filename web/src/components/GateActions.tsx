import { useState } from "react";
import { describeError, type Job } from "../api/client";
import { useApprove, useReject } from "../api/hooks";

export function pendingApproval(job: Job): string | null {
  switch (job.state) {
    case "awaiting_backlog_approval":
      return "backlog";
    case "awaiting_architecture_approval":
      return "architecture";
    case "awaiting_review_approval":
      return "review";
    case "awaiting_test_approval":
      return job.data.qa_stage === 1 ? "test cases" : "written tests";
    default:
      return null;
  }
}

/** The supervisor's view of the gate the job waits at (assisted / auto modes). */
export function Recommendation({ job, detailed = false }: { job: Job; detailed?: boolean }) {
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
        supervisor unavailable
      </span>
    );
  }
  if (!s.decision || s.acted !== "none") return null;
  const cls = s.decision === "approve" ? (s.risk === "low" ? "ok" : "work") : "bad";
  const chip = (
    <span className={`badge plain ${cls}`} title={(s.reasons ?? []).join("; ")}>
      supervisor recommends {s.decision} · {(s.confidence ?? 0).toFixed(2)} · risk {s.risk}
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
          Waiting for your approval of the <strong>{pending}</strong>.
        </div>
      )}
      <div className="row">
        <button
          className="btn ok small"
          disabled={approve.isPending}
          onClick={() => approve.mutate()}
        >
          Approve {pending}
        </button>
        {!rejecting ? (
          <button className="btn bad small" onClick={() => setRejecting(true)}>
            Reject…
          </button>
        ) : (
          <>
            <input
              type="text"
              style={{ width: compact ? 220 : 360 }}
              placeholder="what should change?"
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
              Send rejection
            </button>
            <button className="btn small" onClick={() => setRejecting(false)}>
              Cancel
            </button>
          </>
        )}
      </div>
      {error && <div className="callout error">{describeError(error)}</div>}
    </div>
  );
}
