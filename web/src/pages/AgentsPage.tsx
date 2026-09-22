import { Link } from "react-router-dom";
import type { AgentSummary } from "../api/client";
import { useAgents } from "../api/hooks";
import { Crumbs } from "../components/Crumbs";
import { AgentIcon } from "../components/agents";
import { ErrorBox, Loading, PageHead, timeAgo } from "../components/ui";
import { useT } from "../i18n";

export function AgentsPage() {
  const tx = useT();
  const agents = useAgents();
  return (
    <div>
      <Crumbs items={[{ label: "Agents" }]} />
      <PageHead
        title={tx("Agents")}
        subtitle={tx(
          "Each card shows the provider and model the agent runs on right now; open one for its setup, standards and activity.",
        )}
      />
      <ErrorBox error={agents.error} />
      {agents.isLoading && <Loading />}
      {agents.data && (
        <div className="grid-3">
          {agents.data.map((a) => (
            <AgentCard key={a.role} agent={a} />
          ))}
        </div>
      )}
    </div>
  );
}

function AgentCard({ agent: a }: { agent: AgentSummary }) {
  const tx = useT();
  return (
    <Link to={`/agents/${a.role}`} className="card pcard" style={{ color: "inherit" }}>
      <div className="row spread" style={{ flexWrap: "nowrap" }}>
        <div className="row" style={{ flexWrap: "nowrap", gap: 10 }}>
          <span className="agent-ico">
            <AgentIcon role={a.role} />
          </span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15 }}>{tx(a.label)}</div>
            <div className="faint tiny mono">{a.role}</div>
          </div>
        </div>
        {a.permissions.includes("jira") && <span className="badge ok plain">jira</span>}
      </div>
      <div className="muted small" style={{ minHeight: 38 }}>
        {a.scope}
      </div>
      <dl className="kv" style={{ gridTemplateColumns: "90px 1fr" }}>
        <dt>{tx("Model")}</dt>
        <dd
          className="mono truncate"
          title={
            a.assigned_provider
              ? tx("assigned — every project")
              : a.provider
                ? "pinned in the profile"
                : "follows Settings → Models"
          }
        >
          {a.effective_model}
          <span className="faint">
            {" "}
            · {a.effective_provider}
            {a.assigned_provider ? ` (${tx("assigned")})` : a.provider ? "" : " (default)"}
          </span>
        </dd>
        <dt>{tx("Thinking")}</dt>
        <dd>{a.thinking_depth}</dd>
        <dt>{tx("Standards")}</dt>
        <dd>{a.standards_domain === "*" ? "all domains" : a.standards_domain}</dd>
      </dl>
      <div className="row" style={{ gap: 4 }}>
        {a.permissions.map((p) => (
          <span key={p} className="tag" style={{ marginLeft: 0 }}>
            {p}
          </span>
        ))}
      </div>
      <div className="row spread faint tiny">
        <span>{tx("{n} invocation(s)", { n: a.invocations })}</span>
        <span>
          {a.last_used ? tx("used {ago}", { ago: timeAgo(a.last_used) }) : tx("never used")}
        </span>
      </div>
    </Link>
  );
}
