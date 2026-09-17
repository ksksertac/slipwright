import { useState, type FormEvent } from "react";
import { describeError, type JiraSettingsIn } from "../../api/client";
import { useJiraSettings, useSaveJiraSettings, useTestJira } from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading } from "../../components/ui";

const TYPE_KEYS = ["epic", "story", "task", "bug"] as const;

export function JiraSettingsPage() {
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
      <h1>Jira</h1>
      <p className="muted">
        With Jira connected, every approved plan is mirrored as epics, stories and sub-tasks in the
        project's Jira project, issues move as tasks complete, and PR links and failures are
        commented. This is the connection used by the engine; the account the agents themselves act
        as is set under <strong>Agents</strong>.
      </p>
      <form className="form card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="jira-site">Site URL</label>
          <input
            id="jira-site"
            type="url"
            value={draft.site_url ?? s.site_url ?? ""}
            disabled={!admin}
            onChange={(e) => setDraft({ ...draft, site_url: e.target.value })}
            placeholder="https://your-team.atlassian.net"
          />
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="jira-email">Account e-mail</label>
            <input
              id="jira-email"
              type="email"
              value={draft.email ?? s.email ?? ""}
              disabled={!admin}
              onChange={(e) => setDraft({ ...draft, email: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="jira-token">API token</label>
            <input
              id="jira-token"
              type="password"
              autoComplete="off"
              value={draft.token ?? ""}
              disabled={!admin}
              onChange={(e) => setDraft({ ...draft, token: e.target.value })}
              placeholder={s.token_set ? `set, ends with ${s.token_hint}` : "not set"}
            />
          </div>
        </div>

        <h3>Issue type names</h3>
        <p className="muted small">
          As they are called in your Jira site. Tasks default to <code>Subtask</code> so they nest
          under stories; use <code>Sub-task</code> on older sites.
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

        {save.error && <div className="error">{describeError(save.error)}</div>}
        {saved && <div className="notice">Saved.</div>}
        {admin ? (
          <div className="row">
            <button className="btn primary" disabled={save.isPending}>
              Save
            </button>
            <button
              type="button"
              className="btn"
              disabled={!s.token_set || test.isPending}
              onClick={() => test.mutate()}
            >
              {test.isPending ? "Testing…" : "Test connection"}
            </button>
            {s.token_set && (
              <button
                type="button"
                className="btn bad"
                onClick={() => save.mutate({ clear_token: true })}
              >
                Remove token
              </button>
            )}
          </div>
        ) : (
          <div className="muted small">Only admins can change these settings.</div>
        )}
        {test.data && (
          <div className="notice">
            Connected as <strong>{test.data.account.display_name}</strong>
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
        {test.error && <div className="error">{describeError(test.error)}</div>}
      </form>
    </div>
  );
}
