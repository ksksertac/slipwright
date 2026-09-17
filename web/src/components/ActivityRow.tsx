import { useState } from "react";
import { Link } from "react-router-dom";
import type { ActivityItem } from "../api/client";
import { useTransition } from "../api/hooks";
import { Detail } from "./Detail";
import {
  IconActivity,
  IconAlert,
  IconBot,
  IconCheck,
  IconFlask,
  IconInbox,
  IconPlay,
  IconTicket,
  IconUsers,
} from "./icons";
import { Loading, formatTime } from "./ui";

const KIND: Record<ActivityItem["kind"], { label: string; cls: string; icon: React.ReactNode }> = {
  started: { label: "started", cls: "", icon: <IconPlay /> },
  role: { label: "agent", cls: "", icon: <IconBot /> },
  gate: { label: "build gate", cls: "work", icon: <IconFlask /> },
  approval: { label: "you", cls: "wait", icon: <IconUsers /> },
  inbox: { label: "steering", cls: "wait", icon: <IconInbox /> },
  jira: { label: "jira", cls: "", icon: <IconTicket /> },
  crash: { label: "crash", cls: "bad", icon: <IconAlert /> },
  failed: { label: "failed", cls: "bad", icon: <IconAlert /> },
  done: { label: "done", cls: "ok", icon: <IconCheck /> },
  other: { label: "", cls: "", icon: <IconActivity /> },
};

export function ActivityRow({
  item,
  projectId,
  projectName,
  showJob = true,
}: {
  item: ActivityItem;
  projectId: string;
  projectName?: string;
  showJob?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const detail = useTransition(item.job_id, open ? item.index : null);
  const kind = KIND[item.kind];
  const who = item.role ?? kind.label;
  // notes are written "<role>: ..."; the badge already names the role
  const title =
    item.role && item.title.startsWith(`${item.role}:`)
      ? item.title.slice(item.role.length + 1).trim()
      : item.title;
  const gateFailed = item.kind === "gate" && item.title.includes("failed");
  return (
    <li>
      <span className={`ico ${gateFailed ? "bad" : kind.cls}`}>{kind.icon}</span>
      <span style={{ minWidth: 0 }}>
        {who && <span className="who">{who}</span>}
        {title}
        {showJob && (
          <div className="faint tiny truncate">
            <Link to={`/projects/${projectId}/jobs/${item.job_id}`} className="faint">
              {projectName ? `${projectName} · ` : ""}
              {item.job_request}
            </Link>
          </div>
        )}
        {item.has_detail && (
          <details onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
            <summary>detail</summary>
            {detail.isLoading && <Loading rows={2} />}
            {detail.data && <Detail text={detail.data.detail} />}
          </details>
        )}
      </span>
      <span className="when" title={item.at}>
        {formatTime(item.at)}
      </span>
    </li>
  );
}
