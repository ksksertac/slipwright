import type { ReactNode } from "react";
import {
  IconBot,
  IconCpu,
  IconFlask,
  IconGit,
  IconLayers,
  IconMonitor,
  IconTicket,
  IconUsers,
} from "./icons";
import { useT } from "../i18n";

/** Role -> icon, used on cards, badges and the pipeline view. */
export function AgentIcon({ role }: { role: string }): ReactNode {
  switch (role) {
    case "po":
      return <IconTicket />;
    case "architect":
      return <IconLayers />;
    case "backend":
      return <IconCpu />;
    case "designer":
      return <IconLayout />;
    case "web_ui":
      return <IconMonitor />;
    case "mobile_ui":
      return <IconMobile />;
    case "qa":
      return <IconFlask />;
    case "devops":
      return <IconGit />;
    case "supervisor":
      return <IconUsers />;
    default:
      return <IconBot />;
  }
}

/** A frame split into regions: a screen decided, not yet built. */
function IconLayout() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9h18M9 9v11" />
    </svg>
  );
}

function IconMobile() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="7" y="2.5" width="10" height="19" rx="2" />
      <path d="M11 18h2" />
    </svg>
  );
}

export const ROLE_LABEL: Record<string, string> = {
  po: "Product Owner",
  architect: "Architect",
  backend: "Backend Developer",
  designer: "Designer",
  web_ui: "Web Developer",
  mobile_ui: "Mobile Developer",
  qa: "QA",
  devops: "DevOps",
  supervisor: "Supervisor",
};

export const DOMAIN_LABEL: Record<string, string> = {
  backend: "backend",
  web: "web",
  mobile: "mobile",
  infra: "infra",
  docs: "docs",
  general: "general",
};

export function DomainBadge({ domain }: { domain: string | undefined }) {
  const tx = useT();
  if (!domain || domain === "general") return null;
  return (
    <span className="tag" title={tx("domain")}>
      {tx(DOMAIN_LABEL[domain] ?? domain)}
    </span>
  );
}
