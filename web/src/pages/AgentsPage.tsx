import { Link } from "react-router-dom";
import type { AgentSummary } from "../api/client";
import { useAgents } from "../api/hooks";
import { Crumbs } from "../components/Crumbs";
import { AgentIcon } from "../components/agents";
import { JiraAgentAccount, ProjectJiraSetup } from "../components/JiraAgentSetup";
import { ErrorBox, Loading, PageHead, timeAgo } from "../components/ui";

export function AgentsPage() {
  const agents = useAgents();
  return (
    <div>
      <Crumbs items={[{ label: "Agents" }]} />
      <PageHead
        title="Agents"
        subtitle="Six specialists and a supervisor. Each card shows its default routing; open one for its setup, standards and activity."
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

      <h2 style={{ marginTop: 28, marginBottom: 12 }}>Jira</h2>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <JiraAgentAccount />
        <ProjectJiraSetup />
      </div>
    </div>
  );
}

function AgentCard({ agent: a }: { agent: AgentSummary }) {
  return (
    <Link to={`/agents/${a.role}`} className="card pcard" style={{ color: "inherit" }}>
      <div className="row spread" style={{ flexWrap: "nowrap" }}>
        <div className="row" style={{ flexWrap: "nowrap", gap: 10 }}>
          <span className="agent-ico">
            <AgentIcon role={a.role} />
          </span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 15 }}>{a.label}</div>
            <div className="faint tiny mono">{a.role}</div>
          </div>
        </div>
        {a.permissions.includes("jira") && <span className="badge ok plain">jira</span>}
      </div>
      <div className="muted small" style={{ minHeight: 38 }}>
        {a.scope}
      </div>
      <dl className="kv" style={{ gridTemplateColumns: "90px 1fr" }}>
        <dt>Model</dt>
        <dd className="mono truncate">
          {a.model}
          <span className="faint"> · {a.provider ?? "default"}</span>
        </dd>
        <dt>Thinking</dt>
        <dd>{a.thinking_depth}</dd>
        <dt>Standards</dt>
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
        <span>
          {a.invocations} invocation{a.invocations === 1 ? "" : "s"}
        </span>
        <span>{a.last_used ? `used ${timeAgo(a.last_used)}` : "never used"}</span>
      </div>
    </Link>
  );
}
