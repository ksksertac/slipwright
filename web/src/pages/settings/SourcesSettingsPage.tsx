// Where the code lives: one row per hosting service, collapsed to what matters — who it is
// connected as and which one new projects default to — and opening onto its token, its
// workspace and its base branch. Same shape as the models page, because it answers the
// same kind of question.
import { useState, type FormEvent } from "react";
import { describeError, type SourceSettings } from "../../api/client";
import { useSaveSource, useSources, useTestSource } from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { Crumbs } from "../../components/Crumbs";
import { IconCheck, IconChevron } from "../../components/icons";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { useT } from "../../i18n";

export function SourcesSettingsPage() {
  const tx = useT();
  const sources = useSources();
  if (sources.isLoading) return <Loading />;
  if (sources.error) return <ErrorBox error={sources.error} />;
  const list = sources.data!;
  const none = !list.some((s) => s.token_set);
  return (
    <div>
      <Crumbs items={[{ label: "Settings" }, { label: "Sources" }]} />
      <PageHead
        title={tx("Sources")}
        subtitle={tx("Where the code lives: clone, push and open pull requests.")}
      />
      <p className="muted">
        {tx(
          "Connect the services your repositories live on. A token is stored encrypted and never shown again; a token from the server's environment is used when none is stored. A project keeps the service it was created from, and new projects start on the one marked",
        )}{" "}
        <strong>{tx("default")}</strong>.
      </p>
      <div className="stack tight">
        {list.map((s, i) => (
          <SourceCard key={s.name} source={s} startOpen={none && i === 0} />
        ))}
      </div>
    </div>
  );
}

function SourceCard({ source: s, startOpen }: { source: SourceSettings; startOpen: boolean }) {
  const tx = useT();
  const { user } = useAuth();
  const save = useSaveSource();
  const test = useTestSource();
  const [open, setOpen] = useState(startOpen);
  const [token, setToken] = useState("");
  const [owner, setOwner] = useState<string | null>(null);
  const [baseBranch, setBaseBranch] = useState<string | null>(null);
  const [apiUrl, setApiUrl] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const admin = !!user?.is_admin;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      {
        name: s.name,
        token: token.trim() || null,
        owner: owner ?? s.owner ?? "",
        base_branch: baseBranch ?? s.base_branch,
        api_url: apiUrl ?? s.api_url ?? "",
      },
      {
        onSuccess: () => {
          setToken("");
          setSaved(true);
        },
      },
    );
  };

  // The one line to read when the row is shut.
  const summary = !s.token_set
    ? tx("add a token to use it")
    : s.owner || tx("no default {owner}", { owner: s.owner_label.toLowerCase() });

  return (
    <details
      className="card acc"
      open={open}
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>
        <IconChevron className="acc-chev" />
        <span className="acc-title">
          <span className="acc-name">
            {s.label}
            {s.is_default && <span className="tag">{tx("default")}</span>}
          </span>
          <span className="acc-sub">{summary}</span>
        </span>
        <span className="acc-right">
          {s.token_set ? (
            <span className="badge ok plain">
              <IconCheck />
              {tx("token set")} {s.token_hint}{" "}
              {s.token_from_env ? tx("(from {env})", { env: s.env_var }) : ""}
            </span>
          ) : (
            <span className="badge idle">{tx("not connected")}</span>
          )}
        </span>
      </summary>
      <form className="acc-body" onSubmit={submit}>
        <div className="grid-2">
          <div className="field">
            <label htmlFor={`${s.name}-token`}>{tx(s.token_label)}</label>
            <input
              id={`${s.name}-token`}
              type="password"
              autoComplete="off"
              value={token}
              disabled={!admin}
              onChange={(e) => setToken(e.target.value)}
              placeholder={
                s.token_set
                  ? tx("set, ends with {hint}", { hint: s.token_hint ?? "" })
                  : tx("paste a token")
              }
            />
            <div className="muted small">
              {tx("Create one at")}{" "}
              <a href={s.token_docs_url} target="_blank" rel="noreferrer">
                {s.token_docs_url.replace(/^https?:\/\//, "").slice(0, 48)}
              </a>
              ; {tx("or set")} <code>{s.env_var}</code> {tx("on the server.")}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${s.name}-owner`}>{tx(s.owner_label)}</label>
            <input
              id={`${s.name}-owner`}
              type="text"
              value={owner ?? s.owner ?? ""}
              disabled={!admin}
              onChange={(e) => setOwner(e.target.value)}
            />
            <div className="muted small">
              {tx("New projects look here first when listing repositories.")}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${s.name}-branch`}>{tx("Base branch")}</label>
            <input
              id={`${s.name}-branch`}
              type="text"
              className="mono"
              value={baseBranch ?? s.base_branch}
              disabled={!admin}
              onChange={(e) => setBaseBranch(e.target.value)}
            />
            <div className="muted small">
              {tx("What a pull request is opened against, and what a finished branch merges into.")}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${s.name}-api`}>{tx("API URL (optional)")}</label>
            <input
              id={`${s.name}-api`}
              type="url"
              className="mono"
              value={apiUrl ?? s.api_url ?? ""}
              disabled={!admin}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder={s.default_api_url}
            />
            <div className="muted small">
              {tx("Leave empty for {url}; set for a self-hosted server.", {
                url: s.default_api_url,
              })}
            </div>
          </div>
        </div>
        {save.error && <div className="callout error">{describeError(save.error)}</div>}
        {saved && <div className="callout notice">{tx("Saved.")}</div>}
        {admin && (
          <div className="row">
            <button className="btn primary small" disabled={save.isPending}>
              {tx("Save")}
            </button>
            <button
              type="button"
              className="btn small"
              disabled={!s.token_set || test.isPending}
              onClick={() => test.mutate(s.name)}
            >
              {test.isPending ? tx("Testing…") : tx("Test connection")}
            </button>
            {!s.is_default && (
              <button
                type="button"
                className="btn small"
                onClick={() => save.mutate({ name: s.name, make_default: true })}
              >
                {tx("Use as default")}
              </button>
            )}
            {s.token_set && !s.token_from_env && (
              <button
                type="button"
                className="btn bad small"
                onClick={() => save.mutate({ name: s.name, clear_token: true })}
              >
                {tx("Disconnect")}
              </button>
            )}
          </div>
        )}
        {test.data && test.variables === s.name && (
          <div className="callout notice">
            {tx("Connected as")} <strong>{test.data.login}</strong>
            {test.data.name ? ` (${test.data.name})` : ""}
            {test.data.rate_limit_remaining !== null && (
              <>
                {" · "}
                {tx("{n} API calls left", {
                  n: `${test.data.rate_limit_remaining}/${test.data.rate_limit_limit}`,
                })}
              </>
            )}
          </div>
        )}
        {test.error && test.variables === s.name && (
          <div className="callout error">{describeError(test.error)}</div>
        )}
      </form>
    </details>
  );
}
