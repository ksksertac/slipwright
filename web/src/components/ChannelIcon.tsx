// Each chat service's own mark, drawn small, so the Notifications tabs read at a glance.
// Simplified shapes in the services' brand colours; they only identify the service.
import type { ChannelName } from "../api/client";

function Telegram() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <circle cx="12" cy="12" r="12" fill="#229ED9" />
      <path
        fill="#fff"
        d="M5.4 11.6l11.3-4.4c.5-.2 1 .1.8.9l-1.9 9c-.1.6-.5.8-1 .5l-2.9-2.1-1.4 1.3c-.2.2-.3.3-.6.3l.2-3 5.4-4.9c.2-.2 0-.3-.3-.1l-6.7 4.2-2.9-.9c-.6-.2-.6-.6.1-.9z"
      />
    </svg>
  );
}

function Slack() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <rect x="9.6" y="2" width="3.2" height="9" rx="1.6" fill="#36C5F0" />
      <rect x="2" y="11.2" width="9" height="3.2" rx="1.6" fill="#E01E5A" />
      <rect x="11.2" y="13" width="3.2" height="9" rx="1.6" fill="#ECB22E" />
      <rect x="13" y="9.6" width="9" height="3.2" rx="1.6" fill="#2EB67D" />
      <circle cx="6.8" cy="7.9" r="1.6" fill="#36C5F0" />
      <circle cx="16.1" cy="6.8" r="1.6" fill="#2EB67D" />
      <circle cx="17.2" cy="16.1" r="1.6" fill="#ECB22E" />
      <circle cx="7.9" cy="17.2" r="1.6" fill="#E01E5A" />
    </svg>
  );
}

function Discord() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <rect width="24" height="24" rx="6" fill="#5865F2" />
      <path
        fill="#fff"
        d="M17.3 7.3a12 12 0 0 0-3-.9l-.4.8a11 11 0 0 0-3.8 0l-.4-.8a12 12 0 0 0-3 .9C4.8 10.2 4.3 13 4.5 15.8a12 12 0 0 0 3.7 1.9l.8-1.3-1.3-.6.3-.2a8.6 8.6 0 0 0 7.9 0l.3.2-1.3.6.8 1.3a12 12 0 0 0 3.7-1.9c.3-3.3-.5-6-2.1-8.5zM9.6 14.2c-.7 0-1.3-.7-1.3-1.5s.6-1.5 1.3-1.5 1.3.7 1.3 1.5-.6 1.5-1.3 1.5zm4.8 0c-.7 0-1.3-.7-1.3-1.5s.6-1.5 1.3-1.5 1.3.7 1.3 1.5-.6 1.5-1.3 1.5z"
      />
    </svg>
  );
}

function Teams() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden>
      <circle cx="18.2" cy="6.4" r="2.6" fill="#7B83EB" />
      <rect x="13" y="10" width="10" height="9" rx="2.5" fill="#7B83EB" />
      <circle cx="12.4" cy="5.2" r="3.2" fill="#5059C9" />
      <rect x="1" y="7" width="14" height="14" rx="2.5" fill="#4B53BC" />
      <path fill="#fff" d="M4.5 10.2h7v1.9H9v6.2H7v-6.2H4.5z" />
    </svg>
  );
}

const MARKS: Record<ChannelName, () => React.JSX.Element> = {
  telegram: Telegram,
  slack: Slack,
  discord: Discord,
  teams: Teams,
};

/** The service's mark, with its setup state as a dot on the corner. */
export function ChannelIcon({
  channel,
  state,
}: {
  channel: ChannelName;
  state?: "done" | "todo" | "optional";
}) {
  const Mark = MARKS[channel];
  return (
    <span className="channel-icon">
      <Mark />
      {state && <span className={`channel-icon-dot ${state}`} />}
    </span>
  );
}
