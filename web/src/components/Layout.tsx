import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useLiveEvents } from "../api/events";
import { isOwner } from "../api/gates";
import { useMyTeam } from "../api/hooks";
import { BrandMark } from "./BrandMark";
import { LangPicker } from "./LangPicker";
import { useToast } from "./Toast";
import { useAuth } from "../auth/AuthProvider";
import {
  IconBot,
  IconCpu,
  IconFolder,
  IconGit,
  IconHome,
  IconLifebuoy,
  IconLogout,
  IconMail,
  IconMonitor,
  IconMoon,
  IconSun,
  IconTicket,
  IconUsers,
  IconBell,
  IconMessage,
  IconShield,
} from "./icons";
import { useTheme, type Theme } from "./theme";
import { useT } from "../i18n";
import { SUPPORT_DESK } from "../features";
import { BuildWatch } from "./BuildWatch";
import { SetupReturn } from "./Onboarding";

const THEMES: { value: Theme; icon: React.ReactNode; title: string }[] = [
  { value: "light", icon: <IconSun />, title: "Light" },
  { value: "dark", icon: <IconMoon />, title: "Dark" },
  { value: "system", icon: <IconMonitor />, title: "System" },
];

/** Signed in, but the address is still unproved: everything reads, nothing runs. The
 *  banner is the only place that says so, because a 403 at the moment of starting work
 *  is a poor way to learn it. */
function DefaultPasswordBanner() {
  const tx = useT();
  // asked of the server rather than remembered, so it goes away the moment the password
  // is changed -- and stays until it is. A published default is only safe while everybody
  // can see that it is still in place.
  const still = useQuery({
    queryKey: ["first-run"],
    queryFn: () => api.get<{ default_admin: boolean }>("/api/auth/first-run"),
    refetchInterval: 60_000,
  });
  if (!still.data?.default_admin) return null;
  return (
    <div className="callout error banner-verify">
      <span>
        {tx(
          "This server still lets anybody in with the password it started with. Change it before it is reachable from anywhere but this machine.",
        )}
      </span>
      <Link className="btn tiny" to="/settings/users">
        {tx("Change it")}
      </Link>
    </div>
  );
}

function UnverifiedBanner() {
  const tx = useT();
  const { unverified, user } = useAuth();
  if (!unverified) return null;
  return (
    <div className="callout warn banner-verify">
      <span>{tx("Confirm {email} before starting any work.", { email: user?.email ?? "" })}</span>
      <Link className="btn tiny" to="/verify">
        {tx("Confirm now")}
      </Link>
    </div>
  );
}

export function Layout() {
  const tx = useT();
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  const toast = useToast();
  useLiveEvents(undefined, toast.ok);
  const overview = useQuery({
    queryKey: ["overview", "badge"],
    queryFn: () => api.get<{ pending_approvals: number }>("/api/overview?recent=0"),
    refetchInterval: 30_000,
  });
  const pending = overview.data?.pending_approvals ?? 0;
  const team = useMyTeam();
  const owner = isOwner(team.data);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <BrandMark /> {tx("Slipwright")}
        </div>
        <nav className="nav">
          <NavLink to="/" end data-nav="dashboard">
            <IconHome /> {tx("Dashboard")}
            {pending > 0 && <span className="count">{pending}</span>}
          </NavLink>
          <NavLink to="/projects" data-nav="projects">
            <IconFolder /> {tx("Projects")}
          </NavLink>
          <NavLink to="/agents" data-nav="agents">
            <IconBot /> {tx("Agents")}
          </NavLink>
          {SUPPORT_DESK && (
            <NavLink to="/support" data-nav="support">
              <IconLifebuoy /> {tx("Support")}
            </NavLink>
          )}
          {/* the settings belong to whoever owns the account; somebody who holds an
              agent configures it on the agent's own page */}
          {owner && <div className="nav-label">{tx("Settings")}</div>}
          {owner && (
            <NavLink to="/settings/models" data-nav="models">
              <IconCpu /> {tx("Models")}
            </NavLink>
          )}
          {owner && (
            <NavLink to="/settings/sources" data-nav="sources">
              <IconGit /> {tx("Sources")}
            </NavLink>
          )}
          {owner && (
            <NavLink to="/settings/jira" data-nav="jira">
              <IconTicket /> {tx("Jira")}
            </NavLink>
          )}
          {owner && user?.is_admin && (
            <NavLink to="/settings/email" data-nav="email">
              <IconMail /> {tx("Email")}
            </NavLink>
          )}
          {/* under Email, because the two answer the same question -- where word of this
              reaches you. Not guarded like the rest of the settings: everybody on the
              account links their own chat here, and only setting the channels up belongs
              to the owner, which the page itself decides. For somebody who is not the
              owner the links above render nothing, so this lands back beside Agents. */}
          <NavLink to="/notifications" data-nav="notifications">
            <IconBell /> {tx("Notifications")}
          </NavLink>
          {/* beside Notifications, because both are about the same chat -- but not the
              same job: a group is told, and this is where somebody works from their own
              chat. Ungated like Notifications, since a member links their account here */}
          <NavLink to="/remote" data-nav="remote">
            <IconMessage /> {tx("Remote control")}
          </NavLink>
          {/* the person's own sign-in, so ungated: a member has a password too */}
          <NavLink to="/security" data-nav="security">
            <IconShield /> {tx("Security")}
          </NavLink>
          {owner && user?.is_admin && (
            <NavLink to="/settings/users" data-nav="users">
              <IconUsers /> {tx("Users")}
            </NavLink>
          )}
        </nav>
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
        <BuildWatch />
      </aside>
      <div className="main">
        <header className="topbar">
          <div id="crumbs" className="crumbs" />
          <LangPicker />
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
          <DefaultPasswordBanner />
          <UnverifiedBanner />
          <SetupReturn />
          <Outlet />
        </main>
      </div>
    </div>
  );
}
