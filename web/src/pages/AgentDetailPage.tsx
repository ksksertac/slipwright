import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, useParams } from "react-router-dom";
import { api, describeError, type Permission, type Profile, type RoleConfig } from "../api/client";
import { useActivity_all, useAgents, usePatchProject, useProject, useProjects } from "../api/hooks";
import { ActivityRow } from "../components/ActivityRow";
import { AgentIcon } from "../components/agents";
import { Crumbs } from "../components/Crumbs";
import { useToast } from "../components/Toast";
import { Empty, ErrorBox, Loading } from "../components/ui";
import { useAuth } from "../auth/AuthProvider";
import { useProviderModels, useProviders } from "../api/hooks";
import { AgentStandardsTab } from "./AgentStandardsTab";

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
          <span className="agent-ico lg">
            <AgentIcon role={agent.role} />
          </span>
          <div>
            <h1>{agent.label}</h1>
            <p>{agent.scope}</p>
          </div>
        </div>
      </div>
      <nav className="tabs">
        {TABS.map((t) => (
          <NavLink key={t} to={`/agents/${role}/${t}`} className={t === current ? "active" : ""}>
            {t[0]!.toUpperCase() + t.slice(1)}
          </NavLink>
        ))}
      </nav>
      {current === "setup" && <SetupTab role={role} />}
      {current === "standards" && <AgentStandardsTab role={role} domain={agent.standards_domain} />}
      {current === "activity" && <ActivityTab role={role} />}
    </div>
  );
}

// -- setup: this role's row of a project's seed profile ------------------------------------

function SetupTab({ role }: { role: string }) {
  const projects = useProjects();
  const [selected, setSelected] = useState("");
  const projectId = selected || projects.data?.[0]?.id || "";
  return (
    <div className="stack">
      <p className="muted small">
        Model, thinking depth and permissions are read from the project's seed profile — never from
        engine code. Pick a project; projects without their own profile start from the engine
        default and get one when you save.
      </p>
      {projects.data && projects.data.length === 0 && (
        <Empty>
          No projects yet. <Link to="/projects/new">Create one</Link> first.
        </Empty>
      )}
      {projects.data && projects.data.length > 0 && (
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="agent-project">Project</label>
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
  const { user } = useAuth();
  const patch = usePatchProject(projectId);
  const toast = useToast();
  const providers = useProviders();
  const admin = !!user?.is_admin;
  const initial: RoleConfig = profile.roles[role] ?? {
    model: "",
    thinking_depth: "medium",
    permissions: [],
  };
  const [cfg, setCfg] = useState<RoleConfig>(initial);
  const [dirty, setDirty] = useState(false);
  const defaultProvider = providers.data?.find((p) => p.is_default)?.name ?? "anthropic";
  const models = useProviderModels(cfg.provider ?? defaultProvider);
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
        <h3>Routing</h3>
        <span className="faint small">
          {hasOwn ? "project profile" : "engine default (saved into the project on save)"}
        </span>
      </div>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <div className="field">
          <label>Provider</label>
          <select
            value={cfg.provider ?? ""}
            disabled={!admin}
            onChange={(e) => set({ provider: e.target.value || null })}
          >
            <option value="">default ({defaultProvider})</option>
            {(providers.data ?? []).map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
                {p.key_set ? "" : " — no key"}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Model</label>
          <input
            type="text"
            className="mono"
            list={`models-${role}`}
            value={cfg.model}
            disabled={!admin}
            onChange={(e) => set({ model: e.target.value })}
          />
          <datalist id={`models-${role}`}>
            {(models.data?.models ?? []).map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        </div>
        <div className="field">
          <label>Thinking depth</label>
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
          <label>Permissions</label>
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
            {patch.isPending ? "Saving…" : "Save"}
          </button>
          {dirty && <span className="muted small">unsaved changes</span>}
        </div>
      )}
    </div>
  );
}

// -- activity -------------------------------------------------------------------------------

function ActivityTab({ role }: { role: string }) {
  const activity = useActivity_all(role);
  const projects = useProjects();
  const byId = new Map((projects.data ?? []).map((p) => [p.id, p]));
  if (activity.isLoading) return <Loading />;
  if (activity.error) return <ErrorBox error={activity.error} />;
  if (!activity.data || activity.data.length === 0) {
    return <Empty>This agent has not run yet.</Empty>;
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
