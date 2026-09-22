import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLiveEvents } from "../api/events";
import { useToast } from "./Toast";
import { useAuth } from "../auth/AuthProvider";
import {
  IconBot,
  IconCpu,
  IconFolder,
  IconGit,
  IconHome,
  IconLogout,
  IconMonitor,
  IconMoon,
  IconSun,
  IconTicket,
  IconUsers,
} from "./icons";
import { useTheme, type Theme } from "./theme";
import { useLang, useT } from "../i18n";
import { BuildWatch } from "./BuildWatch";

const THEMES: { value: Theme; icon: React.ReactNode; title: string }[] = [
  { value: "light", icon: <IconSun />, title: "Light" },
  { value: "dark", icon: <IconMoon />, title: "Dark" },
  { value: "system", icon: <IconMonitor />, title: "System" },
];

export function Layout() {
  const tx = useT();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  const { lang, setLang } = useLang();
  const toast = useToast();
  useLiveEvents(undefined, toast.ok);
  const overview = useQuery({
    queryKey: ["overview", "badge"],
    queryFn: () => api.get<{ pending_approvals: number }>("/api/overview?recent=0"),
    refetchInterval: 30_000,
  });
  const pending = overview.data?.pending_approvals ?? 0;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">⛵</span> {tx("Slipwright")}
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            <IconHome /> {tx("Dashboard")}
            {pending > 0 && <span className="count">{pending}</span>}
          </NavLink>
          <NavLink to="/projects">
            <IconFolder /> {tx("Projects")}
          </NavLink>
          <NavLink to="/agents">
            <IconBot /> {tx("Agents")}
          </NavLink>
          <div className="nav-label">{tx("Settings")}</div>
          <NavLink to="/settings/models">
            <IconCpu /> {tx("Models")}
          </NavLink>
          <NavLink to="/settings/github">
            <IconGit /> {tx("GitHub")}
          </NavLink>
          <NavLink to="/settings/jira">
            <IconTicket /> {tx("Jira")}
          </NavLink>
          {user?.is_admin && (
            <NavLink to="/settings/users">
              <IconUsers /> {tx("Users")}
            </NavLink>
          )}
        </nav>
        <BuildWatch />
        <div className="sidebar-foot">
          <div className="avatar">{user?.username.slice(0, 2)}</div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="truncate" style={{ fontWeight: 500 }}>
              {user?.username}
            </div>
            <div className="faint tiny">{user?.is_admin ? tx("admin") : tx("member")}</div>
          </div>
          <button
            className="btn ghost icon"
            title={tx("Log out")}
            onClick={() => {
              void logout().then(() => navigate("/login"));
            }}
          >
            <IconLogout />
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div id="crumbs" className="crumbs" />
          <div className="segmented" role="group" aria-label={tx("Language")}>
            {(["tr", "en"] as const).map((l) => (
              <button
                key={l}
                className={lang === l ? "on" : ""}
                title={l === "tr" ? "Türkçe" : "English"}
                onClick={() => setLang(l)}
              >
                {l.toUpperCase()}
              </button>
            ))}
          </div>
          <div className="segmented" role="group" aria-label={tx("Theme")}>
            {THEMES.map((t) => (
              <button
                key={t.value}
                className={theme === t.value ? "on" : ""}
                title={tx(t.title)}
                onClick={() => setTheme(t.value)}
              >
                {t.icon}
              </button>
            ))}
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
