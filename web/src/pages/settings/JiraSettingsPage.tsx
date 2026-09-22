import { useState, type FormEvent } from "react";
import { describeError, type JiraSettingsIn } from "../../api/client";
import {
  useJiraSettings,
  useJiraSweep,
  useRunJiraSweep,
  useSaveJiraSettings,
  useTestJira,
} from "../../api/hooks";
import { timeAgo } from "../../components/ui";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { Crumbs } from "../../components/Crumbs";
import { JiraAgentAccount, ProjectJiraSetup } from "../../components/JiraAgentSetup";
import { useT } from "../../i18n";

const TYPE_KEYS = ["epic", "story", "task", "bug"] as const;

export function JiraSettingsPage() {
  const tx = useT();
  const { user } = useAuth();
  const settings = useJiraSettings();
  const save = useSaveJiraSettings();
  const test = useTestJira();
  const [draft, setDraft] = useState<JiraSettingsIn>({});
  const [saved, setSaved] = useState(false);
  const admin = !!user?.is_admin;

  if (settings.isLoading) return <Loading />;
  if (settings.error) return <ErrorBox error={settings.error} />;
  const s = settings.data!;
  const types = { ...s.issue_types, ...(draft.issue_types ?? {}) };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      { ...draft, token: draft.token?.trim() || null },
      {
        onSuccess: () => {
          setDraft({});
          setSaved(true);
        },
      },
    );
  };

  return (
    <div>
      <Crumbs items={[{ label: "Settings" }, { label: "Jira" }]} />
      <PageHead
        title={tx("Jira")}
        subtitle={tx("Mirror epics, stories and tasks into your tracker.")}
      />
      <p className="muted">
        {tx(
          "With Jira connected, every approved plan is mirrored as epics, stories and sub-tasks in the project's Jira project, issues move as tasks complete, and PR links and failures are commented. This is the connection used by the engine; the account the agents themselves act as, and which Jira project each Slipwright project mirrors into, are set below.",
        )}
      </p>
      <form className="form card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="jira-site">{tx("Site URL")}</label>
          <input
            id="jira-site"
            type="url"
            value={draft.site_url ?? s.site_url ?? ""}
            disabled={!admin}
            onChange={(e) => setDraft({ ...draft, site_url: e.target.value })}
            placeholder={tx("https://your-team.atlassian.net")}
          />
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="jira-email">{tx("Account e-mail")}</label>
            <input
              id="jira-email"
              type="email"
              value={draft.email ?? s.email ?? ""}
              disabled={!admin}
              onChange={(e) => setDraft({ ...draft, email: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="jira-token">{tx("API token")}</label>
            <input
              id="jira-token"
              type="password"
              autoComplete="off"
              value={draft.token ?? ""}
              disabled={!admin}
              onChange={(e) => setDraft({ ...draft, token: e.target.value })}
              placeholder={
                s.token_set
                  ? tx("set, ends with {hint}", { hint: s.token_hint ?? "" })
                  : tx("not set")
              }
            />
          </div>
        </div>

        <h3>{tx("Issue type names")}</h3>
        <p className="muted small">
          {tx("As they are called in your Jira site. Tasks default to")}{" "}
          <code>{tx("Subtask")}</code> {tx("so they nest under stories;")}{" "}
          <code>{tx("Sub-task")}</code> {tx("is for older sites.")}
        </p>
        <div className="grid-2">
          {TYPE_KEYS.map((k) => (
            <div className="field" key={k}>
              <label htmlFor={`type-${k}`}>{k}</label>
              <input
                id={`type-${k}`}
                type="text"
                value={types[k] ?? ""}
                disabled={!admin}
                onChange={(e) =>
                  setDraft({ ...draft, issue_types: { ...types, [k]: e.target.value } })
                }
              />
            </div>
          ))}
        </div>

        {save.error && <div className="callout error">{describeError(save.error)}</div>}
        {saved && <div className="callout notice">{tx("Saved.")}</div>}
        {admin ? (
          <div className="row">
            <button className="btn primary" disabled={save.isPending}>
              {tx("Save")}
            </button>
            <button
              type="button"
              className="btn"
              disabled={!s.token_set || test.isPending}
              onClick={() => test.mutate()}
            >
              {test.isPending ? tx("Testing…") : tx("Test connection")}
            </button>
            {s.token_set && (
              <button
                type="button"
                className="btn bad"
                onClick={() => save.mutate({ clear_token: true })}
              >
                {tx("Remove token")}
              </button>
            )}
          </div>
        ) : (
          <div className="muted small">{tx("Only admins can change these settings.")}</div>
        )}
        {test.data && (
          <div className="callout notice">
            {tx("Connected as")} <strong>{test.data.account.display_name}</strong>
            {test.data.agent_account && (
              <>
                {" "}
                · agents act as <strong>{test.data.agent_account.display_name}</strong>
              </>
            )}
            <div className="small">
              Projects: {test.data.projects.map((p) => `${p.key} (${p.name})`).join(", ") || "none"}
            </div>
          </div>
        )}
        {test.error && <div className="callout error">{describeError(test.error)}</div>}
      </form>

      <h2 style={{ marginTop: 28, marginBottom: 12 }}>{tx("Agents in Jira")}</h2>
      <div className="grid-2" style={{ alignItems: "start" }}>
        <JiraAgentAccount />
        <ProjectJiraSetup />
      </div>
      <SweepCard admin={admin} />
    </div>
  );
}

/** The PO's round: what the hourly sweep did last, and a button to run it now. */
function SweepCard({ admin }: { admin: boolean }) {
  const tx = useT();
  const last = useJiraSweep();
  const run = useRunJiraSweep();
  const s = last.data;
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="row spread">
        <h3>{tx("The Product Owner's round")}</h3>
        {admin && (
          <button className="btn small" disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? tx("Running…") : tx("Run now")}
          </button>
        )}
      </div>
      <p className="muted small">
        {tx(
          "At startup and every hour, every development of a Jira-linked project is checked: missing epics, stories and sub-tasks are created, stories join the sprint (one is started when none is running), statuses catch up.",
        )}
      </p>
      <div className="small">
        {s
          ? tx(
              "Last round {when}: {jobs} development(s) checked, {updated} updated, {errors} with Jira errors.",
              { when: timeAgo(s.at), jobs: s.jobs, updated: s.updated, errors: s.errors },
            )
          : tx("No round has run yet.")}
      </div>
      {run.error && <div className="callout error">{describeError(run.error)}</div>}
    </div>
  );
}
