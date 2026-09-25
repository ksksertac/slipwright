// The project's test runs: every build gate the engine ran and every run started by
// hand, newest first and grouped by the day they happened on, so the tab reads as "what
// happened, and when". A row opens in place into what that run was for, what it actually
// executed, what passing would have meant and how it ended -- the engine's own note is
// English, so nothing here is read from it: the text is composed from the run's fields
// and translated like the rest of the UI.
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { describeError, type Job, type TestRun } from "../api/client";
import {
  useProjectJobs,
  useStartTestRun,
  useTestRun,
  useTestRunOutput,
  useTestRuns,
} from "../api/hooks";
import { IconFlask, IconPlay } from "../components/icons";
import { Empty, ErrorBox, Loading, timeAgo } from "../components/ui";
import { useLang, useT, type T } from "../i18n";
import { Copyable } from "../components/Copyable";

const STATUS_CLASS: Record<TestRun["status"], string> = {
  running: "work",
  passed: "ok",
  failed: "bad",
  error: "bad",
};

const STATUS_LABEL: Record<TestRun["status"], string> = {
  running: "running",
  passed: "passed",
  failed: "failed",
  error: "error",
};

function duration(run: TestRun, tx: T): string {
  if (!run.finished_at) return "…";
  const s = Math.max(
    0,
    (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000,
  );
  if (s < 1) return tx("under a second");
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.round(s / 60)} min`;
}

/** The commands a run executed: the profile joins them with "&&", and each one is a step
 *  that had to end in exit code 0 for the run to pass. */
function steps(command: string): string[] {
  return command
    .split("&&")
    .map((part) => part.trim())
    .filter(Boolean);
}

function locale(lang: string): string {
  return lang === "tr" ? "tr-TR" : "en-GB";
}

function clock(iso: string, lang: string): string {
  return new Date(iso).toLocaleTimeString(locale(lang), { hour: "2-digit", minute: "2-digit" });
}

/** Runs under the day they ran on, newest day first; the list already arrives newest
 *  first, so the order inside a day is kept as it comes. */
function byDay(runs: TestRun[]): { key: string; runs: TestRun[] }[] {
  const out: { key: string; runs: TestRun[] }[] = [];
  for (const run of runs) {
    const key = new Date(run.started_at).toDateString();
    if (out.length === 0 || out[out.length - 1]!.key !== key) out.push({ key, runs: [] });
    out[out.length - 1]!.runs.push(run);
  }
  return out;
}

function dayLabel(key: string, tx: T, lang: string): string {
  const day = new Date(key);
  const today = new Date();
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const yesterday = new Date(today.getTime() - 86400000);
  if (same(day, today)) return tx("Today");
  if (same(day, yesterday)) return tx("Yesterday");
  return day.toLocaleDateString(locale(lang), {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: day.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

/** One line for the list: what this run was testing. */
function what(run: TestRun, job: Job | undefined, tx: T): string {
  if (run.source === "gate") {
    return run.phase ? tx("build gate · phase {n}", { n: run.phase }) : tx("build gate");
  }
  return job ? tx("by hand · on the development's branch") : tx("by hand · on the main branch");
}

export function TestsTab({ projectId }: { projectId: string }) {
  const tx = useT();
  const { lang } = useLang();
  const runs = useTestRuns(projectId);
  const jobs = useProjectJobs(projectId);
  const start = useStartTestRun(projectId);
  const [target, setTarget] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [jobFilter, setJobFilter] = useState<string>("");
  const [selected, setSelected] = useState<string | null>(null);

  const jobById = useMemo(() => new Map((jobs.data ?? []).map((j) => [j.id, j])), [jobs.data]);
  const visible = (runs.data ?? []).filter(
    (r) => (!status || r.status === status) && (!jobFilter || r.job_id === jobFilter),
  );
  const days = useMemo(() => byDay(visible), [visible]);
  const withWorktree = (jobs.data ?? []).filter((j) => j.worktree_path);

  const total = runs.data?.length ?? 0;
  const filtered = !!status || !!jobFilter;

  return (
    <div className="stack">
      {/* Starting a run. Only the two controls that do it, so the button never sits next
          to something that merely narrows the list below. */}
      <div className="card">
        <div className="row">
          <strong>{tx("Run tests")}</strong>
          <select className="run-target" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">{tx("on the main branch")}</option>
            {withWorktree.map((j) => (
              <option key={j.id} value={j.id}>
                {tx("in the development: {request}", { request: j.request.slice(0, 50) })}
              </option>
            ))}
          </select>
          <button
            className="btn primary"
            disabled={start.isPending}
            onClick={() =>
              start.mutate(target || null, { onSuccess: (run) => setSelected(run.id) })
            }
          >
            <IconPlay /> {start.isPending ? tx("Starting…") : tx("Run tests")}
          </button>
        </div>
        <p className="muted small" style={{ marginTop: 8, marginBottom: 0 }}>
          {tx(
            "The project's test command, run on the branch you pick. Every build gate the engine ran is in the same list — open a row to see what it was for and how it ended.",
          )}
        </p>
        {start.error && <div className="callout error">{describeError(start.error)}</div>}
      </div>

      <ErrorBox error={runs.error} />
      {runs.isLoading && <Loading />}

      {/* Narrowing the list. It belongs to the list, so it sits on top of it and says how
          much of the list it is currently hiding. Nothing to filter, no bar. */}
      {total > 0 && (
        <div className="run-filters">
          <span className="muted small">
            {filtered
              ? tx("{shown} of {total} run(s)", { shown: visible.length, total })
              : tx("{n} run(s)", { n: total })}
          </span>
          <div className="row">
            <label className="run-filter">
              <span className="faint tiny">{tx("Result")}</span>
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">{tx("any status")}</option>
                <option value="running">{tx("running")}</option>
                <option value="passed">{tx("passed")}</option>
                <option value="failed">{tx("failed")}</option>
                <option value="error">{tx("error")}</option>
              </select>
            </label>
            <label className="run-filter">
              <span className="faint tiny">{tx("Development")}</span>
              <select value={jobFilter} onChange={(e) => setJobFilter(e.target.value)}>
                <option value="">{tx("any development")}</option>
                {(jobs.data ?? []).map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.request.slice(0, 50)}
                  </option>
                ))}
              </select>
            </label>
            {filtered && (
              <button
                className="btn ghost small"
                onClick={() => {
                  setStatus("");
                  setJobFilter("");
                }}
              >
                {tx("Clear")}
              </button>
            )}
          </div>
        </div>
      )}
      {runs.data && runs.data.length === 0 && (
        <Empty title={tx("No test runs yet")} icon={<IconFlask />}>
          {tx(
            "Every build gate the engine runs is recorded here, and you can run the project's test command yourself at any time.",
          )}
        </Empty>
      )}
      {runs.data && runs.data.length > 0 && visible.length === 0 && (
        <Empty
          title={tx("Nothing matches these filters")}
          icon={<IconFlask />}
          action={
            <button
              className="btn small"
              onClick={() => {
                setStatus("");
                setJobFilter("");
              }}
            >
              {tx("Clear the filters")}
            </button>
          }
        >
          {tx("All {n} run(s) are still here — the filters above are hiding them.", { n: total })}
        </Empty>
      )}
      {days.map((day) => (
        <div className="card flush test-day" key={day.key}>
          <div className="card-head">
            <h3>{dayLabel(day.key, tx, lang)}</h3>
            <span className="muted small">
              {tx("{n} run(s)", { n: day.runs.length })} ·{" "}
              {tx("{n} passed", { n: day.runs.filter((r) => r.status === "passed").length })}
              {day.runs.some((r) => r.status === "failed" || r.status === "error")
                ? ` · ${tx("{n} failed", {
                    n: day.runs.filter((r) => r.status === "failed" || r.status === "error").length,
                  })}`
                : ""}
            </span>
          </div>
          <table className="runs">
            <thead>
              <tr>
                <th>{tx("Result")}</th>
                <th>{tx("When")}</th>
                <th>{tx("Duration")}</th>
                <th>{tx("What was tested")}</th>
                <th>{tx("Development")}</th>
              </tr>
            </thead>
            <tbody>
              {day.runs.map((run) => {
                const job = run.job_id ? jobById.get(run.job_id) : undefined;
                const open = selected === run.id;
                return (
                  <Fragment key={run.id}>
                    <tr
                      className={`clickable ${open ? "selected" : ""}`}
                      onClick={() => setSelected(open ? null : run.id)}
                    >
                      <td>
                        <span className={`badge ${STATUS_CLASS[run.status]}`}>
                          {tx(STATUS_LABEL[run.status])}
                        </span>
                      </td>
                      <td className="muted small">
                        {clock(run.started_at, lang)}
                        <span className="faint"> · {timeAgo(run.started_at)}</span>
                      </td>
                      <td className="muted small">{duration(run, tx)}</td>
                      <td className="small">{what(run, job, tx)}</td>
                      <td className="small">
                        {run.job_id ? (
                          <Link
                            to={`/projects/${projectId}/jobs/${run.job_id}`}
                            onClick={(e) => e.stopPropagation()}
                          >
                            {job?.request.slice(0, 40) ?? run.job_id}
                          </Link>
                        ) : (
                          <span className="muted">{tx("main branch")}</span>
                        )}
                      </td>
                    </tr>
                    {open && (
                      <tr className="run-detail">
                        <td colSpan={5}>
                          <RunDetail run={run} job={job} projectId={projectId} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

/** What this run was for, in the reader's language: the purpose, the commands it ran, what
 *  "passed" would have meant and what actually happened -- then the output itself. */
function RunDetail({
  run,
  job,
  projectId,
}: {
  run: TestRun;
  job: Job | undefined;
  projectId: string;
}) {
  const tx = useT();
  const parts = steps(run.command);
  const purpose =
    run.source === "gate"
      ? run.phase
        ? tx(
            "The specialist finished phase {n} of this development. Before the next phase starts, the engine builds the branch and runs the whole test suite: this is that check.",
            { n: run.phase },
          )
        : tx(
            "The engine built the branch and ran the whole test suite before letting the development move on.",
          )
      : job
        ? tx("You started this run yourself, on the development's own branch.")
        : tx("You started this run yourself, on the project's main branch.");
  const outcome =
    run.status === "running"
      ? tx("Still running.")
      : run.status === "passed"
        ? tx("Every command ended in exit code 0: nothing to fix here.")
        : run.status === "error"
          ? tx("The run could not be carried out at all.")
          : tx("A command ended in exit code {code}; the first failure is highlighted below.", {
              code: String(run.exit_code ?? 1),
            });
  return (
    <div className="run-detail-body">
      <dl className="run-facts">
        <dt>{tx("Why this ran")}</dt>
        <dd>
          {purpose}{" "}
          {job && (
            <Link to={`/projects/${projectId}/jobs/${job.id}`}>{tx("Open the development")}</Link>
          )}
        </dd>
        <dt>{tx("What it ran")}</dt>
        <dd>
          <ol className="run-steps">
            {parts.map((part, i) => (
              <li key={`${part}-${i}`}>
                <code>{part}</code>
              </li>
            ))}
          </ol>
          <span className="faint tiny mono">{run.cwd}</span>
        </dd>
        <dt>{tx("What was expected")}</dt>
        <dd>
          {parts.length > 1
            ? tx(
                "All {n} commands end in exit code 0 — the build, the linters and the type checks first, then the whole test suite, with no test skipped or weakened.",
                { n: parts.length },
              )
            : tx(
                "The command ends in exit code 0 — the whole test suite green, with no test skipped or weakened.",
              )}
        </dd>
        <dt>{tx("What happened")}</dt>
        <dd>
          {outcome}
          {run.status !== "running" && (
            <span className="faint">
              {" "}
              {tx("Took {duration}.", { duration: duration(run, tx) })}
            </span>
          )}
          {run.status === "error" && run.note && (
            <div className="faint tiny mono" style={{ marginTop: 4 }}>
              {run.note}
            </div>
          )}
        </dd>
      </dl>
      <RunOutput runId={run.id} />
    </div>
  );
}

function RunOutput({ runId }: { runId: string }) {
  const tx = useT();
  const run = useTestRun(runId);
  const running = run.data?.status === "running";
  const output = useTestRunOutput(runId, running);
  const failRef = useRef<HTMLSpanElement>(null);
  const lines = useMemo(() => (output.data ?? "").split("\n"), [output.data]);
  const failIndex = useMemo(() => {
    const patterns = [/FAILED|FAIL\b|Error\b|error:|Traceback|✗|✖/, /exit \d+\]$/];
    for (const p of patterns) {
      const i = lines.findIndex((l) => p.test(l) && !/exit 0\]$/.test(l));
      if (i >= 0) return i;
    }
    return -1;
  }, [lines]);

  useEffect(() => {
    if (!running && failIndex >= 0) {
      failRef.current?.scrollIntoView({ block: "center" });
    }
  }, [running, failIndex, runId]);

  return (
    <div className="run-output">
      <div className="row spread">
        <strong className="small">{tx("Output")}</strong>
        {failIndex >= 0 && !running && (
          <span className="faint tiny">{tx("scrolled to the first failure")}</span>
        )}
      </div>
      {output.isLoading && <Loading rows={2} />}
      {output.data !== undefined && (
        <Copyable text={output.data}>
          <pre className="log" style={{ marginTop: 8 }}>
            {lines.map((line, i) =>
              i === failIndex ? (
                <span key={i} ref={failRef} className="fail">
                  {line + "\n"}
                </span>
              ) : (
                <span key={i}>{line + "\n"}</span>
              ),
            )}
            {running && <span className="muted">{tx("… still running")}</span>}
          </pre>
        </Copyable>
      )}
    </div>
  );
}
