import { useState } from "react";
import { Link } from "react-router-dom";
import type { ActivityItem } from "../api/client";
import { useTransition } from "../api/hooks";
import { Detail } from "./Detail";
import { ROLE_LABEL } from "./agents";
import {
  IconActivity,
  IconAlert,
  IconBot,
  IconCheck,
  IconFlask,
  IconInbox,
  IconLayers,
  IconPlay,
  IconTicket,
  IconUsers,
} from "./icons";
import { Loading, formatTime } from "./ui";
import { useT } from "../i18n";

const KIND: Record<ActivityItem["kind"], { label: string; cls: string; icon: React.ReactNode }> = {
  started: { label: "started", cls: "", icon: <IconPlay /> },
  role: { label: "agent", cls: "", icon: <IconBot /> },
  gate: { label: "build gate", cls: "work", icon: <IconFlask /> },
  approval: { label: "you", cls: "wait", icon: <IconUsers /> },
  inbox: { label: "steering", cls: "wait", icon: <IconInbox /> },
  jira: { label: "jira", cls: "", icon: <IconTicket /> },
  standards: { label: "standards", cls: "", icon: <IconLayers /> },
  crash: { label: "crash", cls: "bad", icon: <IconAlert /> },
  failed: { label: "failed", cls: "bad", icon: <IconAlert /> },
  done: { label: "done", cls: "ok", icon: <IconCheck /> },
  other: { label: "", cls: "", icon: <IconActivity /> },
};

/** A note longer than this is a paragraph, not a headline: it is clamped to two lines
 *  with a "more" toggle, so one talkative entry cannot bury the rest of the feed. */
const LONG_NOTE = 180;

export function ActivityRow({
  item,
  projectId,
  projectName,
  showJob = true,
  compact = false,
}: {
  item: ActivityItem;
  projectId: string;
  projectName?: string;
  showJob?: boolean;
  /** On the dashboard the feed is a glance, not a reader: the detail stays folded away
   *  on the development's own page, where there is room for it. One entry unfolding a
   *  whole pull-request body used to push everything else off the screen. */
  compact?: boolean;
}) {
  const tx = useT();
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState(false);
  const detail = useTransition(item.job_id, open ? item.index : null);
  const kind = KIND[item.kind];
  const who = item.role ? tx(ROLE_LABEL[item.role] ?? item.role) : tx(kind.label);
  // notes are written "<role>: ..."; the badge already names the role
  const title =
    item.role && item.title.startsWith(`${item.role}:`)
      ? item.title.slice(item.role.length + 1).trim()
      : item.title;
  const gateFailed = item.kind === "gate" && item.title.includes("failed");
  const long = title.length > LONG_NOTE;
  return (
    <li>
      <span className={`ico ${gateFailed ? "bad" : kind.cls}`}>{kind.icon}</span>
      <span style={{ minWidth: 0 }}>
        <span className={`note${long && !full ? " clamp" : ""}`}>
          {who && <span className="who">{who}</span>}
          {title}
        </span>
        {long && (
          <button type="button" className="linkish" onClick={() => setFull(!full)}>
            {full ? tx("less") : tx("more")}
          </button>
        )}
        {showJob && (
          <div className="faint tiny truncate">
            <Link to={`/projects/${projectId}/jobs/${item.job_id}`} className="faint">
              {projectName ? `${projectName} · ` : ""}
              {item.job_request}
            </Link>
          </div>
        )}
        {item.has_detail && !compact && (
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
