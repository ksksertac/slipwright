import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, describeError, type Profile, type Project } from "../../api/client";
import {
  useJiraProjects,
  useJiraSettings,
  usePatchProject,
  useProject,
  useProjects,
  useSaveJiraSettings,
  useTestJira,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { ProfileForm } from "../../components/ProfileForm";
import { ErrorBox, Loading } from "../../components/ui";

const STATUSES = ["todo", "in_progress", "done", "failed"] as const;

/**
 * Everything about how the agents behave: which account they act as in Jira, and per
 * project the seed profile (model, thinking depth and permissions per role — the Jira
 * permission is the "may act in Jira" toggle) plus the Jira project and transitions.
 */
export function AgentsSettingsPage() {
  const projects = useProjects();
  const [selected, setSelected] = useState<string>("");
  const projectId = selected || projects.data?.[0]?.id || "";

  return (
    <div>
      <h1>Agents</h1>
      <AgentAccount />

      <h2>Per-project agent setup</h2>
      <p className="muted">
        Each project starts its jobs from a seed profile. Model and thinking depth per role are read
        from it — never from the engine — and a role may act in Jira only when its
        <code> jira</code> permission is on.
      </p>
      <ErrorBox error={projects.error} />
      {projects.data && projects.data.length === 0 && (
        <div className="card muted">
          No projects yet. <Link to="/projects/new">Create one</Link> first.
        </div>
      )}
      {projects.data && projects.data.length > 0 && (
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="project">Project</label>
          <select id="project" value={projectId} onChange={(e) => setSelected(e.target.value)}>
            {projects.data.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {projectId && <ProjectAgents key={projectId} projectId={projectId} />}
    </div>
  );
}

function AgentAccount() {
  const { user } = useAuth();
  const jira = useJiraSettings();
  const save = useSaveJiraSettings();
  const test = useTestJira();
  const [email, setEmail] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const [saved, setSaved] = useState(false);
  const admin = !!user?.is_admin;
  if (jira.isLoading) return <Loading />;
  if (!jira.data) return <ErrorBox error={jira.error} />;
  const s = jira.data;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      { agent_email: email ?? s.agent_email, agent_token: token.trim() || null },
      {
        onSuccess: () => {
          setToken("");
          setSaved(true);
        },
      },
    );
  };

  return (
    <form className="form card" onSubmit={submit}>
      <h3>Jira account for the agents</h3>
      <p className="muted small">
        Comments, transitions and bug issues the agents create appear under this account, so Jira
        history shows the bot and not the person who configured the connection.
      </p>
      {!s.token_set && (
        <div className="hint small">
          Jira is not connected yet: <Link to="/settings/jira">set up the connection</Link> first.
        </div>
      )}
      {s.token_set && !s.agent_token_set && (
        <div className="hint small">
          No agent account is set: agents would act through the human connection ({s.email}).
        </div>
      )}
      <div className="grid-2">
        <div className="field">
          <label htmlFor="agent-email">Agent e-mail</label>
          <input
            id="agent-email"
            type="email"
            value={email ?? s.agent_email ?? ""}
            disabled={!admin}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="slipwright-bot@example.com"
          />
        </div>
        <div className="field">
          <label htmlFor="agent-token">Agent API token</label>
          <input
            id="agent-token"
            type="password"
            autoComplete="off"
            value={token}
            disabled={!admin}
            onChange={(e) => setToken(e.target.value)}
            placeholder={s.agent_token_set ? `set, ends with ${s.agent_token_hint}` : "not set"}
          />
        </div>
      </div>
      {save.error && <div className="error">{describeError(save.error)}</div>}
      {saved && <div className="notice">Saved.</div>}
      {admin && (
        <div className="row">
          <button className="btn primary" disabled={save.isPending}>
            Save
          </button>
          <button
            type="button"
            className="btn"
            disabled={!s.agent_token_set || test.isPending}
            onClick={() => test.mutate()}
          >
            {test.isPending ? "Testing…" : "Test connection"}
          </button>
          {s.agent_token_set && (
            <button
              type="button"
              className="btn bad"
              onClick={() => save.mutate({ clear_agent_token: true })}
            >
              Remove agent token
            </button>
          )}
        </div>
      )}
      {test.data?.agent_account && (
        <div className="notice">
          Agents act as <strong>{test.data.agent_account.display_name}</strong> (
          {test.data.agent_account.email})
        </div>
      )}
      {test.data && !test.data.agent_account && (
        <div className="hint">The connection works but no agent account is configured.</div>
      )}
      {test.error && <div className="error">{describeError(test.error)}</div>}
    </form>
  );
}

function ProjectAgents({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  const defaults = useQuery({
    queryKey: ["settings", "profile"],
    queryFn: () => api.get<Profile>("/api/settings/profile"),
  });
  if (project.isLoading || defaults.isLoading) return <Loading />;
  if (project.error) return <ErrorBox error={project.error} />;
  if (!project.data || !defaults.data) return null;
  return <ProjectAgentsForm project={project.data} defaults={defaults.data} />;
}

function ProjectAgentsForm({ project, defaults }: { project: Project; defaults: Profile }) {
  const { user } = useAuth();
  const patch = usePatchProject(project.id);
  const jira = useJiraSettings();
  const jiraProjects = useJiraProjects(!!jira.data?.token_set);
  const [profile, setProfile] = useState<Profile>(project.profile ?? defaults);
  const [jiraKey, setJiraKey] = useState(project.jira_project_key ?? "");
  const [transitions, setTransitions] = useState<Record<string, string>>(
    project.jira_transitions ?? {},
  );
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const admin = !!user?.is_admin;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    patch.mutate(
      {
        profile,
        jira_project_key: jiraKey.trim() || null,
        jira_transitions: Object.fromEntries(
          Object.entries(transitions).filter(([, v]) => v.trim()),
        ),
      },
      {
        onSuccess: () => {
          setDirty(false);
          setSaved(true);
        },
      },
    );
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="row spread">
        <h3>{project.name}</h3>
        <span className="muted small">
          {project.profile ? "has its own seed profile" : "using the engine default (unsaved)"}
        </span>
      </div>

      <h3 style={{ marginTop: 12 }}>Jira</h3>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="jira-key">Jira project</label>
          {jiraProjects.data && jiraProjects.data.length > 0 ? (
            <select
              id="jira-key"
              value={jiraKey}
              disabled={!admin}
              onChange={(e) => {
                setJiraKey(e.target.value);
                setDirty(true);
              }}
            >
              <option value="">Not linked</option>
              {jiraProjects.data.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.key} — {p.name}
                </option>
              ))}
            </select>
          ) : (
            <input
              id="jira-key"
              type="text"
              className="mono"
              value={jiraKey}
              disabled={!admin}
              onChange={(e) => {
                setJiraKey(e.target.value.toUpperCase());
                setDirty(true);
              }}
              placeholder="e.g. DEM"
            />
          )}
        </div>
        <div className="field">
          <label>Task status → Jira transition</label>
          <div className="stack" style={{ gap: 4 }}>
            {STATUSES.map((st) => (
              <div className="row" key={st}>
                <span className="mono small" style={{ width: 90 }}>
                  {st}
                </span>
                <input
                  type="text"
                  value={transitions[st] ?? ""}
                  disabled={!admin}
                  onChange={(e) => {
                    setTransitions({ ...transitions, [st]: e.target.value });
                    setDirty(true);
                  }}
                  placeholder={
                    st === "failed"
                      ? "(comment only)"
                      : { todo: "To Do", in_progress: "In Progress", done: "Done" }[st]
                  }
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      <h3 style={{ marginTop: 12 }}>Roles: model, thinking depth, permissions</h3>
      <p className="muted small">
        The <code>jira</code> permission lets a role return Jira actions (comments, transitions,
        bugs, worklogs) that the engine executes through the agent account.
      </p>
      <ProfileForm
        value={profile}
        disabled={!admin}
        onChange={(next) => {
          setProfile(next);
          setDirty(true);
        }}
      />
      {patch.error && <div className="error">{describeError(patch.error)}</div>}
      {saved && <div className="notice">Saved.</div>}
      {admin && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" disabled={!dirty || patch.isPending}>
            {patch.isPending ? "Saving…" : "Save project settings"}
          </button>
          {dirty && <span className="muted small">unsaved changes</span>}
        </div>
      )}
    </form>
  );
}
