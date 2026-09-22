import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { describeError, type Project } from "../api/client";
import {
  useJiraProjects,
  useJiraSettings,
  usePatchProject,
  useProject,
  useProjects,
  useSaveJiraSettings,
  useTestJira,
} from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { useToast } from "./Toast";
import { ErrorBox, Loading } from "./ui";
import { useT } from "../i18n";

const STATUSES = ["todo", "in_progress", "done", "failed"] as const;
const DEFAULT_TRANSITION: Record<string, string> = {
  todo: "To Do",
  in_progress: "In Progress",
  done: "Done",
  failed: "(comment only)",
};

/** The separate Jira account the agents act as. */
export function JiraAgentAccount() {
  const tx = useT();
  const { user } = useAuth();
  const jira = useJiraSettings();
  const save = useSaveJiraSettings();
  const test = useTestJira();
  const toast = useToast();
  const [email, setEmail] = useState<string | null>(null);
  const [token, setToken] = useState("");
  const admin = !!user?.is_admin;
  if (jira.isLoading) return <Loading />;
  if (!jira.data) return <ErrorBox error={jira.error} />;
  const s = jira.data;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(
      { agent_email: email ?? s.agent_email, agent_token: token.trim() || null },
      {
        onSuccess: () => {
          setToken("");
          toast.ok("Agent account saved");
        },
      },
    );
  };

  return (
    <form className="card" onSubmit={submit}>
      <h3 style={{ marginBottom: 6 }}>{tx("Jira account for the agents")}</h3>
      <p className="muted small">
        {tx(
          "Comments, transitions and bug issues the agents create appear under this account, so Jira history shows the bot and not the person who configured the connection.",
        )}
      </p>
      {!s.token_set && (
        <div className="callout hint">
          {tx("Jira is not connected yet:")}{" "}
          <Link to="/settings/jira">{tx("set up the connection")}</Link> {tx("first.")}
        </div>
      )}
      {s.token_set && !s.agent_token_set && (
        <div className="callout hint">
          No agent account is set: agents would act through the human connection ({s.email}).
        </div>
      )}
      <div className="grid-2">
        <div className="field">
          <label htmlFor="agent-email">{tx("Agent e-mail")}</label>
          <input
            id="agent-email"
            type="email"
            value={email ?? s.agent_email ?? ""}
            disabled={!admin}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={tx("slipwright-bot@example.com")}
          />
        </div>
        <div className="field">
          <label htmlFor="agent-token">{tx("Agent API token")}</label>
          <input
            id="agent-token"
            type="password"
            autoComplete="off"
            value={token}
            disabled={!admin}
            onChange={(e) => setToken(e.target.value)}
            placeholder={
              s.agent_token_set
                ? tx("set, ends with {hint}", { hint: s.agent_token_hint ?? "" })
                : tx("not set")
            }
          />
        </div>
      </div>
      {save.error && <div className="callout error">{describeError(save.error)}</div>}
      {admin && (
        <div className="row">
          <button className="btn primary small" disabled={save.isPending}>
            {tx("Save")}
          </button>
          <button
            type="button"
            className="btn small"
            disabled={!s.agent_token_set || test.isPending}
            onClick={() => test.mutate()}
          >
            {test.isPending ? tx("Testing…") : tx("Test connection")}
          </button>
          {s.agent_token_set && (
            <button
              type="button"
              className="btn bad small"
              onClick={() => save.mutate({ clear_agent_token: true })}
            >
              {tx("Remove agent token")}
            </button>
          )}
        </div>
      )}
      {test.data?.agent_account && (
        <div className="callout notice">
          {tx("Agents act as")} <strong>{test.data.agent_account.display_name}</strong> (
          {test.data.agent_account.email})
        </div>
      )}
      {test.data && !test.data.agent_account && (
        <div className="callout hint">
          {tx("The connection works but no agent account is configured.")}
        </div>
      )}
      {test.error && <div className="callout error">{describeError(test.error)}</div>}
    </form>
  );
}

/** Which Jira project a Slipwright project mirrors into, and its transition names. */
export function ProjectJiraSetup() {
  const tx = useT();
  const projects = useProjects();
  const [selected, setSelected] = useState("");
  const projectId = selected || projects.data?.[0]?.id || "";
  return (
    <div className="card">
      <h3 style={{ marginBottom: 6 }}>{tx("Project → Jira project")}</h3>
      <p className="muted small">
        {tx(
          "Approved plans are mirrored as epics, stories and sub-tasks here; task statuses map to the transition names below.",
        )}
      </p>
      {projects.data && projects.data.length === 0 && (
        <div className="muted small">
          {tx("No projects yet.")} <Link to="/projects/new">{tx("Create one")}</Link> {tx("first.")}
        </div>
      )}
      {projects.data && projects.data.length > 0 && (
        <div className="field">
          <label htmlFor="jira-project">{tx("Project")}</label>
          <select id="jira-project" value={projectId} onChange={(e) => setSelected(e.target.value)}>
            {projects.data.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {projectId && <ProjectJiraForm key={projectId} projectId={projectId} />}
    </div>
  );
}

function ProjectJiraForm({ projectId }: { projectId: string }) {
  const project = useProject(projectId);
  if (project.isLoading) return <Loading />;
  if (!project.data) return <ErrorBox error={project.error} />;
  return <ProjectJiraFields project={project.data} />;
}

function ProjectJiraFields({ project }: { project: Project }) {
  const tx = useT();
  const { user } = useAuth();
  const patch = usePatchProject(project.id);
  const toast = useToast();
  const jira = useJiraSettings();
  const jiraProjects = useJiraProjects(!!jira.data?.token_set);
  const [jiraKey, setJiraKey] = useState(project.jira_project_key ?? "");
  const [transitions, setTransitions] = useState<Record<string, string>>(
    project.jira_transitions ?? {},
  );
  const [dirty, setDirty] = useState(false);
  const admin = !!user?.is_admin;

  const save = () =>
    patch.mutate(
      {
        jira_project_key: jiraKey.trim() || null,
        jira_transitions: Object.fromEntries(
          Object.entries(transitions).filter(([, v]) => v.trim()),
        ),
      },
      {
        onSuccess: () => {
          setDirty(false);
          toast.ok("Jira mapping saved");
        },
      },
    );

  return (
    <div>
      <div className="field">
        <label htmlFor="jira-key">{tx("Jira project key")}</label>
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
            <option value="">{tx("Not linked")}</option>
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
            placeholder={tx("e.g. DEM")}
          />
        )}
      </div>
      <label>{tx("Task status → Jira transition")}</label>
      <div className="stack" style={{ gap: 6 }}>
        {STATUSES.map((st) => (
          <div className="row" key={st} style={{ flexWrap: "nowrap" }}>
            <span className="mono small" style={{ width: 96 }}>
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
              placeholder={DEFAULT_TRANSITION[st]}
            />
          </div>
        ))}
      </div>
      {patch.error && <div className="callout error">{describeError(patch.error)}</div>}
      {admin && (
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn primary small" disabled={!dirty || patch.isPending} onClick={save}>
            {patch.isPending ? tx("Saving…") : tx("Save")}
          </button>
        </div>
      )}
    </div>
  );
}
