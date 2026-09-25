// What the agents burned, what they were expected to burn, and the gap.
//
// Three numbers at the top, then one row per development that opens into where the money
// went: by agent, by phase, by model. The estimate is arithmetic over what these roles
// have actually used in this installation, so a project with no history says so instead
// of showing a number that would later read as a measurement.
import { useState } from "react";
import { Link } from "react-router-dom";
import type { JobCost, Spend } from "../api/client";
import { useCosts } from "../api/hooks";
import { AgentIcon, ROLE_LABEL } from "../components/agents";
import { Empty, ErrorBox, Loading, StateBadge, sentence } from "../components/ui";
import { useT, type T } from "../i18n";

/** Dollars, at the precision the number deserves: cents are noise above a dollar, and a
 *  tenth of a cent is the whole story below one. */
function usd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const abs = Math.abs(value);
  if (abs >= 100) return `$${value.toFixed(0)}`;
  if (abs >= 1) return `$${value.toFixed(2)}`;
  if (abs >= 0.01) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(5)}`;
}

export function CostsTab({ projectId }: { projectId: string }) {
  const tx = useT();
  const costs = useCosts(projectId);
  if (costs.isLoading) return <Loading rows={4} />;
  if (costs.error) return <ErrorBox error={costs.error} />;
  if (!costs.data) return null;
  const { jobs, spent_usd, expected_usd, unpriced_calls, priced_models } = costs.data;

  if (priced_models === 0) {
    return (
      <Empty title={tx("No model prices yet")}>
        {tx(
          "Nothing can be costed until the price table has been fetched. It runs once a day, and you can fetch it now from Settings.",
        )}{" "}
        <Link to="/settings/models">{tx("Models")}</Link>
      </Empty>
    );
  }

  return (
    <div className="stack">
      <div className="cost-totals">
        <Total label={tx("Spent")} value={usd(spent_usd)} />
        <Total label={tx("Expected")} value={usd(expected_usd)} />
        <Total
          label={tx("Difference")}
          value={expected_usd === null ? "—" : usd(spent_usd - expected_usd)}
          tone={expected_usd === null ? "" : spent_usd > expected_usd ? "bad" : "ok"}
        />
      </div>
      {unpriced_calls > 0 && (
        <div className="muted small">
          {tx("{n} call(s) ran on a model with no stored price and are not in these totals.", {
            n: unpriced_calls,
          })}
        </div>
      )}
      {jobs.length === 0 ? (
        <Empty>{tx("No development has run yet.")}</Empty>
      ) : (
        jobs.map((job) => <JobRow key={job.job_id} job={job} projectId={projectId} />)
      )}
    </div>
  );
}

function Total({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="cost-total">
      <div className="cost-total-label">{label}</div>
      <div className={`cost-total-value ${tone}`}>{value}</div>
    </div>
  );
}

/** One development. Closed it is a line; open it says where the money went. */
function JobRow({ job, projectId }: { job: JobCost; projectId: string }) {
  const tx = useT();
  const [open, setOpen] = useState(false);
  const over = job.variance_usd !== null && job.variance_usd > 0;
  return (
    <section className="card cost-job">
      <button type="button" className="cost-job-head" onClick={() => setOpen(!open)}>
        <span className="cost-job-id">
          <span className="truncate">{sentence(job.request)}</span>
          <StateBadge state={job.state} />
        </span>
        <span className="cost-job-money">
          <span className="cost-spent">{usd(job.spent_usd)}</span>
          {job.expected_usd !== null && (
            <span className={`chip ${over ? "bad" : "ok"}`}>
              {tx("expected")} {usd(job.expected_usd)}
            </span>
          )}
          <span className="faint tiny">{tx("{n} call(s)", { n: job.calls })}</span>
        </span>
      </button>
      {open && (
        <div className="cost-job-body">
          <Breakdown title={tx("By agent")} rows={job.by_role} roles />
          <Breakdown title={tx("By phase")} rows={job.by_phase} />
          <Breakdown title={tx("By model")} rows={job.by_model} />
          <Expected job={job} />
          <Link className="small" to={`/projects/${projectId}/jobs/${job.job_id}`}>
            {tx("open development →")}
          </Link>
        </div>
      )}
    </section>
  );
}

function Breakdown({ title, rows, roles }: { title: string; rows: Spend[]; roles?: boolean }) {
  const tx = useT();
  if (rows.length === 0) return null;
  const top = Math.max(...rows.map((r) => r.usd), 0);
  return (
    <section className="cost-breakdown">
      <h4>{title}</h4>
      <ul>
        {rows.map((row) => (
          <li key={row.key}>
            <span className="cost-row-name">
              {roles && (
                <span className="role-ink" data-agent={row.key}>
                  <AgentIcon role={row.key} />
                </span>
              )}
              <span className="truncate">
                {roles ? tx(ROLE_LABEL[row.key] ?? row.key) : row.key}
              </span>
            </span>
            {/* the bar is relative to the biggest row, so the shape of the spend reads
                without anyone doing division in their head */}
            <span className="cost-bar">
              <span style={{ width: `${top > 0 ? (row.usd / top) * 100 : 0}%` }} />
            </span>
            <span className="cost-row-value">{usd(row.usd)}</span>
            {row.unpriced_calls > 0 && (
              <span className="faint tiny" title={tx("calls with no stored price")}>
                +{row.unpriced_calls}
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** What each agent was expected to cost, and what that expectation rests on. */
function Expected({ job }: { job: JobCost }) {
  const tx = useT();
  if (job.expectations.length === 0) return null;
  return (
    <section className="cost-breakdown">
      <h4>{tx("What was expected")}</h4>
      <table className="mini">
        <thead>
          <tr>
            <th>{tx("Agent")}</th>
            <th>{tx("Model")}</th>
            <th className="num">{tx("Calls")}</th>
            <th className="num">{tx("Expected")}</th>
            <th className="num">{tx("Based on")}</th>
          </tr>
        </thead>
        <tbody>
          {job.expectations.map((e) => (
            <tr key={e.role}>
              <td>{tx(ROLE_LABEL[e.role] ?? e.role)}</td>
              <td className="mono">{e.model || "—"}</td>
              <td className="num">{e.calls}</td>
              <td className="num">{usd(e.usd)}</td>
              <td className="num">
                {e.basis_calls === 0 ? (
                  <span className="faint">{tx("no history")}</span>
                ) : (
                  tx("{n} call(s)", { n: e.basis_calls })
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export type { T };
