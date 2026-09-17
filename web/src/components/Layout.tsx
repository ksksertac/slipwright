import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useLiveEvents } from "../api/events";

export function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  useLiveEvents();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">⛵</span> Slipwright
        </div>
        <nav>
          <NavLink to="/projects">Projects</NavLink>
          <NavLink to="/settings/github">Settings</NavLink>
          <div className="nav-sub">
            <NavLink to="/settings/github">GitHub</NavLink>
            <NavLink to="/settings/jira">Jira</NavLink>
            <NavLink to="/settings/agents">Agents</NavLink>
            {user?.is_admin && <NavLink to="/settings/users">Users</NavLink>}
          </div>
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div />
          <div className="user">
            <span>
              {user?.username}
              {user?.is_admin && <span className="tag">admin</span>}
            </span>
            <button
              className="btn small"
              onClick={() => {
                void logout().then(() => navigate("/login"));
              }}
            >
              Log out
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
