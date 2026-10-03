// Deleting a development for good, and what a deleted one shows instead of its controls.
//
// The delete that came before took the development's rows away and left the host as it
// was: the branch, the draft pull request, and the code itself once somebody had merged
// it. This one takes those back -- the pull request closed, the branch deleted, what was
// merged reverted on the base branch, the Jira issues moved to Won't Do -- and keeps the
// development in the list, marked deleted, to be read. Nothing moves it again.
import { useState } from "react";
import { describeError, type Job } from "../api/client";
import { useMyTeam, useRemoveJob } from "../api/hooks";
import { isOwner } from "../api/gates";
import { IconTrash } from "./icons";
import { Modal } from "./Modal";
import { hasFinished, timeAgo } from "./ui";
import { useT } from "../i18n";

/** What the server keeps about a deletion (``JobData.removed``); loosely typed there. */
type RemovalRecord = {
  by?: string | null;
  at?: string;
  prs_closed?: string[];
  branch_deleted?: boolean;
  reverted?: { onto: string; commit: string; commits: number } | null;
  jira_closed?: string[];
  jira_left?: string[];
  errors?: string[];
};

function removalOf(job: Job): RemovalRecord | null {
  return (job.data.removed ?? null) as RemovalRecord | null;
}

export function isRemoved(job: Job): boolean {
  return job.data.removed !== null && job.data.removed !== undefined;
}

/** Whether it can be deleted now: stopped or finished, and not already deleted. */
export function mayRemove(job: Job): boolean {
  return !isRemoved(job) && (job.state === "paused" || hasFinished(job.state));
}

/** The button that opens the delete dialog, beside Carry on on a stopped development and
 *  on a finished one. The owner's, like ending it. */
export function RemoveAction({ job, lane = false }: { job: Job; lane?: boolean }) {
  const tx = useT();
  const team = useMyTeam();
  const [open, setOpen] = useState(false);
  if (!mayRemove(job) || !isOwner(team.data)) return null;
  return (
    <>
      <button
        type="button"
        className={lane ? "lane-btn lane-stop" : "btn danger small"}
        onClick={() => setOpen(true)}
      >
        <IconTrash />
        {tx("Delete")}
      </button>
      {open && <RemoveDialog job={job} onClose={() => setOpen(false)} />}
    </>
  );
}

export function RemoveDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const tx = useT();
  const remove = useRemoveJob(job.id);
  const branch = job.data.branch_name || `slipwright/${job.id}`;
  const pr = job.data.pr_url ?? job.data.draft_pr_url;
  const jira = Object.keys(job.data.jira_keys ?? {}).length;
  return (
    <Modal
      title={tx("Delete development")}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            {tx("Cancel")}
          </button>
          <button
            className="btn bad"
            disabled={remove.isPending}
            onClick={() => remove.mutate(undefined, { onSuccess: onClose })}
          >
            <IconTrash /> {remove.isPending ? tx("Deleting…") : tx("Delete it everywhere")}
          </button>
        </>
      }
    >
      <p>
        {tx(
          "The development stays in the list, marked deleted, to be read. Nothing carries it on, retries or re-runs it again.",
        )}
      </p>
      <ul className="small">
        <li>
          {tx("Its branch is deleted on the host:")} <span className="mono">{branch}</span>
        </li>
        {pr && <li>{tx("Its pull request is closed.")}</li>}
        <li>
          {tx(
            "If any of it was merged into the base branch, a commit that reverts it is pushed there, on top of what is there now.",
          )}
        </li>
        {jira > 0 && <li>{tx("Its Jira issues are moved to Won't Do.")}</li>}
        <li>{tx("Its worktree on this machine is removed.")}</li>
      </ul>
      {remove.error && <p className="error small">{describeError(remove.error)}</p>}
    </Modal>
  );
}

/** What a deleted development's page says in place of a gate: who deleted it, when, what
 *  was taken off the host -- and what could not be, so it can be done by hand. */
export function RemovedPanel({ job }: { job: Job }) {
  const tx = useT();
  const r = removalOf(job);
  if (!r) return null;
  const errors = r.errors ?? [];
  return (
    <div className={`callout ${errors.length ? "error" : "notice"}`} style={{ display: "block" }}>
      <strong>
        {r.by
          ? tx("Deleted by {who} {ago}", { who: r.by, ago: timeAgo(r.at) })
          : tx("Deleted {ago}", { ago: timeAgo(r.at) })}
      </strong>
      <ul className="small" style={{ marginTop: 6 }}>
        {r.reverted && (
          <li>
            {tx("Reverted on {branch}:", { branch: r.reverted.onto })}{" "}
            <span className="mono">{r.reverted.commit.slice(0, 12)}</span>
          </li>
        )}
        {(r.prs_closed ?? []).map((url) => (
          <li key={url}>
            {tx("Pull request closed:")}{" "}
            <a href={url} target="_blank" rel="noreferrer">
              {url}
            </a>
          </li>
        ))}
        {r.branch_deleted && <li>{tx("Branch deleted on the host.")}</li>}
        {(r.jira_closed ?? []).length > 0 && (
          <li>
            {tx("Jira, moved to Won't Do:")} {(r.jira_closed ?? []).join(", ")}
          </li>
        )}
        {(r.jira_left ?? []).length > 0 && (
          <li>
            {tx("Jira, no Won't Do to move to:")} {(r.jira_left ?? []).join(", ")}
          </li>
        )}
      </ul>
      {errors.length > 0 && (
        <div className="small" style={{ marginTop: 6 }}>
          <strong>{tx("Not done -- do these by hand:")}</strong>
          <ul>
            {errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
