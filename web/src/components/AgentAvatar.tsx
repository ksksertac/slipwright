import type { ReactNode } from "react";

/**
 * One drawn character per role, for the places with room for it (agent cards, the agent
 * page header). Every figure shares the same silhouette — the shoulders below, the eyes
 * on the same line — and differs only in the head, which is the tool of the trade: the
 * Product Owner is a clipboard, the Architect wears the hard hat, Backend is a rack.
 *
 * Everything is drawn in ``currentColor``, so the colour comes from CSS alone
 * (``.agent-avatar[data-agent]`` in styles.css) and light and dark need no second copy.
 * Small places (the pipeline steps) keep the plain glyph in ``agents.tsx``.
 */
export function AgentAvatar({ role, className = "" }: { role: string; className?: string }) {
  return (
    <span className={`agent-avatar ${className}`.trim()} data-agent={role}>
      <Figure>{head(role)}</Figure>
    </span>
  );
}

/** Shared fill: a tint of the role colour, so one colour drives the whole drawing. */
const TINT = { fill: "currentColor", fillOpacity: 0.14 } as const;
const SOLID = { fill: "currentColor", stroke: "none" } as const;

function Figure({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 44 44"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {/* the shoulders every role shares, so the set reads as one family */}
      <path d="M8.5 39.5c0-5.8 6-9 13.5-9s13.5 3.2 13.5 9" opacity={0.45} />
      {children}
    </svg>
  );
}

function Eyes({ y = 17.5, dx = 4.5 }: { y?: number; dx?: number }) {
  return (
    <>
      <circle cx={22 - dx} cy={y} r={1.65} {...SOLID} />
      <circle cx={22 + dx} cy={y} r={1.65} {...SOLID} />
    </>
  );
}

function head(role: string): ReactNode {
  switch (role) {
    // the backlog on a clipboard, with the tick of an approved item
    case "po":
      return (
        <>
          <rect x={18} y={3.5} width={8} height={5} rx={1.6} {...TINT} />
          <rect x={10} y={7} width={24} height={22.5} rx={3.5} {...TINT} />
          <Eyes y={16} />
          <path d="M17.5 23.5l3 3 5.5-5.5" opacity={0.75} />
        </>
      );
    // the hard hat: the one who decides how it gets built
    case "architect":
      return (
        <>
          <rect x={11} y={11} width={22} height={18.5} rx={5.5} {...TINT} />
          <Eyes y={19.5} />
          <path d="M18 25.5h8" opacity={0.6} />
          <path d="M13 11a9 9 0 0 1 18 0" {...TINT} />
          <path d="M9 11h26" />
          <path d="M22 2.2v3.4" opacity={0.6} />
        </>
      );
    // a rack: services, data, the machine under everything
    case "backend":
      return (
        <>
          <rect x={10} y={7.5} width={24} height={22} rx={3} {...TINT} />
          <Eyes y={14} />
          <path d="M10 20.5h24" opacity={0.45} />
          <circle cx={14.5} cy={25} r={1.2} {...SOLID} opacity={0.8} />
          <path d="M19 25h11" opacity={0.5} />
        </>
      );
    // a browser window, traffic lights and all
    case "web_ui":
      return (
        <>
          <rect x={8} y={8} width={28} height={21} rx={3.2} {...TINT} />
          <path d="M8 13.5h28" opacity={0.45} />
          <circle cx={11.8} cy={10.8} r={1} {...SOLID} opacity={0.7} />
          <circle cx={15.3} cy={10.8} r={1} {...SOLID} opacity={0.7} />
          <Eyes y={20} />
          <path d="M19 25h6" opacity={0.6} />
        </>
      );
    // a handset, earpiece above and home indicator below
    case "mobile_ui":
      return (
        <>
          <rect x={13} y={5} width={18} height={25} rx={4.2} {...TINT} />
          <path d="M19.5 9h5" opacity={0.6} />
          <Eyes y={17} dx={4} />
          <path d="M19.5 22h5" opacity={0.6} />
          <path d="M19 27h6" opacity={0.4} />
        </>
      );
    // looking for the bug through the glass
    case "qa":
      return (
        <>
          <circle cx={22} cy={18} r={11.5} {...TINT} />
          <circle cx={17.2} cy={16.5} r={1.65} {...SOLID} />
          <circle cx={26.8} cy={16.5} r={4.3} />
          <path d="M29.9 19.7l3.3 3.5" />
          <path d="M18 24.5h8" opacity={0.55} />
        </>
      );
    // a nut: the one that bolts the pipeline together
    case "devops":
      return (
        <>
          <path d="M22 5l9.8 5.5v11L22 27l-9.8-5.5v-11z" {...TINT} />
          <Eyes y={15} dx={4.2} />
          <path d="M18.5 20.5h7" opacity={0.6} />
        </>
      );
    // reads what waits at the gate and stamps it
    case "supervisor":
      return (
        <>
          <circle cx={20} cy={17.5} r={11} {...TINT} />
          <Eyes y={17} dx={4.4} />
          <path d="M13.4 12.8l4.4 1.6" opacity={0.7} />
          <path d="M26.6 12.8l-4.4 1.6" opacity={0.7} />
          <path d="M16.5 23.5c1.6 1.3 5.4 1.3 7 0" opacity={0.55} />
          <circle cx={33} cy={26.5} r={5.4} fill="var(--surface)" />
          <path d="M30.7 26.4l1.7 1.8 3.1-3.5" strokeWidth={1.7} />
        </>
      );
    default:
      return (
        <>
          <rect x={10.5} y={8} width={23} height={21.5} rx={6} {...TINT} />
          <Eyes y={17} />
          <path d="M18 24h8" opacity={0.6} />
          <path d="M22 2.5v4" opacity={0.6} />
        </>
      );
  }
}
