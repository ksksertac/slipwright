import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, useParams } from "react-router-dom";
import {
  api,
  describeError,
  type AgentSummary,
  type Permission,
  type Profile,
  type RoleConfig,
} from "../api/client";
import {
  useActivity_all,
  useAgents,
  useAssignAgent,
  usePatchProject,
  useProject,
  useProjects,
  useTestProvider,
} from "../api/hooks";
import { ActivityRow } from "../components/ActivityRow";
import { AgentAvatar } from "../components/AgentAvatar";
import { Crumbs } from "../components/Crumbs";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAuth } from "../auth/AuthProvider";
import { useProviderModels, useProviders } from "../api/hooks";
import { AgentStandardsTab } from "./AgentStandardsTab";
import { useT } from "../i18n";

const TABS = ["setup", "standards", "activity"] as const;
type Tab = (typeof TABS)[number];
const DEPTHS = ["off", "low", "medium", "high", "max"] as const;
const PERMISSIONS: Permission[] = [
  "read_files",
  "write_files",
  "run_commands",
  "network",
  "git_push",
  "jira",
];

export function AgentDetailPage() {
  const tx = useT();
  const { role = "", tab = "setup" } = useParams();
  const agents = useAgents();
  const current: Tab = (TABS as readonly string[]).includes(tab) ? (tab as Tab) : "setup";
  const agent = agents.data?.find((a) => a.role === role);
  if (agents.isLoading) return <Loading />;
  if (agents.error) return <ErrorBox error={agents.error} />;
  if (!agent) return <Empty>Unknown agent “{role}”.</Empty>;

  return (
    <div>
      <Crumbs items={[{ label: "Agents", to: "/agents" }, { label: agent.label }]} />
      <div className="page-head">
        <div className="row" style={{ flexWrap: "nowrap", gap: 14 }}>
          <AgentAvatar role={agent.role} className="lg" />
          <div>
            <h1>{agent.label}</h1>
            <p>{agent.scope}</p>
          </div>
        </div>
      </div>
      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink key={t} to={`/agents/${role}/${t}`} className={t === current ? "active" : ""}>
            {tx(t[0]!.toUpperCase() + t.slice(1))}
          </NavLink>
        ))}
      </nav>
      {current === "setup" && <SetupTab agent={agent} />}
      {current === "standards" && <AgentStandardsTab role={role} domain={agent.standards_domain} />}
      {current === "activity" && <ActivityTab role={role} />}
    </div>
  );
}

// -- setup: the agent's model (every project), then this role's row of a project profile --

function SetupTab({ agent }: { agent: AgentSummary }) {
  const tx = useT();
  const projects = useProjects();
  const [selected, setSelected] = useState("");
  const projectId = selected || projects.data?.[0]?.id || "";
  const role = agent.role;
  return (
    <div className="stack">
      <ModelCard key={role} agent={agent} />
      <p className="muted small" style={{ marginTop: 18 }}>
        {tx(
          "Thinking depth and permissions are read from the project's seed profile — never from engine code. Pick a project; projects without their own profile start from the engine default and get one when you save.",
        )}
      </p>
      {projects.data && projects.data.length === 0 && (
        <Empty>
          {tx("No projects yet.")} <Link to="/projects/new">{tx("Create one")}</Link> {tx("first.")}
        </Empty>
      )}
      {projects.data && projects.data.length > 0 && (
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="agent-project">{tx("Project")}</label>
          <select
            id="agent-project"
            value={projectId}
            onChange={(e) => setSelected(e.target.value)}
          >
            {projects.data.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {projectId && <RoleSetup key={`${projectId}:${role}`} projectId={projectId} role={role} />}
    </div>
  );
}

/** Which provider and model this agent runs on, for every project. Saving is refused when
 *  the provider has no key; "Test" asks the vendor whether the key and model work. */
function ModelCard({ agent }: { agent: AgentSummary }) {
  const tx = useT();
  const { user } = useAuth();
  const admin = !!user?.is_admin;
  const toast = useToast();
  const providers = useProviders();
  const assign = useAssignAgent(agent.role);
  const test = useTestProvider();
  const [provider, setProvider] = useState(agent.assigned_provider ?? "");
  const [model, setModel] = useState(agent.assigned_model ?? "");
  const [dirty, setDirty] = useState(false);
  const models = useProviderModels(provider || null);
  const spec = providers.data?.find((p) => p.name === provider);
  const defaultProvider = providers.data?.find((p) => p.is_default);
  const pinned = !!agent.assigned_provider;
  const listed = models.data?.models ?? [];
  const known = listed.length > 0;

  const pick = (name: string) => {
    setProvider(name);
    setModel("");
    setDirty(true);
    test.reset();
  };
  const save = (body: { provider: string | null; model: string | null }) =>
    assign.mutate(body, {
      onSuccess: (card) => {
        setDirty(false);
        setProvider(card.assigned_provider ?? "");
        setModel(card.assigned_model ?? "");
        toast.ok(
          card.assigned_provider
            ? tx("{agent} now runs on {model}", {
                agent: tx(agent.label),
                model: card.assigned_model ?? "",
              })
            : tx("{agent} follows the default provider again", { agent: tx(agent.label) }),
        );
      },
    });

  return (
    <div className="card form">
      <div className="row spread">
        <h3>{tx("Model")}</h3>
        <span className="faint small">
          {pinned
            ? tx("assigned — every project")
            : tx("follows the default provider (Settings → Models)")}
        </span>
      </div>
      <p className="muted small" style={{ marginTop: 6 }}>
        {tx(
          "Pick the provider and model this agent works with. It runs there on every project, whatever the project profile says; if the provider cannot be reached the job fails with the reason.",
        )}
      </p>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <div className="field">
          <label>{tx("Provider")}</label>
          <select value={provider} disabled={!admin} onChange={(e) => pick(e.target.value)}>
            <option value="">
              {tx("default ({provider})", { provider: defaultProvider?.name ?? "…" })}
            </option>
            {(providers.data ?? []).map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
                {p.key_set ? "" : ` — ${tx("no key")}`}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>{tx("Model")}</label>
          {provider && known ? (
            <select
              className="mono"
              value={model}
              disabled={!admin}
              onChange={(e) => {
                setModel(e.target.value);
                setDirty(true);
              }}
            >
              <option value="">{tx("pick a model…")}</option>
              {model && !listed.includes(model) && <option value={model}>{model}</option>}
              {listed.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              className="mono"
              value={model}
              disabled={!admin || !provider}
              placeholder={
                !provider
                  ? tx("the provider's default model")
                  : spec && !spec.key_set
                    ? tx("add a key under Settings → Models first")
                    : tx("model id")
              }
              onChange={(e) => {
                setModel(e.target.value);
                setDirty(true);
              }}
            />
          )}
          {provider && spec && !spec.key_set && (
            <span className="faint tiny">
              {tx("no API key for {provider}", { provider: spec.label })}
            </span>
          )}
        </div>
      </div>
      {provider && models.error && (
        <div className="callout error">{describeError(models.error)}</div>
      )}
      {assign.error && <div className="callout error">{describeError(assign.error)}</div>}
      {test.data && test.data.name === provider && (
        <div
          className={`callout ${model && !test.data.models.includes(model) ? "warn" : "notice"}`}
        >
          {tx("Connected to {provider}: {n} model(s).", {
            provider: spec?.label ?? provider,
            n: test.data.models.length,
          })}{" "}
          {model &&
            (test.data.models.includes(model)
              ? tx("{model} is available.", { model })
              : tx("{model} is not in the vendor's list — it may still fail at run time.", {
                  model,
                }))}
        </div>
      )}
      {test.error && test.variables === provider && (
        <div className="callout error">{describeError(test.error)}</div>
      )}
      {admin && (
        <div className="row">
          <button
            className="btn primary"
            disabled={!dirty || assign.isPending || (!!provider && !model)}
            onClick={() => save({ provider: provider || null, model: model || null })}
          >
            {assign.isPending ? tx("Saving…") : tx("Save")}
          </button>
          <button
            className="btn"
            disabled={!provider || !spec?.key_set || test.isPending}
            onClick={() => test.mutate(provider)}
          >
            {test.isPending ? tx("Testing…") : tx("Test connection")}
          </button>
          {pinned && !dirty && (
            <button
              className="btn"
              disabled={assign.isPending}
              onClick={() => save({ provider: null, model: null })}
            >
              {tx("Clear assignment")}
            </button>
          )}
          {dirty && <span className="muted small">{tx("unsaved changes")}</span>}
        </div>
      )}
    </div>
  );
}

function RoleSetup({ projectId, role }: { projectId: string; role: string }) {
  const project = useProject(projectId);
  const defaults = useQuery({
    queryKey: ["settings", "profile"],
    queryFn: () => api.get<Profile>("/api/settings/profile"),
  });
  if (project.isLoading || defaults.isLoading) return <Loading />;
  if (!project.data || !defaults.data) return <ErrorBox error={project.error ?? defaults.error} />;
  const profile = project.data.profile ?? defaults.data;
  return (
    <RoleForm projectId={projectId} role={role} profile={profile} hasOwn={!!project.data.profile} />
  );
}

function RoleForm({
  projectId,
  role,
  profile,
  hasOwn,
}: {
  projectId: string;
  role: string;
  profile: Profile;
  hasOwn: boolean;
}) {
  const tx = useT();
  const { user } = useAuth();
  const patch = usePatchProject(projectId);
  const toast = useToast();
  const admin = !!user?.is_admin;
  const initial: RoleConfig = profile.roles[role] ?? {
    model: "",
    thinking_depth: "medium",
    permissions: [],
  };
  const [cfg, setCfg] = useState<RoleConfig>(initial);
  const [dirty, setDirty] = useState(false);
  const set = (patchCfg: Partial<RoleConfig>) => {
    setCfg({ ...cfg, ...patchCfg });
    setDirty(true);
  };

  const save = () =>
    patch.mutate(
      { profile: { ...profile, roles: { ...profile.roles, [role]: cfg } } },
      {
        onSuccess: () => {
          setDirty(false);
          toast.ok("Agent setup saved");
        },
      },
    );

  return (
    <div className="card form">
      <div className="row spread">
        <h3>{tx("Project profile")}</h3>
        <span className="faint small">
          {hasOwn ? tx("project profile") : tx("engine default (saved into the project on save)")}
        </span>
      </div>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <div className="field">
          <label>{tx("Thinking depth")}</label>
          <select
            value={cfg.thinking_depth}
            disabled={!admin}
            onChange={(e) =>
              set({ thinking_depth: e.target.value as RoleConfig["thinking_depth"] })
            }
          >
            {DEPTHS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>{tx("Permissions")}</label>
          <div className="row" style={{ gap: 8 }}>
            {PERMISSIONS.map((perm) => {
              const on = (cfg.permissions ?? []).includes(perm);
              return (
                <label key={perm} className="check">
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={!admin}
                    onChange={(e) => {
                      const current = cfg.permissions ?? [];
                      set({
                        permissions: e.target.checked
                          ? [...current, perm]
                          : current.filter((p) => p !== perm),
                      });
                    }}
                  />
                  {perm}
                </label>
              );
            })}
          </div>
        </div>
      </div>
      {patch.error && <div className="callout error">{describeError(patch.error)}</div>}
      {admin && (
        <div className="row">
          <button className="btn primary" disabled={!dirty || patch.isPending} onClick={save}>
            {patch.isPending ? tx("Saving…") : tx("Save")}
          </button>
          {dirty && <span className="muted small">{tx("unsaved changes")}</span>}
        </div>
      )}
    </div>
  );
}

// -- activity -------------------------------------------------------------------------------

function ActivityTab({ role }: { role: string }) {
  const tx = useT();
  const activity = useActivity_all(role);
  const projects = useProjects();
  const byId = new Map((projects.data ?? []).map((p) => [p.id, p]));
  if (activity.isLoading) return <Loading />;
  if (activity.error) return <ErrorBox error={activity.error} />;
  if (!activity.data || activity.data.length === 0) {
    return <Empty>{tx("This agent has not run yet.")}</Empty>;
  }
  return (
    <div className="card">
      <ul className="feed">
        {activity.data.map((item) => (
          <ActivityRow
            key={`${item.job_id}:${item.index}`}
            item={item}
            projectId={item.project_id ?? ""}
            projectName={byId.get(item.project_id ?? "")?.name}
          />
        ))}
      </ul>
    </div>
  );
}
