// The window: the machine's agents down the left, as the approved design has them, and the
// page for whichever is chosen. The page lives in the URL's hash so a screenshot run can
// open any screen (`--page models`).

import { useEffect, useState } from "react";
import type { AgentId, AppState } from "@shared/types";
import { AGENTS } from "@shared/types";
import { t } from "./i18n";
import logo from "./logo.png";
import { AgentPage, HistoryPage, JiraPage, ModelsPage, Now, SettingsPage, SourcePage, TeamPage } from "./pages";
import { AGENT_NAME, agentStatus, Icon, platformsLine } from "./parts";

// upper-cased in the language's own rules, not CSS's: "İş" must become "İŞ", which
// text-transform got wrong in Chromium for a dotted capital I
const label = (key: string) => t(key).toLocaleUpperCase("tr-TR");

function usePage(): [string, (page: string) => void] {
  const read = () => window.location.hash.replace(/^#/, "") || "now";
  const [page, setPage] = useState(read);
  useEffect(() => {
    const on = () => setPage(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return [page, (next) => (window.location.hash = next)];
}

function useNow(ms: number): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}

function Item({ page, current, go, icon, children }: { page: string; current: string; go: (p: string) => void; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <button className={`item${current === page ? " on" : ""}`} onClick={() => go(page)} aria-current={current === page ? "page" : undefined}>
      {icon}
      {children}
    </button>
  );
}

function ConnectionCard({ state, go }: { state: AppState; go: (p: string) => void }) {
  const p = state.pairing;
  let tone = "off";
  let label = t("Not connected");
  if (p) {
    if (state.settings.paused) [tone, label] = ["warn", t("Paused")];
    else if (state.holding === "battery") [tone, label] = ["warn", t("On battery")];
    else if (state.connection === "connected") [tone, label] = ["", t("Connected")];
    else if (state.connection === "offline") [tone, label] = ["bad", t("No connection")];
    else [tone, label] = ["warn", t("Connecting")];
  }
  const where = p ? (p.relay ? p.relay.host : (p.address ?? "").replace(/^https?:\/\//, "")) : null;
  return (
    <button className="machine" onClick={() => go("team")}>
      <div className="row">
        <span className={`live ${tone}`}>{label}</span>
        {p && <span className="badge">{p.relay ? t("Relay") : t("LAN")}</span>}
      </div>
      <small>{[state.machineName, where].filter(Boolean).join(" · ")}</small>
    </button>
  );
}

export function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [page, go] = usePage();
  const now = useNow(5000);

  useEffect(() => {
    void window.agent.state().then(setState);
    return window.agent.onState(setState);
  }, []);

  useEffect(() => {
    if (!state) return;
    // a pinned theme wins both ways; "system" leaves it to prefers-color-scheme
    const theme = state.settings.theme;
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [state?.settings.theme, state]);

  if (!state) return null;
  const paused = state.settings.paused;
  const agentPage = page.startsWith("agent-") ? (page.slice(6) as AgentId) : null;

  let body: React.ReactNode;
  if (agentPage && AGENTS.includes(agentPage)) body = <AgentPage state={state} agent={agentPage} now={now} />;
  else if (page === "history") body = <HistoryPage state={state} />;
  else if (page === "team") body = <TeamPage state={state} />;
  else if (page === "models") body = <ModelsPage state={state} />;
  else if (page === "source") body = <SourcePage state={state} />;
  else if (page === "jira") body = <JiraPage state={state} />;
  else if (page === "settings") body = <SettingsPage state={state} />;
  else body = <Now state={state} go={go} now={now} />;

  return (
    <div className="app">
      <aside>
        <div className="brand">
          <img src={logo} alt="" />
          <div>
            <b>Slipwright Agent</b>
            <span>v{state.version}</span>
          </div>
        </div>
        <ConnectionCard state={state} go={go} />
        <nav>
          <Item page="now" current={page} go={go} icon={Icon.now}>
            <span className="grow">{t("Now")}</span>
            {state.tasks.length > 0 && <span className="badge">{state.tasks.length}</span>}
          </Item>

          <div className="lbl">{label("Agents")}</div>
          {AGENTS.map((agent) => {
            const { status, task } = agentStatus(state, agent);
            const platforms = agent === "mobile" ? platformsLine(state) : null;
            return (
              <Item key={agent} page={`agent-${agent}`} current={page} go={go} icon={<span className={`st ${status}`} />}>
                <span className="grow">{platforms ? `${AGENT_NAME[agent]} · ${platforms}` : AGENT_NAME[agent]}</span>
                {task && <span className="badge">{task.phase ? t("Phase {n}", { n: task.phase }) : t("Build")}</span>}
              </Item>
            );
          })}

          <div className="lbl">{label("Work")}</div>
          <Item page="history" current={page} go={go} icon={Icon.history}>
            <span className="grow">{t("History")}</span>
          </Item>

          <div className="lbl">{label("Connections")}</div>
          <Item page="team" current={page} go={go} icon={Icon.team}>
            <span className="grow">{t("Slipwright team")}</span>
          </Item>
          <Item page="models" current={page} go={go} icon={Icon.models}>
            <span className="grow">{t("Models")}</span>
          </Item>
          <Item page="source" current={page} go={go} icon={Icon.source}>
            <span className="grow">{t("Source")}</span>
          </Item>
          <Item page="jira" current={page} go={go} icon={Icon.jira}>
            <span className="grow">Jira</span>
          </Item>

          <div className="lbl">{label("App")}</div>
          <Item page="settings" current={page} go={go} icon={Icon.settings}>
            <span className="grow">{t("Settings")}</span>
          </Item>
        </nav>
        <div className="foot">
          <button className={`btn grow${paused ? " primary" : ""}`} onClick={() => void window.agent.saveSettings({ paused: !paused })}>
            {paused ? Icon.play : Icon.pause}
            {paused ? t("Resume taking work") : t("Pause taking work")}
          </button>
        </div>
      </aside>
      <main>{body}</main>
    </div>
  );
}
