import { useState } from "react";
import { describeError, type Job } from "../api/client";
import { useApprove, useReject } from "../api/hooks";

export function pendingApproval(job: Job): string | null {
  switch (job.state) {
    case "awaiting_profile_approval":
      return "profile";
    case "awaiting_plan_approval":
      return "plan";
    case "awaiting_test_approval":
      return job.data.qa_stage === 1 ? "test cases" : "written tests";
    default:
      return null;
  }
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
      {error && <div className="error small">{describeError(error)}</div>}
    </div>
  );
}
