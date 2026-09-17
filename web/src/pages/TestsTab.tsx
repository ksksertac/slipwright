import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { describeError, type TestRun } from "../api/client";
import {
  useProjectJobs,
  useStartTestRun,
  useTestRun,
  useTestRunOutput,
  useTestRuns,
} from "../api/hooks";
import { IconFlask, IconPlay } from "../components/icons";
import { Empty, ErrorBox, Loading, formatTime } from "../components/ui";

const STATUS_CLASS: Record<TestRun["status"], string> = {
  running: "work",
  passed: "ok",
  failed: "bad",
  error: "bad",
};

function duration(run: TestRun): string {
  if (!run.finished_at) return "…";
  const s = (new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.round(s / 60)} min`;
}

export function TestsTab({ projectId }: { projectId: string }) {
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
  const withWorktree = (jobs.data ?? []).filter((j) => j.worktree_path);

  return (
    <div className="stack">
      <div className="card">
        <div className="row spread">
          <div className="row">
            <strong>Run tests</strong>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">on the main checkout</option>
              {withWorktree.map((j) => (
                <option key={j.id} value={j.id}>
                  in job {j.id} — {j.request.slice(0, 50)}
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
              <IconPlay /> {start.isPending ? "Starting…" : "Run tests"}
            </button>
          </div>
          <div className="row">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">any status</option>
              <option value="running">running</option>
              <option value="passed">passed</option>
              <option value="failed">failed</option>
              <option value="error">error</option>
            </select>
            <select value={jobFilter} onChange={(e) => setJobFilter(e.target.value)}>
              <option value="">any job</option>
              {(jobs.data ?? []).map((j) => (
                <option key={j.id} value={j.id}>
                  {j.id}
                </option>
              ))}
            </select>
          </div>
        </div>
        {start.error && <div className="callout error">{describeError(start.error)}</div>}
      </div>

      <ErrorBox error={runs.error} />
      {runs.isLoading && <Loading />}
      {runs.data && runs.data.length === 0 && (
        <Empty title="No test runs yet" icon={<IconFlask />}>
          Every build gate the engine runs is recorded here, and you can run the project's test
          command yourself at any time.
        </Empty>
      )}
      {visible.length > 0 && (
        <div className="card flush">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Source</th>
                <th>Job</th>
                <th>Command</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((run) => (
                <tr
                  key={run.id}
                  className={`clickable ${selected === run.id ? "selected" : ""}`}
                  onClick={() => setSelected(selected === run.id ? null : run.id)}
                >
                  <td>
                    <span className={`badge ${STATUS_CLASS[run.status]}`}>{run.status}</span>
                    {run.exit_code !== null && run.exit_code !== 0 && (
                      <span className="muted small"> exit {run.exit_code}</span>
                    )}
                  </td>
                  <td className="muted small">{formatTime(run.started_at)}</td>
                  <td className="muted small">{duration(run)}</td>
                  <td className="small">
                    {run.source === "gate" ? "build gate" : "manual"}
                    {run.note && <div className="muted">{run.note}</div>}
                  </td>
                  <td className="small">
                    {run.job_id ? (
                      <Link
                        to={`/projects/${projectId}/jobs/${run.job_id}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {jobById.get(run.job_id)?.request.slice(0, 40) ?? run.job_id}
                      </Link>
                    ) : (
                      <span className="muted">main checkout</span>
                    )}
                  </td>
                  <td className="mono small">{run.command}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {selected && <RunOutput runId={selected} />}
    </div>
  );
}

function RunOutput({ runId }: { runId: string }) {
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
    <div className="card">
      <div className="row spread">
        <strong>
          Output{" "}
          {run.data && (
            <span className={`badge ${STATUS_CLASS[run.data.status]}`}>{run.data.status}</span>
          )}
        </strong>
        <span className="muted small mono">{run.data?.cwd}</span>
      </div>
      {output.isLoading && <Loading />}
      {output.data !== undefined && (
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
          {running && <span className="muted">… still running</span>}
        </pre>
      )}
    </div>
  );
}
