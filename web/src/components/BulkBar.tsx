// The sticky action bar for bulk approvals: "N selected · Approve selected · Reject
// selected…". Selection lives in the page; the bar only acts on it. Each approval is an
// ordinary gate call recorded on its job, so a job that moved on is reported, not lost.
import { useState } from "react";
import { describeError, type BatchResult } from "../api/client";
import { useBatchApprove, useBatchReject } from "../api/hooks";
import { IconCheck, IconX } from "./icons";
import { useToast } from "./Toast";
import { useT } from "../i18n";

export function BulkBar({
  selected,
  onClear,
  labelOf,
}: {
  selected: string[];
  onClear: () => void;
  labelOf?: (jobId: string) => string;
}) {
  const tx = useT();
  const approve = useBatchApprove();
  const reject = useBatchReject();
  const toast = useToast();
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  if (selected.length === 0) return null;
  const busy = approve.isPending || reject.isPending;

  const report = (verb: string, result: BatchResult) => {
    const failed = result.results.filter((r) => !r.ok);
    if (result.approved > 0) toast.ok(`${verb} ${result.approved} development(s)`);
    for (const r of failed) {
      toast.bad(`${labelOf ? labelOf(r.job_id) : r.job_id}: ${r.error ?? "failed"}`);
    }
    onClear();
    setRejecting(false);
    setFeedback("");
  };

  return (
    <div className="bulk-bar" role="region" aria-label={tx("Bulk approvals")}>
      <strong>{selected.length} selected</strong>
      {!rejecting ? (
        <>
          <button
            className="btn ok small"
            disabled={busy}
            onClick={() =>
              approve.mutate(selected, {
                onSuccess: (r) => report("Approved", r),
                onError: (e) => toast.bad(describeError(e)),
              })
            }
          >
            <IconCheck /> {tx("Approve selected")}
          </button>
          <button className="btn bad small" disabled={busy} onClick={() => setRejecting(true)}>
            <IconX /> {tx("Reject selected…")}
          </button>
        </>
      ) : (
        <>
          <input
            type="text"
            style={{ width: 320 }}
            placeholder={tx("feedback for every selected gate")}
            value={feedback}
            autoFocus
            onChange={(e) => setFeedback(e.target.value)}
          />
          <button
            className="btn bad small"
            disabled={busy || !feedback.trim()}
            onClick={() =>
              reject.mutate(
                { job_ids: selected, feedback: feedback.trim() },
                {
                  onSuccess: (r) => report("Rejected", r),
                  onError: (e) => toast.bad(describeError(e)),
                },
              )
            }
          >
            {tx("Send rejection")}
          </button>
          <button className="btn small" onClick={() => setRejecting(false)}>
            {tx("Cancel")}
          </button>
        </>
      )}
      <button className="btn ghost small" onClick={onClear} disabled={busy}>
        {tx("Clear")}
      </button>
    </div>
  );
}
