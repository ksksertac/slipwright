import { useState, type FormEvent } from "react";
import { describeError } from "../../api/client";
import { useGitHubSettings, useSaveGitHubSettings, useTestGitHub } from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { Crumbs } from "../../components/Crumbs";

export function GitHubSettingsPage() {
  const { user } = useAuth();
  const settings = useGitHubSettings();
  const save = useSaveGitHubSettings();
  const test = useTestGitHub();
  const [token, setToken] = useState("");
  const [owner, setOwner] = useState<string | null>(null);
  const [baseBranch, setBaseBranch] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const admin = !!user?.is_admin;

  if (settings.isLoading) return <Loading />;
  if (settings.error) return <ErrorBox error={settings.error} />;
  const s = settings.data!;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      {
        token: token.trim() || null,
        owner: owner ?? s.owner,
        base_branch: baseBranch ?? s.base_branch,
      },
      {
        onSuccess: () => {
          setToken("");
          setSaved(true);
        },
      },
    );
  };

  return (
    <div>
      <Crumbs items={[{ label: "Settings" }, { label: "GitHub" }]} />
      <PageHead title="GitHub" subtitle="Clone, push and open pull requests." />
      <p className="muted">
        The token is used to clone private repositories, push job branches and open pull requests.
        It is stored encrypted and never shown again.
      </p>
      <form className="form card" onSubmit={submit}>
        <div className="field">
          <label htmlFor="gh-token">Personal access token</label>
          <input
            id="gh-token"
            type="password"
            autoComplete="off"
            value={token}
            disabled={!admin}
            onChange={(e) => setToken(e.target.value)}
            placeholder={s.token_set ? `set, ends with ${s.token_hint}` : "not set"}
          />
          <div className="muted small">
            {s.token_set ? `A token is stored (…${s.token_hint?.slice(1)}).` : "No token stored."}{" "}
            Leave empty to keep it.
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="gh-owner">Default owner / organisation</label>
            <input
              id="gh-owner"
              type="text"
              value={owner ?? s.owner ?? ""}
              disabled={!admin}
              onChange={(e) => setOwner(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="gh-branch">Base branch</label>
            <input
              id="gh-branch"
              type="text"
              value={baseBranch ?? s.base_branch}
              disabled={!admin}
              onChange={(e) => setBaseBranch(e.target.value)}
            />
          </div>
        </div>
        {save.error && <div className="callout error">{describeError(save.error)}</div>}
        {saved && <div className="callout notice">Saved.</div>}
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
          <div className="callout notice">
            Connected as <strong>{test.data.login}</strong>
            {test.data.name ? ` (${test.data.name})` : ""}
            {test.data.rate_limit_remaining !== null &&
              ` · ${test.data.rate_limit_remaining}/${test.data.rate_limit_limit} API calls left`}
          </div>
        )}
        {test.error && <div className="callout error">{describeError(test.error)}</div>}
      </form>
    </div>
  );
}
