import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLiveEvents } from "../api/events";
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

const THEMES: { value: Theme; icon: React.ReactNode; title: string }[] = [
  { value: "light", icon: <IconSun />, title: "Light" },
  { value: "dark", icon: <IconMoon />, title: "Dark" },
  { value: "system", icon: <IconMonitor />, title: "System" },
];

export function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  useLiveEvents();
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
          <span className="brand-mark">⛵</span> Slipwright
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            <IconHome /> Dashboard
            {pending > 0 && <span className="count">{pending}</span>}
          </NavLink>
          <NavLink to="/projects">
            <IconFolder /> Projects
          </NavLink>
          <NavLink to="/agents">
            <IconBot /> Agents
          </NavLink>
          <div className="nav-label">Settings</div>
          <NavLink to="/settings/models">
            <IconCpu /> Models
          </NavLink>
          <NavLink to="/settings/github">
            <IconGit /> GitHub
          </NavLink>
          <NavLink to="/settings/jira">
            <IconTicket /> Jira
          </NavLink>
          {user?.is_admin && (
            <NavLink to="/settings/users">
              <IconUsers /> Users
            </NavLink>
          )}
        </nav>
        <div className="sidebar-foot">
          <div className="avatar">{user?.username.slice(0, 2)}</div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="truncate" style={{ fontWeight: 500 }}>
              {user?.username}
            </div>
            <div className="faint tiny">{user?.is_admin ? "admin" : "member"}</div>
          </div>
          <button
            className="btn ghost icon"
            title="Log out"
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
          <div className="segmented" role="group" aria-label="Theme">
            {THEMES.map((t) => (
              <button
                key={t.value}
                className={theme === t.value ? "on" : ""}
                title={t.title}
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
