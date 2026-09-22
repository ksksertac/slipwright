// Jira setup as a sequence: connect, choose who the agents write as, name the issue
// types, map each project, then the round that keeps it all true. Each step says in one
// line what it is for and shows whether it is done, so the page reads top to bottom.
import { useState, type FormEvent, type ReactNode } from "react";
import { describeError, type JiraSettingsIn } from "../../api/client";
import {
  useJiraSettings,
  useJiraSweep,
  useRunJiraSweep,
  useSaveJiraSettings,
  useTestJira,
} from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { Crumbs } from "../../components/Crumbs";
import { JiraAgentAccount, ProjectJiraSetup } from "../../components/JiraAgentSetup";
import { ErrorBox, Loading, PageHead, timeAgo } from "../../components/ui";
import { useT } from "../../i18n";

const TYPE_KEYS = ["epic", "story", "task", "bug"] as const;

type StepState = "done" | "todo" | "optional";

function Step({
  n,
  title,
  why,
  state,
  stateText,
  children,
}: {
  n: number;
  title: string;
  why: string;
  state: StepState;
  stateText: string;
  children: ReactNode;
}) {
  const badge = state === "done" ? "ok" : state === "todo" ? "wait" : "idle";
  return (
    <section className="card step">
      <div className="row spread" style={{ alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>
          <span className="step-n">{n}</span> {title}
        </h3>
        <span className={`badge ${badge}`}>{stateText}</span>
      </div>
      <p className="muted small" style={{ margin: "4px 0 14px" }}>
        {why}
      </p>
      {children}
    </section>
  );
}

export function JiraSettingsPage() {
  const tx = useT();
  const { user } = useAuth();
  const settings = useJiraSettings();
  const admin = !!user?.is_admin;

  if (settings.isLoading) return <Loading />;
  if (settings.error) return <ErrorBox error={settings.error} />;
  const s = settings.data!;

  return (
    <div className="settings-flow">
      <Crumbs items={[{ label: "Settings" }, { label: "Jira" }]} />
      <PageHead
        title={tx("Jira")}
        subtitle={tx("Mirror epics, stories and tasks into your tracker.")}
      />
      <p className="muted">
        {tx(
          "Once this is set up an approved plan appears in Jira by itself: the Product Owner creates the epics, stories and sub-tasks, the specialists move them as they work, and pull request links and failures are commented. Five steps, top to bottom.",
        )}
      </p>

      <Step
        n={1}
        title={tx("The connection")}
        why={tx(
          "The Jira site and the account Slipwright signs in with. Nothing works without it.",
        )}
        state={s.token_set ? "done" : "todo"}
        stateText={s.token_set ? tx("connected") : tx("not connected yet")}
      >
        <ConnectionForm admin={admin} />
      </Step>

      <Step
        n={2}
        title={tx("Who the agents write as")}
        why={tx(
          "Optional: a second Jira account for the bot, so comments and transitions carry its name instead of yours.",
        )}
        state={s.agent_token_set ? "done" : "optional"}
        stateText={s.agent_token_set ? tx("its own account") : tx("your account")}
      >
        <JiraAgentAccount />
      </Step>

      <Step
        n={3}
        title={tx("Issue type names")}
        why={tx(
          "What your Jira site calls an epic, a story, a task and a bug. The defaults fit most sites.",
        )}
        state="optional"
        stateText={tx("defaults")}
      >
        <IssueTypesForm admin={admin} />
      </Step>

      <Step
        n={4}
        title={tx("Which project goes where")}
        why={tx(
          "Each Slipwright project mirrors into one Jira project, and each task status becomes a transition there.",
        )}
        state="todo"
        stateText={tx("per project")}
      >
        <ProjectJiraSetup />
      </Step>

      <SweepStep admin={admin} />
    </div>
  );
}

/** Step 1: site, account and token — plus the connection test. */
function ConnectionForm({ admin }: { admin: boolean }) {
  const tx = useT();
  const settings = useJiraSettings();
  const save = useSaveJiraSettings();
  const test = useTestJira();
  const [draft, setDraft] = useState<JiraSettingsIn>({});
  const [saved, setSaved] = useState(false);
  const s = settings.data!;

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
    <form className="form" onSubmit={submit}>
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
          <div className="muted small">
            {tx("Create one in Atlassian under Account settings → Security → API tokens.")}
          </div>
        </div>
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
              · {tx("agents act as")} <strong>{test.data.agent_account.display_name}</strong>
            </>
          )}
          <div className="small">
            {tx("Projects this account can see:")}{" "}
            {test.data.projects.map((p) => `${p.key} (${p.name})`).join(", ") || tx("none")}
          </div>
        </div>
      )}
      {test.error && <div className="callout error">{describeError(test.error)}</div>}
    </form>
  );
}

/** Step 3: the four type names, saved with the rest of the connection settings. */
function IssueTypesForm({ admin }: { admin: boolean }) {
  const tx = useT();
  const settings = useJiraSettings();
  const save = useSaveJiraSettings();
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [saved, setSaved] = useState(false);
  const types: Record<string, string> = { ...settings.data!.issue_types, ...(draft ?? {}) };

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        setSaved(false);
        save.mutate(
          { issue_types: types },
          {
            onSuccess: () => {
              setDraft(null);
              setSaved(true);
            },
          },
        );
      }}
    >
      <p className="muted small" style={{ marginTop: 0 }}>
        {tx("Tasks default to")} <code>{tx("Subtask")}</code> {tx("so they nest under stories;")}{" "}
        <code>{tx("Sub-task")}</code> {tx("is for older sites.")}
      </p>
      <div className="grid-2">
        {TYPE_KEYS.map((k) => (
          <div className="field" key={k}>
            <label htmlFor={`type-${k}`}>{tx(k)}</label>
            <input
              id={`type-${k}`}
              type="text"
              value={types[k] ?? ""}
              disabled={!admin}
              onChange={(e) => setDraft({ ...types, [k]: e.target.value })}
            />
          </div>
        ))}
      </div>
      {save.error && <div className="callout error">{describeError(save.error)}</div>}
      {saved && <div className="callout notice">{tx("Saved.")}</div>}
      {admin && (
        <div className="row">
          <button className="btn primary small" disabled={save.isPending || draft === null}>
            {tx("Save")}
          </button>
        </div>
      )}
    </form>
  );
}

/** Step 5: the PO's round — what the hourly sweep did last, and a button to run it now. */
function SweepStep({ admin }: { admin: boolean }) {
  const tx = useT();
  const last = useJiraSweep();
  const run = useRunJiraSweep();
  const s = last.data;
  return (
    <Step
      n={5}
      title={tx("The Product Owner's round")}
      why={tx(
        "Runs by itself at startup and every hour: missing epics, stories and sub-tasks are created, stories join the sprint (one is started when none is running), statuses catch up. Nothing to set — this is how a half-mirrored plan repairs itself.",
      )}
      state={s ? "done" : "optional"}
      stateText={s ? tx("last run {when}", { when: timeAgo(s.at) }) : tx("not run yet")}
    >
      <div className="small">
        {s
          ? tx(
              "Last round {when}: {jobs} development(s) checked, {updated} updated, {errors} with Jira errors.",
              { when: timeAgo(s.at), jobs: s.jobs, updated: s.updated, errors: s.errors },
            )
          : tx("No round has run yet.")}
      </div>
      {admin && (
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn small" disabled={run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? tx("Running…") : tx("Run now")}
          </button>
        </div>
      )}
      {run.error && <div className="callout error">{describeError(run.error)}</div>}
    </Step>
  );
}
