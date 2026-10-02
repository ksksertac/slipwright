// Pausing a development so people can work on its branch by hand, and carrying it on.
//
// Stop used to be the only way to halt one, and it was for good. Somebody who wanted to
// write a piece themselves -- and then let the agents go on from there -- had nowhere to
// go. A pause keeps the development's place; the two dialogs here are its two ends: how to
// leave it (with the branch pushed, or not) and how to come back (with what people pushed
// meanwhile, or not). Ending it for good is still there, as "End".
import { useState } from "react";
import { describeError, type Job } from "../api/client";
import { useCarryOn, useMyTeam, usePauseJob, useSyncStatus } from "../api/hooks";
import { isOwner } from "../api/gates";
import { IconPlay, IconStop } from "./icons";
import { Modal } from "./Modal";
import { hasFinished, timeAgo } from "./ui";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";

/** What the server keeps about a pause (``JobData.pause``); loosely typed there. */
type PauseRecord = {
  from_state?: string;
  phase_index?: number;
  at?: string;
  by?: string | null;
  pushed?: string | null;
  push_error?: string | null;
};

function pauseOf(job: Job): PauseRecord {
  return (job.data.pause ?? {}) as PauseRecord;
}

/** The button that opens the pause dialog: "Stop" on a development that is going. */
export function PauseAction({ job, lane = false }: { job: Job; lane?: boolean }) {
  const tx = useT();
  const team = useMyTeam();
  const [open, setOpen] = useState(false);
  if (hasFinished(job.state) || job.state === "paused" || job.state === "created") return null;
  if (!isOwner(team.data)) return null;
  return (
    <>
      <button
        type="button"
        className={lane ? "lane-btn lane-stop" : "btn ghost small"}
        onClick={() => setOpen(true)}
        title={tx("pause this development; it keeps its place")}
      >
        <IconStop />
        {tx("Stop")}
      </button>
      {open && <PauseDialog job={job} onClose={() => setOpen(false)} />}
    </>
  );
}

function PauseDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const tx = useT();
  const pause = usePauseJob(job.id);
  const sync = useSyncStatus(job.id, true);
  const canPush = sync.data?.can_push ?? false;
  const go = (push: boolean) => pause.mutate(push, { onSuccess: onClose });
  return (
    <Modal
      title={tx("Stop the development")}
      onClose={onClose}
      footer={
        <>
          <button className="btn" disabled={pause.isPending} onClick={() => go(false)}>
            {tx("Stop")}
          </button>
          <button
            className="btn primary"
            disabled={pause.isPending || !canPush}
            title={sync.data?.why_not ?? undefined}
            onClick={() => go(true)}
          >
            {pause.isPending ? tx("Stopping…") : tx("Stop and push")}
          </button>
        </>
      }
    >
      <p>
        {tx(
          "It stops before its next call -- whatever is being answered now finishes -- and keeps its place: the step, the phase and everything written so far. It carries on from there when you say so.",
        )}
      </p>
      <p className="muted small">
        {tx(
          "Stop and push also sends the branch to the repository as it stands, half-written phase included, so people can check it out and work on it by hand.",
        )}
      </p>
      {sync.data && !sync.data.can_push && (
        <p className="muted small">{tx(sync.data.why_not ?? "")}</p>
      )}
      <p className="mono small">{job.data.branch_name || `slipwright/${job.id}`}</p>
      {pause.error && <p className="error small">{describeError(pause.error)}</p>}
    </Modal>
  );
}

/** The button that opens the carry-on dialog, on a paused development. */
export function CarryOnAction({ job, lane = false }: { job: Job; lane?: boolean }) {
  const tx = useT();
  const team = useMyTeam();
  const [open, setOpen] = useState(false);
  if (job.state !== "paused" || !isOwner(team.data)) return null;
  return (
    <>
      <button
        type="button"
        className={lane ? "lane-btn" : "btn primary small"}
        onClick={() => setOpen(true)}
      >
        <IconPlay />
        {tx("Carry on")}
      </button>
      {open && <CarryOnDialog job={job} onClose={() => setOpen(false)} />}
    </>
  );
}

function CarryOnDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const tx = useT();
  const carry = useCarryOn(job.id);
  const sync = useSyncStatus(job.id, true);
  const moved = sync.data?.moved === true;
  const go = (pull: boolean) => carry.mutate(pull, { onSuccess: onClose });
  return (
    <Modal
      title={tx("Carry on with the development")}
      onClose={onClose}
      footer={
        <>
          <button
            className={moved ? "btn" : "btn primary"}
            disabled={carry.isPending || moved}
            onClick={() => go(false)}
          >
            {tx("Carry on")}
          </button>
          <button
            className={moved ? "btn primary" : "btn"}
            disabled={carry.isPending || !(sync.data?.can_push ?? false)}
            title={sync.data?.why_not ?? undefined}
            onClick={() => go(true)}
          >
            {carry.isPending ? tx("Working…") : tx("Pull and carry on")}
          </button>
        </>
      }
    >
      <p>
        {tx(
          "Carry on picks up exactly where it was paused. Pull and carry on first merges what people pushed to the branch meanwhile; the Architect then reads what they did against the plan, and once you approve that, the phases they finished are not built again.",
        )}
      </p>
      {moved && (
        <p className="callout notice small">
          {tx(
            "Somebody has pushed to this branch since it was paused. Carrying on without those commits would build beside them, so pull them in.",
          )}
        </p>
      )}
      {carry.error && <p className="error small">{describeError(carry.error)}</p>}
    </Modal>
  );
}

/** What a paused development's page says in place of a gate: who paused it, when, and --
 *  when the branch was pushed -- how to get at it. */
export function PausedPanel({ job }: { job: Job }) {
  const tx = useT();
  const p = pauseOf(job);
  const branch = job.data.branch_name || `slipwright/${job.id}`;
  return (
    <div className="callout notice" style={{ display: "block" }}>
      <div className="row spread">
        <span>
          <strong>
            {p.by
              ? tx("Paused by {who} {ago}", { who: p.by, ago: timeAgo(p.at) })
              : tx("Paused {ago}", { ago: timeAgo(p.at) })}
          </strong>
        </span>
        <CarryOnAction job={job} />
      </div>
      {p.pushed && (
        <div className="small" style={{ marginTop: 6 }}>
          {tx("The branch is pushed. To work on it:")}
          <pre className="mono small">{`git fetch origin\ngit checkout ${branch}`}</pre>
        </div>
      )}
      {p.push_error && (
        <div className="small error" style={{ marginTop: 6 }}>
          {tx("The branch was not pushed:")} {p.push_error}
        </div>
      )}
    </div>
  );
}

type Finding = { phase: number; goal: string; status: string; evidence: string };

/** The Architect's reading of what people did while it was paused: approved, the phases
 *  they finished are passed over; sent back with a note, it is read again. */
export function ReconcileGate({ job }: { job: Job }) {
  const tx = useT();
  const say = useSay();
  const found = (job.data.reconcile ?? {}) as {
    resume_phase?: number;
    phases?: Finding[];
    summary?: string;
    commits?: number;
  };
  const total = (job.data.plan?.phases as unknown[] | undefined)?.length ?? 0;
  const resume = found.resume_phase ?? 1;
  return (
    <div style={{ marginTop: 12 }}>
      {found.summary && <p>{say(found.summary)}</p>}
      <table className="mini">
        <thead>
          <tr>
            <th>{tx("Phase")}</th>
            <th>{tx("Goal")}</th>
            <th>{tx("Status")}</th>
            <th>{tx("Evidence")}</th>
          </tr>
        </thead>
        <tbody>
          {(found.phases ?? []).map((f) => (
            <tr key={f.phase}>
              <td>{f.phase}</td>
              <td>{say(f.goal)}</td>
              <td>
                <span
                  className={`badge ${f.status === "done" ? "ok" : f.status === "partial" ? "work" : "idle"}`}
                >
                  {tx(f.status === "done" ? "done by hand" : f.status)}
                </span>
              </td>
              <td className="muted">{say(f.evidence)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        {resume > total
          ? tx("Every phase left is finished: approving goes straight to QA.")
          : tx("Approving carries on with phase {n}.", { n: resume })}
      </p>
    </div>
  );
}
