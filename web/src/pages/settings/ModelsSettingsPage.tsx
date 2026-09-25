import { useState, type FormEvent } from "react";
import { describeError, type ProviderSettings } from "../../api/client";
import { useProviderModels, useProviders, useSaveProvider, useTestProvider } from "../../api/hooks";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { IconCheck, IconChevron } from "../../components/icons";
import { useT } from "../../i18n";

/**
 * API keys for the model providers (Anthropic, OpenAI, DeepSeek). Which provider a role
 * uses is chosen per project under Agents; the default applies to roles that name none.
 *
 * Every provider is one collapsed row — key, model and default at a glance — that opens
 * on click; nothing is expanded unless a provider still has to be set up.
 */
export function ModelsSettingsPage() {
  const tx = useT();
  const providers = useProviders();
  if (providers.isLoading) return <Loading />;
  if (providers.error) return <ErrorBox error={providers.error} />;
  const list = providers.data!;
  const none = !list.some((p) => p.key_set);
  return (
    <div>
      <PageHead
        title={tx("Models")}
        subtitle={tx("API keys for Anthropic, OpenAI and DeepSeek.")}
      />
      <p className="muted">
        {tx(
          "Enter an API key for each provider you want to use. Keys are stored encrypted and never shown again; a key from the server's environment is used when none is stored. Every agent runs on the provider marked",
        )}{" "}
        <strong>{tx("default")}</strong> {tx("below, on that provider's")}{" "}
        <strong>{tx("default model")}</strong>{" "}
        {tx("— unless a role is pinned to a provider and model of its own under")}{" "}
        <strong>{tx("Agents")}</strong>.
      </p>
      <div className="stack tight">
        {list.map((p, i) => (
          <ProviderCard key={p.name} provider={p} startOpen={none && i === 0} />
        ))}
      </div>
    </div>
  );
}

function ProviderCard({
  provider: p,
  startOpen,
}: {
  provider: ProviderSettings;
  startOpen: boolean;
}) {
  const tx = useT();
  const { user } = useAuth();
  const save = useSaveProvider();
  const test = useTestProvider();
  const [open, setOpen] = useState(startOpen);
  const [key, setKey] = useState("");
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [maxTokens, setMaxTokens] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const admin = !!user?.is_admin;
  const models = useProviderModels(p.key_set && open ? p.name : null);
  const modelValue = model ?? p.default_model ?? "";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSaved(false);
    save.mutate(
      {
        name: p.name,
        api_key: key.trim() || null,
        base_url: baseUrl ?? p.base_url ?? "",
        default_model: modelValue,
        max_tokens: maxTokens === null ? undefined : Number(maxTokens) || 0,
      },
      {
        onSuccess: () => {
          setKey("");
          setSaved(true);
        },
      },
    );
  };

  // The one line to read when the row is shut: what this provider would run on.
  const summary = !p.key_set ? tx("add a key to use it") : modelValue || tx("no default model");

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
            {p.label}
            {p.is_default && <span className="tag">{tx("default")}</span>}
          </span>
          <span className={`acc-sub${p.key_set && modelValue ? " mono" : ""}`}>{summary}</span>
        </span>
        <span className="acc-right">
          {p.key_set ? (
            <span className="badge ok plain">
              <IconCheck />
              {tx("key set")} {p.key_hint}{" "}
              {p.key_from_env ? tx("(from {env})", { env: p.env_var }) : ""}
            </span>
          ) : (
            <span className="badge idle">{tx("no key")}</span>
          )}
        </span>
      </summary>
      <form className="acc-body" onSubmit={submit}>
        <div className="grid-2">
          <div className="field">
            <label htmlFor={`${p.name}-key`}>{tx("API key")}</label>
            <input
              id={`${p.name}-key`}
              type="password"
              autoComplete="off"
              value={key}
              disabled={!admin}
              onChange={(e) => setKey(e.target.value)}
              placeholder={
                p.key_set
                  ? tx("set, ends with {hint}", { hint: p.key_hint ?? "" })
                  : tx("paste a key")
              }
            />
            <div className="muted small">
              {tx("Get one at")}{" "}
              <a href={p.docs_url} target="_blank" rel="noreferrer">
                {p.docs_url.replace(/^https?:\/\//, "")}
              </a>
              ; {tx("or set")} <code>{p.env_var}</code> {tx("on the server.")}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${p.name}-url`}>{tx("Base URL (optional)")}</label>
            <input
              id={`${p.name}-url`}
              type="url"
              className="mono"
              value={baseUrl ?? p.base_url ?? ""}
              disabled={!admin}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={p.default_base_url}
            />
            <div className="muted small">
              {tx("Leave empty for {url}; set for proxies.", { url: p.default_base_url })}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${p.name}-model`}>{tx("Default model")}</label>
            {models.data && models.data.models.length > 0 ? (
              <select
                id={`${p.name}-model`}
                value={modelValue}
                disabled={!admin}
                onChange={(e) => setModel(e.target.value)}
              >
                <option value="">{tx("— not set: roles use the model in their profile —")}</option>
                {!models.data.models.includes(modelValue) && modelValue && (
                  <option value={modelValue}>{modelValue}</option>
                )}
                {models.data.models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={`${p.name}-model`}
                type="text"
                className="mono"
                value={modelValue}
                disabled={!admin}
                onChange={(e) => setModel(e.target.value)}
                placeholder={p.key_set ? tx("model id") : tx("add a key to list the models")}
              />
            )}
            <div className="muted small">
              {p.is_default
                ? tx("What every agent without a pinned provider runs on right now.")
                : tx(
                    "Used by every agent without a pinned provider once this provider is the default.",
                  )}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${p.name}-max`}>{tx("Max output tokens per call")}</label>
            <input
              id={`${p.name}-max`}
              type="number"
              min={0}
              step={1024}
              value={maxTokens ?? p.max_tokens ?? ""}
              disabled={!admin}
              onChange={(e) => setMaxTokens(e.target.value)}
              placeholder={tx("{n} (vendor default)", { n: p.default_max_tokens })}
            />
            <div className="muted small">
              {tx(
                "How long one answer may be. Raise it if the vendor's newer models allow more; an agent that still hits the limit is asked for smaller parts automatically.",
              )}
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
              disabled={!p.key_set || test.isPending}
              onClick={() => test.mutate(p.name)}
            >
              {test.isPending ? tx("Testing…") : tx("Test connection")}
            </button>
            {!p.is_default && (
              <button
                type="button"
                className="btn small"
                onClick={() => save.mutate({ name: p.name, make_default: true })}
              >
                {tx("Use as default")}
              </button>
            )}
            {p.key_set && !p.key_from_env && (
              <button
                type="button"
                className="btn bad small"
                onClick={() => save.mutate({ name: p.name, clear_key: true })}
              >
                {tx("Remove key")}
              </button>
            )}
          </div>
        )}
        {test.data && test.data.name === p.name && (
          <div className="callout notice">
            {tx("Connected. {n} model(s) available:", { n: test.data.models.length })}{" "}
            <span className="mono">{test.data.models.slice(0, 12).join(", ")}</span>
            {test.data.models.length > 12 && " …"}
          </div>
        )}
        {test.error && test.variables === p.name && (
          <div className="callout error">{describeError(test.error)}</div>
        )}
      </form>
    </details>
  );
}
