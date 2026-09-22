import { useState, type FormEvent } from "react";
import { describeError } from "../../api/client";
import { useGitHubIdentity, useGitHubSettings, useSaveGitHubSettings } from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { Crumbs } from "../../components/Crumbs";
import { useT } from "../../i18n";

export function GitHubSettingsPage() {
  const tx = useT();
  const { user } = useAuth();
  const settings = useGitHubSettings();
  const admin = !!user?.is_admin;

  if (settings.isLoading) return <Loading />;
  if (settings.error) return <ErrorBox error={settings.error} />;
  const s = settings.data!;

  return (
    <div>
      <Crumbs items={[{ label: "Settings" }, { label: "GitHub" }]} />
      <PageHead title={tx("GitHub")} subtitle={tx("Clone, push and open pull requests.")} />
      <ConnectionCard tokenSet={s.token_set} tokenHint={s.token_hint} admin={admin} />
      <DefaultsCard owner={s.owner} baseBranch={s.base_branch} admin={admin} />
      {!admin && <p className="muted small">{tx("Only admins can change these settings.")}</p>}
    </div>
  );
}

/** One line that answers "is GitHub connected, and as whom?"; the token field only when needed. */
function ConnectionCard({
  tokenSet,
  tokenHint,
  admin,
}: {
  tokenSet: boolean;
  tokenHint: string | null;
  admin: boolean;
}) {
  const tx = useT();
  const save = useSaveGitHubSettings();
  const identity = useGitHubIdentity(tokenSet, tokenHint);
  const [editing, setEditing] = useState(false);
  const [token, setToken] = useState("");
  const showForm = admin && (!tokenSet || editing);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    save.mutate(
      { token: token.trim() },
      {
        onSuccess: () => {
          setToken("");
          setEditing(false);
        },
      },
    );
  };

  let status: { kind: "ok" | "bad" | "wait" | "idle"; text: string; detail?: string };
  if (!tokenSet) {
    status = { kind: "idle", text: tx("Not connected") };
  } else if (identity.isPending) {
    status = { kind: "wait", text: tx("Checking…") };
  } else if (identity.error) {
    status = { kind: "bad", text: tx("Token rejected"), detail: describeError(identity.error) };
  } else {
    const id = identity.data!;
    const who = id.name ? `${id.login} (${id.name})` : id.login;
    const calls =
      id.rate_limit_remaining !== null
        ? ` · ${tx("{n} API calls left").replace("{n}", `${id.rate_limit_remaining}/${id.rate_limit_limit}`)}`
        : "";
    status = { kind: "ok", text: who, detail: `${tx("Token")} …${tokenHint?.slice(1)}${calls}` };
  }

  return (
    <div className="card connection">
      <div className="row spread">
        <div className="connection-status">
          <span className={`badge ${status.kind}`}>
            {status.kind === "ok" ? tx("Connected") : status.text}
          </span>
          {status.kind === "ok" && <strong>{status.text}</strong>}
        </div>
        {admin && tokenSet && !editing && (
          <div className="row">
            <button type="button" className="btn small" onClick={() => setEditing(true)}>
              {tx("Change token")}
            </button>
            <button
              type="button"
              className="btn small bad"
              disabled={save.isPending}
              onClick={() => save.mutate({ clear_token: true })}
            >
              {tx("Disconnect")}
            </button>
          </div>
        )}
      </div>
      {status.detail && (
        <div className={`muted small ${status.kind === "bad" ? "bad-text" : ""}`}>
          {status.detail}
        </div>
      )}
      {showForm && (
        <form className="form" onSubmit={submit}>
          <div className="field">
            <label htmlFor="gh-token">{tx("Personal access token")}</label>
            <input
              id="gh-token"
              type="password"
              autoComplete="off"
              autoFocus={editing}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="ghp_…"
            />
            <div className="muted small">
              {tx(
                "Used to clone private repositories, push job branches and open pull requests. Stored encrypted and never shown again.",
              )}
            </div>
          </div>
          {save.error && <div className="callout error">{describeError(save.error)}</div>}
          <div className="row">
            <button className="btn primary" disabled={save.isPending || !token.trim()}>
              {tokenSet ? tx("Save") : tx("Connect")}
            </button>
            {editing && (
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setEditing(false);
                  setToken("");
                }}
              >
                {tx("Cancel")}
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

/** Where new projects land by default. */
function DefaultsCard({
  owner,
  baseBranch,
  admin,
}: {
  owner: string | null;
  baseBranch: string;
  admin: boolean;
}) {
  const tx = useT();
  const save = useSaveGitHubSettings();
  const [draft, setDraft] = useState<{ owner?: string; base_branch?: string }>({});
  const [saved, setSaved] = useState(false);
  const dirty =
    (draft.owner !== undefined && draft.owner !== (owner ?? "")) ||
    (draft.base_branch !== undefined && draft.base_branch !== baseBranch);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      { owner: draft.owner ?? owner, base_branch: draft.base_branch ?? baseBranch },
      {
        onSuccess: () => {
          setDraft({});
          setSaved(true);
        },
      },
    );
  };

  return (
    <form className="form card" onSubmit={submit} style={{ marginTop: 16 }}>
      <h3>{tx("Defaults for new projects")}</h3>
      <div className="grid-2">
        <div className="field">
          <label htmlFor="gh-owner">{tx("Owner / organisation")}</label>
          <input
            id="gh-owner"
            type="text"
            value={draft.owner ?? owner ?? ""}
            disabled={!admin}
            onChange={(e) => {
              setSaved(false);
              setDraft({ ...draft, owner: e.target.value });
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="gh-branch">{tx("Base branch")}</label>
          <input
            id="gh-branch"
            type="text"
            value={draft.base_branch ?? baseBranch}
            disabled={!admin}
            onChange={(e) => {
              setSaved(false);
              setDraft({ ...draft, base_branch: e.target.value });
            }}
          />
        </div>
      </div>
      {save.error && <div className="callout error">{describeError(save.error)}</div>}
      {admin && (
        <div className="row">
          <button className="btn primary" disabled={save.isPending || !dirty}>
            {tx("Save")}
          </button>
          {saved && !dirty && <span className="muted small">{tx("Saved.")}</span>}
        </div>
      )}
    </form>
  );
}
