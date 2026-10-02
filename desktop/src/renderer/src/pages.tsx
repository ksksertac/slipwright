// The screens. Each takes the app state the main process pushed and calls back through
// `window.agent`; none of them holds anything of its own that matters past a re-render.

import { useEffect, useState } from "react";
import type { AgentId, AppState, HistoryEntry, ModelChoice, ProviderId, Result } from "@shared/types";
import { AGENTS } from "@shared/types";
import { t } from "./i18n";
import logo from "./logo.png";
import { AGENT_NAME, AgentCard, DOMAINS, Icon, Switch } from "./parts";

export type Go = (page: string) => void;

function Head({ title, text, children }: { title: string; text?: string; children?: React.ReactNode }) {
  return (
    <div className="head">
      <div>
        <h2>{title}</h2>
        {text && <p>{text}</p>}
      </div>
      {children}
    </div>
  );
}

function Outcome({ result }: { result: Result | null }) {
  if (!result || (!result.message && result.ok)) return null;
  return (
    <div className={`ok-line${result.ok ? "" : " bad"}`}>
      {result.ok ? Icon.check : Icon.cross} {result.message}
    </div>
  );
}

// -- Now ------------------------------------------------------------------------------

export function Welcome({ go }: { go: Go }) {
  return (
    <div className="card welcome">
      <img src={logo} alt="" />
      <h3>{t("This machine is not lent to a Slipwright team yet")}</h3>
      <p>{t("Once it is, its agents write phases with your own Claude Code, Codex or API key, and it builds iOS and Android when it can.")}</p>
      <ol>
        <li>{t("In Slipwright, open Settings → Machines → Connect a machine")}</li>
        <li>{t("Copy the code (SW-…); it works for 15 minutes, once")}</li>
        <li>{t("Paste it on the Slipwright team page")}</li>
      </ol>
      <button className="btn primary" onClick={() => go("team")}>
        {t("Connect to a team")}
      </button>
    </div>
  );
}

export function Now({ state, go, now }: { state: AppState; go: Go; now: number }) {
  const running = state.tasks.length;
  return (
    <>
      <Head title={t("Now")} text={t("The agents on this machine and the work they hold. The development's page on Slipwright shows the same.")}>
        {running > 0 && <span className="pill p-run inline">{running === 1 ? t("1 task running") : t("{n} tasks running", { n: running })}</span>}
      </Head>
      {!state.pairing && <Welcome go={go} />}
      <div className="grid2">
        {AGENTS.map((agent) => (
          <AgentCard key={agent} state={state} agent={agent} full={false} now={now} onOpen={() => go(`agent-${agent}`)} />
        ))}
      </div>
    </>
  );
}

// -- an agent -------------------------------------------------------------------------

const PROVIDERS: { id: ProviderId; name: string }[] = [
  { id: "claude-code", name: "Claude Code" },
  { id: "codex", name: "Codex" },
  { id: "anthropic", name: "Anthropic API" },
  { id: "openai", name: "OpenAI API" },
];

export function ModelPick({ agent, state }: { agent: AgentId; state: AppState }) {
  const choice = state.settings.agents[agent].model;
  const [model, setModel] = useState(choice?.model ?? "");
  useEffect(() => setModel(choice?.model ?? ""), [choice?.model, choice?.provider]);
  const save = (next: ModelChoice | null) => void window.agent.saveAgent(agent, { model: next });
  return (
    <div className="model-pick">
      <select
        className="select"
        aria-label={t("Model")}
        value={choice?.provider ?? ""}
        onChange={(e) => save(e.target.value ? { provider: e.target.value as ProviderId, model: "" } : null)}
      >
        <option value="">—</option>
        {PROVIDERS.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      {choice && (
        <div className="input">
          <input
            value={model}
            placeholder={t("Model name (empty: default)")}
            onChange={(e) => setModel(e.target.value)}
            onBlur={() => model.trim() !== choice.model && save({ ...choice, model: model.trim() })}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        </div>
      )}
    </div>
  );
}

export function AgentPage({ state, agent, now }: { state: AppState; agent: AgentId; now: number }) {
  const own = state.settings.agents[agent];
  const name = AGENT_NAME[agent];
  return (
    <>
      <Head title={t("{agent} agent", { agent: name })} text={t("Takes {agent} phases on this machine. Its model and whether it is on are set here.", { agent: name })}>
        <div className="row-btns">
          <span style={{ fontSize: 13, color: "var(--text-2)" }}>{t("On this machine")}</span>
          <Switch on={own.enabled} label={t("On this machine")} onChange={(on) => void window.agent.saveAgent(agent, { enabled: on })} />
        </div>
      </Head>
      <AgentCard state={state} agent={agent} full now={now} />
      <div className="card form">
        <div className="field">
          <label>{t("Model")}</label>
          <ModelPick agent={agent} state={state} />
        </div>
        <div className="meta">
          <span>
            {t("Writes the domains")} <b>{DOMAINS[agent].join(", ")}</b>
          </span>
        </div>
      </div>
    </>
  );
}

// -- History --------------------------------------------------------------------------

const OUTCOME_PILL: Record<HistoryEntry["outcome"], string> = {
  answered: "p-idle",
  built: "p-idle",
  "build-failed": "p-bad",
  "taken-back": "p-off",
  failed: "p-bad",
  timeout: "p-warn",
  rejected: "p-warn",
};

export function HistoryPage({ state }: { state: AppState }) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  // read again whenever the set of running tasks changes: one finishing is a new line
  const key = state.tasks.map((x) => x.id).join();
  useEffect(() => {
    void window.agent.history().then(setEntries);
  }, [key]);
  return (
    <>
      <Head title={t("History")} text={t("The phases and builds this machine handled.")} />
      <div className="card">
        {entries.length === 0 ? (
          <div className="form empty">{t("Nothing handled yet")}</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("Phase")}</th>
                <th>{t("Project")}</th>
                <th>{t("Agent")}</th>
                <th>{t("Duration")}</th>
                <th>{t("Outcome")}</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={`${e.id}-${e.at}`}>
                  <td>
                    {e.goal}
                    <div className="mono">
                      {[e.phase ? t("Phase {n}/{m}", { n: e.phase, m: e.phases ?? "?" }) : null, e.jiraKey, new Date(e.at).toLocaleString("tr-TR")].filter(Boolean).join(" · ")}
                    </div>
                  </td>
                  <td>{e.project || "—"}</td>
                  <td>{AGENT_NAME[e.agent]}</td>
                  <td>{e.seconds < 60 ? `${e.seconds} sn` : t("{min} min", { min: Math.round(e.seconds / 60) })}</td>
                  <td>
                    <span className={`pill inline ${OUTCOME_PILL[e.outcome]}`} title={e.detail ?? undefined}>
                      {t(e.outcome)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

// -- Team -----------------------------------------------------------------------------

export function TeamPage({ state }: { state: AppState }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const p = state.pairing;
  const connect = async () => {
    setBusy(true);
    setResult(null);
    const r = await window.agent.pair(code);
    setBusy(false);
    setResult(r.ok ? null : r);
    if (r.ok) setCode("");
  };
  return (
    <>
      <Head title={t("Slipwright team")} text={t("Which Slipwright this machine is connected to, and as what.")} />
      <div className="card form">
        {p ? (
          <>
            <div className={`ok-line${state.connection === "offline" ? " bad" : ""}`}>
              {state.connection === "offline" ? Icon.cross : Icon.check}{" "}
              {t("Connected: {where}", { where: p.relay ? p.relay.host : (p.address ?? "").replace(/^https?:\/\//, "") })}
            </div>
            <div className="meta">
              <span>
                {p.relay ? t("Relay") : t("LAN")} <b>{p.relay ? p.relay.host : p.address}</b>
              </span>
              <span>
                {t("Connection")} <b>{p.relay ? t("end-to-end encrypted") : t("on this network")}</b>
              </span>
              <span>
                {t("Machine name")} <b>{state.machineName}</b>
              </span>
              <span>
                {t("Machine key")} <b>{t("in the system keychain")}</b>
              </span>
            </div>
            {state.connectionError && state.connection === "offline" && (
              <div className="meta">
                <span>
                  {t("Last error")} <b>{state.connectionError}</b>
                </span>
              </div>
            )}
          </>
        ) : (
          state.connectionError && <Outcome result={{ ok: false, message: state.connectionError }} />
        )}
        <div className="sec">
          <h3>{p ? t("Connect to another team") : t("Connect to a team")}</h3>
          <p>{t("Paste the code from Slipwright's Settings → Machines → Connect a machine. A code works for 15 minutes, once.")}</p>
        </div>
        <div className="field">
          <label htmlFor="code">{t("Connection code")}</label>
          <div className="input">
            <input id="code" value={code} placeholder="SW-XXXX-XXXX-XXXX-XXXX" spellCheck={false} onChange={(e) => setCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && code.trim() && void connect()} />
          </div>
        </div>
        <Outcome result={result} />
        <div className="row-btns">
          <button className="btn primary" disabled={busy || !code.trim()} onClick={() => void connect()}>
            {busy ? t("Connecting…") : t("Connect")}
          </button>
          {p && (
            <button className="btn danger" title={t("This machine forgets the pairing. Remove it on Slipwright's Machines page too.")} onClick={() => void window.agent.forget()}>
              {t("Leave this team")}
            </button>
          )}
        </div>
      </div>
    </>
  );
}

// -- Models ---------------------------------------------------------------------------

function KeyRow({ mark, name, secret, which }: { mark: string; name: string; secret: string | null; which: "anthropic" | "openai" }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const save = async (v: string | null) => {
    await window.agent.saveSecret(which, v);
    setEditing(false);
    setValue("");
  };
  return (
    <div className="prov">
      <div className="logo-sq">{mark}</div>
      <div>
        <b>{name}</b>
        <small>{secret ?? t("No key")}</small>
      </div>
      <div className="row-btns">
        {secret && !editing && (
          <button className="btn" onClick={() => void save(null)}>
            {t("Remove")}
          </button>
        )}
        <button className="btn" onClick={() => setEditing(!editing)}>
          {editing ? t("Cancel") : secret ? t("Change") : t("Add key")}
        </button>
      </div>
      {editing && (
        <div className="edit">
          <div className="input">
            <input type="password" autoFocus value={value} placeholder={which === "anthropic" ? "sk-ant-…" : "sk-…"} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === "Enter" && value.trim() && void save(value)} />
          </div>
          <button className="btn primary" disabled={!value.trim()} onClick={() => void save(value)}>
            {t("Save")}
          </button>
        </div>
      )}
    </div>
  );
}

function CliRow({ mark, name, kind, info, install }: { mark: string; name: string; kind: string; info: AppState["detected"]["claude"]; install: string }) {
  const found = name === "Claude Code" ? t("claude CLI found") : t("codex CLI found");
  const parts = info.installed ? [kind, found, info.version, info.signedIn ? t("signed in") : t("sign-in not known")] : [kind, t("not installed")];
  const line = parts.filter(Boolean).join(" · ");
  return (
    <div className="prov">
      <div className="logo-sq">{mark}</div>
      <div>
        <b>{name}</b>
        <small>{line}</small>
        {!info.installed && (
          <div className="mono">
            {t("Install with")}: {install}
          </div>
        )}
      </div>
      <span className={`pill inline ${info.installed ? (info.signedIn ? "p-idle" : "p-warn") : "p-off"}`}>{info.installed ? t("ready") : t("not found")}</span>
    </div>
  );
}

function platformWhy(detail: string | null, platform: "ios" | "android"): string {
  if (platform === "ios") {
    if (detail === "no-xcode") return t("Xcode not found");
    if (detail === "xcode-unopened") return t("Xcode is installed but was never opened");
    return t("iOS builds need a Mac");
  }
  return detail === "no-jdk" ? t("Android SDK found but no JDK") : t("Android SDK not found");
}

export function ModelsPage({ state }: { state: AppState }) {
  const d = state.detected;
  const [looking, setLooking] = useState(false);
  return (
    <>
      <Head title={t("Models")} text={t("The agents write with this machine's own subscription or key. Keys never leave this machine.")}>
        <button
          className="btn"
          disabled={looking}
          onClick={async () => {
            setLooking(true);
            await window.agent.detect();
            setLooking(false);
          }}
        >
          {t("Look again")}
        </button>
      </Head>
      <div className="card">
        <CliRow mark="CC" name="Claude Code" kind={t("Subscription")} info={d.claude} install="npm install -g @anthropic-ai/claude-code" />
        <CliRow mark="CX" name="Codex" kind={t("ChatGPT plan")} info={d.codex} install="npm install -g @openai/codex" />
        <KeyRow mark="A" name={t("Anthropic API")} secret={state.secrets.anthropic} which="anthropic" />
        <KeyRow mark="O" name={t("OpenAI API")} secret={state.secrets.openai} which="openai" />
      </div>
      <div className="card form">
        <div className="sec">
          <h3>{t("Which agent uses which model")}</h3>
        </div>
        <table>
          <tbody>
            {AGENTS.map((agent) => (
              <tr key={agent}>
                <td style={{ width: 120 }}>{AGENT_NAME[agent]}</td>
                <td>{state.settings.agents[agent].enabled ? <ModelPick agent={agent} state={state} /> : <span className="mono">{t("off on this machine")}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card form">
        <div className="sec">
          <h3>{t("Platforms this machine builds")}</h3>
        </div>
        <div className="meta">
          <span>
            iOS <b>{d.ios.ok ? d.ios.detail : platformWhy(d.ios.detail, "ios")}</b>
          </span>
          <span>
            Android <b>{d.android.ok ? d.android.detail : platformWhy(d.android.detail, "android")}</b>
          </span>
        </div>
      </div>
    </>
  );
}

// -- Source ---------------------------------------------------------------------------

export function SourcePage({ state }: { state: AppState }) {
  const [github, setGithub] = useState("");
  const [bbUser, setBbUser] = useState(state.settings.bitbucket.user ?? "");
  const [bbPass, setBbPass] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(state.settings.github.user ? { ok: true, message: `GitHub: ${state.settings.github.user}` } : null);
  const save = async () => {
    setBusy(true);
    const r = await window.agent.saveSource(github.trim() || null, bbUser.trim(), bbPass.trim() || null);
    setBusy(false);
    setResult(r);
    setGithub("");
    setBbPass("");
  };
  return (
    <>
      <Head title={t("Source")} text={t("The agents read the project's code from here. Read access is enough: only Slipwright writes to the branch.")} />
      <div className="card form">
        <div className="field">
          <label htmlFor="gh">{t("GitHub token")}</label>
          <div className="input">
            <input id="gh" type="password" value={github} placeholder={state.secrets.github ?? "github_pat_…"} onChange={(e) => setGithub(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="bbu">{t("Bitbucket (optional)")}</label>
          <div className="row-btns">
            <div className="input" style={{ flex: 1 }}>
              <input id="bbu" value={bbUser} placeholder={t("Bitbucket username")} onChange={(e) => setBbUser(e.target.value)} />
            </div>
            <div className="input" style={{ flex: 1 }}>
              <input type="password" aria-label={t("App password")} value={bbPass} placeholder={state.secrets.bitbucket ?? t("App password")} onChange={(e) => setBbPass(e.target.value)} />
            </div>
          </div>
        </div>
        <Outcome result={result} />
        <div className="meta">
          <span>{t("Without a token the agents answer from the prompt alone.")}</span>
          {(state.secrets.github || state.secrets.bitbucket) && <span>{t("Leave empty to keep the saved one")}</span>}
        </div>
        <div className="row-btns">
          <button className="btn primary" disabled={busy} onClick={() => void save()}>
            {busy ? t("Testing…") : t("Save and test")}
          </button>
          {state.secrets.github && (
            <button
              className="btn"
              onClick={async () => {
                setResult(await window.agent.saveSource("", null, null));
              }}
            >
              {t("Remove")} GitHub
            </button>
          )}
        </div>
      </div>
    </>
  );
}

// -- Jira -----------------------------------------------------------------------------

export function JiraPage({ state }: { state: AppState }) {
  const [site, setSite] = useState(state.settings.jira.site);
  const [email, setEmail] = useState(state.settings.jira.email);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  return (
    <>
      <Head title="Jira" text={t('When a phase is taken, its issue moves to "In Progress" under your name. Optional.')} />
      <div className="card form">
        <div className="field">
          <label htmlFor="js">{t("Site")}</label>
          <div className="input">
            <input id="js" value={site} placeholder="acme.atlassian.net" onChange={(e) => setSite(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="je">{t("E-mail")}</label>
          <div className="input">
            <input id="je" value={email} placeholder="ayse@acme.com" onChange={(e) => setEmail(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="jt">{t("API token")}</label>
          <div className="input">
            <input id="jt" type="password" value={token} placeholder={state.secrets.jira ?? "ATATT…"} onChange={(e) => setToken(e.target.value)} />
          </div>
        </div>
        <Outcome result={result && result.ok && result.message ? { ok: true, message: t("Connected as {name}", { name: result.message }) } : result} />
        <div className="row-btns">
          <button
            className="btn primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setResult(await window.agent.saveJira(site, email, token.trim() || null));
              setBusy(false);
              setToken("");
            }}
          >
            {busy ? t("Testing…") : t("Save and test")}
          </button>
        </div>
      </div>
    </>
  );
}

// -- Settings -------------------------------------------------------------------------

export function SettingsPage({ state }: { state: AppState }) {
  const s = state.settings;
  const [max, setMax] = useState(String(s.maxConcurrent));
  const toggles: [keyof typeof s, string, string][] = [
    ["runBuilds", t("Run build and test commands on this machine"), t("The commands the agents wrote run in a folder of their own, with a restricted environment.")],
    ["startAtLogin", t("Start when the computer starts"), t("Runs in the background with a tray icon.")],
    ["notOnBattery", t("Do not take work on battery"), t("A laptop that is not plugged in takes no new phase.")],
    ["notifyDone", t("Notify when a task is done"), ""],
  ];
  return (
    <>
      <Head title={t("Settings")} text={t("How this machine works.")} />
      <div className="card form">
        {toggles.map(([key, title, text]) => (
          <div className="toggle-row" key={key}>
            <div className="sec">
              <h3>{title}</h3>
              {text && <p>{text}</p>}
            </div>
            <Switch on={!!s[key]} label={title} onChange={(on) => void window.agent.saveSettings({ [key]: on })} />
          </div>
        ))}
        <div className="field">
          <label htmlFor="par">{t("At most this many tasks at once")}</label>
          <div className="input" style={{ maxWidth: 120 }}>
            <input id="par" inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value.replace(/\D/g, ""))} onBlur={() => void window.agent.saveSettings({ maxConcurrent: Number(max) || 1 })} />
          </div>
        </div>
        <div className="field">
          <label>{t("Work folder")}</label>
          <div className="row-btns">
            <div className="input" style={{ flex: 1 }}>
              <input readOnly value={s.workDir} />
            </div>
            <button className="btn" onClick={() => void window.agent.chooseWorkDir()}>
              {t("Change")}
            </button>
          </div>
        </div>
        <div className="field">
          <label htmlFor="theme">{t("Theme")}</label>
          <select id="theme" className="select" style={{ maxWidth: 160 }} value={s.theme} onChange={(e) => void window.agent.saveSettings({ theme: e.target.value as typeof s.theme })}>
            <option value="system">{t("System")}</option>
            <option value="light">{t("Light")}</option>
            <option value="dark">{t("Dark")}</option>
          </select>
        </div>
      </div>
    </>
  );
}

