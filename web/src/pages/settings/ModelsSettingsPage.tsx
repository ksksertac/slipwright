import { useState, type FormEvent } from "react";
import { describeError, type ProviderSettings } from "../../api/client";
import { useProviders, useSaveProvider, useTestProvider } from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { Crumbs } from "../../components/Crumbs";

/**
 * API keys for the model providers (Anthropic, OpenAI, DeepSeek). Which provider a role
 * uses is chosen per project under Agents; the default applies to roles that name none.
 */
export function ModelsSettingsPage() {
  const providers = useProviders();
  if (providers.isLoading) return <Loading />;
  if (providers.error) return <ErrorBox error={providers.error} />;
  return (
    <div>
      <Crumbs items={[{ label: "Settings" }, { label: "Models" }]} />
      <PageHead title="Models" subtitle="API keys for Anthropic, OpenAI and DeepSeek." />
      <p className="muted">
        Enter an API key for each provider you want to use. Keys are stored encrypted and never
        shown again; a key from the server's environment is used when none is stored. Pick which
        provider and model each role runs on under <strong>Agents</strong> — roles without a
        provider use the default marked below.
      </p>
      <div className="stack">
        {providers.data!.map((p) => (
          <ProviderCard key={p.name} provider={p} />
        ))}
      </div>
    </div>
  );
}

function ProviderCard({ provider: p }: { provider: ProviderSettings }) {
  const { user } = useAuth();
  const save = useSaveProvider();
  const test = useTestProvider();
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const admin = !!user?.is_admin;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      { name: p.name, api_key: key.trim() || null, base_url: baseUrl ?? p.base_url ?? "" },
      {
        onSuccess: () => {
          setKey("");
          setSaved(true);
        },
      },
    );
  };

  return (
    <form className="card" onSubmit={submit}>
      <div className="row spread">
        <h3 style={{ marginBottom: 0 }}>
          {p.label}
          {p.is_default && <span className="tag">default</span>}
        </h3>
        <span className="small">
          {p.key_set ? (
            <span className="badge ok">
              key set {p.key_hint} {p.key_from_env ? `(from ${p.env_var})` : ""}
            </span>
          ) : (
            <span className="badge idle">no key</span>
          )}
        </span>
      </div>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <div className="field">
          <label htmlFor={`${p.name}-key`}>API key</label>
          <input
            id={`${p.name}-key`}
            type="password"
            autoComplete="off"
            value={key}
            disabled={!admin}
            onChange={(e) => setKey(e.target.value)}
            placeholder={p.key_set ? `set, ends with ${p.key_hint}` : "paste a key"}
          />
          <div className="muted small">
            Get one at{" "}
            <a href={p.docs_url} target="_blank" rel="noreferrer">
              {p.docs_url.replace(/^https?:\/\//, "")}
            </a>
            ; or set <code>{p.env_var}</code> on the server.
          </div>
        </div>
        <div className="field">
          <label htmlFor={`${p.name}-url`}>Base URL (optional)</label>
          <input
            id={`${p.name}-url`}
            type="url"
            className="mono"
            value={baseUrl ?? p.base_url ?? ""}
            disabled={!admin}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={p.default_base_url}
          />
          <div className="muted small">Leave empty for {p.default_base_url}; set for proxies.</div>
        </div>
      </div>
      {save.error && <div className="callout error">{describeError(save.error)}</div>}
      {saved && <div className="callout notice">Saved.</div>}
      {admin && (
        <div className="row">
          <button className="btn primary small" disabled={save.isPending}>
            Save
          </button>
          <button
            type="button"
            className="btn small"
            disabled={!p.key_set || test.isPending}
            onClick={() => test.mutate(p.name)}
          >
            {test.isPending ? "Testing…" : "Test connection"}
          </button>
          {!p.is_default && (
            <button
              type="button"
              className="btn small"
              onClick={() => save.mutate({ name: p.name, make_default: true })}
            >
              Use as default
            </button>
          )}
          {p.key_set && !p.key_from_env && (
            <button
              type="button"
              className="btn bad small"
              onClick={() => save.mutate({ name: p.name, clear_key: true })}
            >
              Remove key
            </button>
          )}
        </div>
      )}
      {test.data && test.data.name === p.name && (
        <div className="callout notice">
          Connected. {test.data.models.length} model(s) available:{" "}
          <span className="mono">{test.data.models.slice(0, 12).join(", ")}</span>
          {test.data.models.length > 12 && " …"}
        </div>
      )}
      {test.error && test.variables === p.name && (
        <div className="callout error">{describeError(test.error)}</div>
      )}
    </form>
  );
}
