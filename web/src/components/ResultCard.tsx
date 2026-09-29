// What a development produced: the branch, what changed on it, and how to get it. Read
// from git on every visit, so it stays true after a restart and after a manual merge.
//
// It used to wait for the development to finish, which read as a lie: five phases built,
// the tests written, commits sitting on the branch -- and a tab saying nothing had come
// out yet. Git can be read at any point, so it is, and the card says whether what it shows
// is finished or still growing. The empty state is kept for what it actually means: a
// branch with nothing on it yet.
//
// In `compact` mode it is one card among others on a page nobody opened for it, and there
// it stays out of the way until there is a finished result to show.
import { Link } from "react-router-dom";
import type { Job } from "../api/client";
import { useJobResult } from "../api/hooks";
import { Copyable } from "./Copyable";
import { Detail } from "./Detail";
import { IconExternal, IconLayers } from "./icons";
import { Empty, ErrorBox, Loading, STATE_LABEL } from "./ui";
import { useT } from "../i18n";

export function ResultCard({ job, compact = false }: { job: Job; compact?: boolean }) {
  const tx = useT();
  const finished = job.state === "done" || job.state === "failed";
  // nothing to read before the branch exists; after that there is something to show at
  // every step, and it is asked for again while the agents are still committing to it
  const started = Boolean(job.data.base_commit);
  const result = useJobResult(job.id, compact ? finished : started, !finished);

  if (compact && !finished) return null;
  if (result.isLoading) return compact ? null : <Loading rows={3} />;
  if (result.error) return compact ? null : <ErrorBox error={result.error} />;

  const r = result.data;
  // no branch yet, or a branch with no commit on it: the only case where the tab is
  // honestly empty
  if (!r || (!finished && r.commits.length === 0)) {
    if (compact) return null;
    return (
      <Empty title={tx("Nothing has come out yet.")} icon={<IconLayers />}>
        {tx(
          "This development is still running — it is {state}. What it produced, and how to take it into your working copy, appears here as soon as the first commit lands on its branch.",
          { state: tx(STATE_LABEL[job.state]) },
        )}
      </Empty>
    );
  }
  const files = [...r.files].sort((a, b) => b.added + b.removed - (a.added + a.removed));
  const shown = compact ? files.slice(0, 5) : files.slice(0, 40);

  return (
    <div className="card result">
      <div className="row spread">
        {/* under the development's "What came out" tab the tab is the title; the project
            page shows the card on its own and needs one */}
        {compact ? (
          <h3 style={{ margin: 0 }}>
            {finished ? tx("What came out of it") : tx("What is on the branch so far")}
          </h3>
        ) : (
          <span />
        )}
        <span className={`badge ${r.merged ? "ok" : finished ? "idle" : "work"}`}>
          {r.merged
            ? tx("merged into {branch}", { branch: r.base_branch })
            : finished
              ? tx("on its branch")
              : tx("still being written")}
        </span>
      </div>
      {r.problem ? (
        <p className="muted small">{tx(r.problem)}</p>
      ) : (
        <>
          <p className="muted small" style={{ marginBottom: 10 }}>
            {tx("{files} file(s), +{added} −{removed}, in {commits} commit(s) on", {
              files: r.files.length,
              added: r.added,
              removed: r.removed,
              commits: r.commits.length,
            })}{" "}
            <code>{r.branch}</code> {tx("in")} <code>{r.checkout}</code>
          </p>
          {shown.length > 0 && (
            <ul className="filelist">
              {shown.map((f) => (
                <li key={f.path}>
                  <code className="truncate">{f.path}</code>
                  <span className="add">+{f.added}</span>
                  <span className="del">−{f.removed}</span>
                </li>
              ))}
              {files.length > shown.length && (
                <li className="faint">{tx("and {n} more", { n: files.length - shown.length })}</li>
              )}
            </ul>
          )}
          {/* not offered mid-run: merging a branch the agents are still committing to
              takes half a feature, and the badge above already says it is still growing */}
          {r.merge_command && finished && (
            <div style={{ marginTop: 10 }}>
              <div className="muted small">{tx("Take it into your working copy:")}</div>
              <Copyable text={r.merge_command}>
                <pre>{r.merge_command}</pre>
              </Copyable>
            </div>
          )}
        </>
      )}
      <div className="row" style={{ marginTop: 10 }}>
        {r.pr_url && (
          <a className="btn small" href={r.pr_url} target="_blank" rel="noreferrer">
            <IconExternal /> {tx("Pull request")}
          </a>
        )}
        {compact && (
          <Link className="btn small" to={`/projects/${job.project_id}/jobs/${job.id}`}>
            {tx("Open the development")}
          </Link>
        )}
      </div>
      {!compact && r.summary && (
        <details style={{ marginTop: 10 }}>
          <summary>{tx("What DevOps wrote about it")}</summary>
          <Detail text={r.summary} />
        </details>
      )}
    </div>
  );
}
