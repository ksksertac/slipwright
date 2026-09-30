import { useState, type FormEvent } from "react";
import { describeError, type ProviderSettings } from "../../api/client";
import {
  useAcceptProviderTerms,
  useChatGPTLogin,
  useChatGPTLogout,
  useProviderTerms,
  useProviders,
  useSaveProvider,
  useStartChatGPTLogin,
  useTestProvider,
} from "../../api/hooks";
import { Copyable } from "../../components/Copyable";
import { ModelPicker } from "../../components/ModelPicker";
import { Markdown } from "../AgentStandardsTab";
import { useAuth } from "../../auth/AuthProvider";
import { ErrorBox, Loading, PageHead } from "../../components/ui";
import { IconCheck, IconChevron } from "../../components/icons";
import { useT } from "../../i18n";

/**
 * API keys for the model providers (Anthropic, OpenAI, OpenRouter, ...). Which provider a role
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
        subtitle={tx("API keys for Anthropic, OpenAI, OpenRouter and the rest.")}
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
  // a plan one signs in with, not a key one pastes (ChatGPT through the Codex CLI)
  const subscription = p.kind === "subscription";
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
  const summary = !p.key_set
    ? subscription
      ? tx("sign in to use it")
      : tx("add a key to use it")
    : modelValue || (p.needs_model ? tx("pick a model") : tx("no default model"));

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
            {tx(p.label)}
            {p.is_default && <span className="tag">{tx("default")}</span>}
          </span>
          <span
            className={`acc-sub${p.key_set && modelValue ? " mono" : ""}${p.needs_model ? " text-bad" : ""}`}
          >
            {summary}
          </span>
        </span>
        <span className="acc-right">
          {p.key_set && subscription ? (
            <span className="badge ok plain">
              <IconCheck />
              {tx("signed in")}
            </span>
          ) : p.key_set ? (
            <span className="badge ok plain">
              <IconCheck />
              {tx("key set")} {p.key_hint}{" "}
              {p.key_from_env ? tx("(from {env})", { env: p.env_var }) : ""}
            </span>
          ) : (
            <span className="badge idle">{subscription ? tx("not signed in") : tx("no key")}</span>
          )}
        </span>
      </summary>
      <form className="acc-body" onSubmit={submit}>
        {subscription && <ChatGPTSignIn signedIn={p.key_set} admin={admin} />}
        {p.has_terms && p.key_set && open && <VendorTerms provider={p} admin={admin} />}
        <div className="grid-2">
          {!subscription && (
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
          )}
          {!subscription && (
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
          )}
          <div className="field">
            <label htmlFor={`${p.name}-model`}>{tx("Default model")}</label>
            <ModelPicker
              id={`${p.name}-model`}
              provider={p.key_set && open ? p.name : null}
              value={modelValue}
              disabled={!admin}
              onChange={setModel}
              placeholder={
                p.key_set
                  ? tx("model id — leave empty to use each role's own")
                  : subscription
                    ? tx("sign in to list the models")
                    : tx("add a key to list the models")
              }
              emptyLabel={tx("— not set: roles use the model in their profile —")}
            />
            <div className="muted small">
              {p.is_default
                ? tx("What every agent without a pinned provider runs on right now.")
                : tx(
                    "Used by every agent without a pinned provider once this provider is the default.",
                  )}
            </div>
          </div>
          {!subscription && (
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
          )}
        </div>
        {p.needs_model && (
          // the key is in and the models are listed from it, but none is chosen: an agent
          // following this provider would be sent a Claude name, so it stops instead
          <div className="callout hint">
            {p.is_default
              ? tx(
                  "Pick a default model above. Until you do, agents cannot run: the profiles name Claude models, which {label} does not know.",
                  { label: p.label },
                )
              : tx("Pick a default model above before making {label} the default.", {
                  label: p.label,
                })}
          </div>
        )}
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
            {p.key_set && !p.key_from_env && !subscription && (
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

/**
 * A vendor that refuses every call until its terms of use are accepted (EVREN). Its own
 * web site has no button for it, only an API call -- so the text is shown here, in the
 * vendor's own words, and the person accepts it with a press. Never automatically: what
 * is being agreed to includes how the prompts Slipwright sends are processed.
 */
function VendorTerms({ provider: p, admin }: { provider: ProviderSettings; admin: boolean }) {
  const tx = useT();
  const terms = useProviderTerms(p.name);
  const accept = useAcceptProviderTerms();
  const [read, setRead] = useState(false);
  if (terms.isLoading) return null;
  // a wrong key or an unreachable host: Test connection says which, and better
  if (terms.error || !terms.data) return null;
  const t = terms.data;
  if (t.accepted) {
    return (
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="badge ok plain">
          <IconCheck />
          {tx("{label}'s terms of use (v{n}) are accepted for this key.", {
            label: p.label,
            n: t.version,
          })}
        </span>
      </div>
    );
  }
  return (
    // one column inside: a callout lays its children side by side
    <div className="callout hint">
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ marginTop: 0 }}>
          <strong>
            {tx("{label} needs its terms of use accepted before it answers.", { label: p.label })}
          </strong>{" "}
          {tx("Until then every call is refused, the model list included. Read them first:")}
        </p>
        <details
          open={read}
          onToggle={(e) => setRead((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>{tx("Terms of use, version {n}", { n: t.version })}</summary>
          <div className="vendor-terms">
            <Markdown text={plainTerms(t.text)} />
          </div>
        </details>
        {admin && (
          <div className="row" style={{ marginTop: 8 }}>
            <button
              type="button"
              className="btn primary small"
              disabled={accept.isPending}
              onClick={() => accept.mutate({ name: p.name, version: t.version })}
            >
              {accept.isPending
                ? tx("Accepting…")
                : tx("I accept {label}'s terms of use", { label: p.label })}
            </button>
          </div>
        )}
        {accept.error && <div className="callout error">{describeError(accept.error)}</div>}
      </div>
    </div>
  );
}

/** EVREN's text is written for GitHub: badges and quote markers are noise in a small box. */
function plainTerms(text: string): string {
  return text
    .replace(/^!\[.*$/gm, "")
    .replace(/^> ?/gm, "")
    .replace(/^---$/gm, "");
}

/**
 * Signing in with a ChatGPT plan: the server runs OpenAI's own `codex login --device-auth`,
 * which prints a link and a one-time code. The person opens the link, types the code,
 * approves -- and the page, asking every few seconds, sees it land.
 */
function ChatGPTSignIn({ signedIn, admin }: { signedIn: boolean; admin: boolean }) {
  const tx = useT();
  const status = useChatGPTLogin(true);
  const start = useStartChatGPTLogin();
  const logout = useChatGPTLogout();
  const waiting = status.data?.status === "waiting" && !signedIn;
  const code = start.data?.status === "waiting" ? start.data : null;

  return (
    <div className="chatgpt-signin">
      <p className="muted small" style={{ marginTop: 0 }}>
        {tx(
          "Runs the agents on your ChatGPT plan instead of API credit, through OpenAI's own Codex CLI on this server. First turn on “Enable device code sign-in for Codex” under ChatGPT → Settings → Security.",
        )}
      </p>
      {signedIn ? (
        <div className="row">
          <span className="badge ok plain">
            <IconCheck /> {tx("Signed in with ChatGPT")}
          </span>
          {admin && (
            <button
              type="button"
              className="btn ghost small"
              disabled={logout.isPending}
              onClick={() => logout.mutate()}
            >
              {tx("Sign out")}
            </button>
          )}
        </div>
      ) : waiting && code ? (
        <div className="chatgpt-code">
          <div className="small">{tx("1. Open this page and sign in to ChatGPT:")}</div>
          <a href={code.url ?? "#"} target="_blank" rel="noreferrer" className="mono small">
            {code.url}
          </a>
          <div className="small">{tx("2. Enter this code there:")}</div>
          <Copyable text={code.code ?? ""}>
            <code className="chatgpt-code-value">{code.code}</code>
          </Copyable>
          <div className="faint small">{tx("Waiting for you to approve it…")}</div>
        </div>
      ) : (
        admin && (
          <button
            type="button"
            className="btn primary small"
            disabled={start.isPending}
            onClick={() => start.mutate()}
          >
            {start.isPending ? tx("Getting a code…") : tx("Sign in with ChatGPT")}
          </button>
        )
      )}
      {start.error && <div className="callout error">{describeError(start.error)}</div>}
      {logout.error && <div className="callout error">{describeError(logout.error)}</div>}
    </div>
  );
}
