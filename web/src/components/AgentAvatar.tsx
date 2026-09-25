import type { ReactNode } from "react";

/**
 * One drawn character per role, for the places with room for it (agent cards, the agent
 * page header).
 *
 * The figure is a helmet, not a robot head: a dome that narrows to a jaw, a single thin
 * mouth slot, and two lit slits for eyes. That shape is the whole point — a boxy head
 * with a vent for a mouth reads as machinery, and these are meant to read as somebody
 * wearing a suit. The form is a plain sci-fi faceplate rather than any particular
 * character's, which is also why nothing here copies a design that belongs to someone.
 *
 * Every role shares the helmet and differs in what is fitted to it, and that fitting is
 * the tool of the trade: the Architect's brim, the Backend's temple vents, QA's scope
 * over one eye. So the set reads as one squad first and as nine jobs second.
 *
 * Everything is drawn in ``currentColor``, so the colour comes from CSS alone
 * (``.agent-avatar[data-agent]`` in styles.css) and light and dark need no second copy.
 * The one exception is the highlight that runs along the eyes, which is white on purpose:
 * it is a reflection, and a reflection is not the colour of the thing it is on.
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

/**
 * The faceplate: a dome across the brow, straight temples, then a jaw that narrows to a
 * chin sitting just above the shoulders.
 */
const SHELL =
  "M22 5.4c6.3 0 10.6 3.6 10.6 9.2v4.4c0 5.6-4.2 10.4-10.6 11.8" +
  "c-6.4-1.4-10.6-6.2-10.6-11.8v-4.4c0-5.6 4.3-9.2 10.6-9.2z";

function Shell() {
  return <path d={SHELL} {...TINT} />;
}

/**
 * An eye: a slit that rides higher at the temple than at the nose, so the face reads as
 * alert. The direction matters more than the amount -- drop the outer end instead and the
 * same shape reads as downcast, which is how this first went out.
 *
 * The highlight travels the length of the slit rather than across a pupil, which is why
 * it finally reads at card size: the slit is five units wide, so the run is ±1.4 and
 * visible, and it still needs no clip path to stay inside.
 */
function Eye({ side }: { side: -1 | 1 }) {
  const outer = 22 + side * 7.4;
  const inner = 22 + side * 2.4;
  return (
    <g className="eye">
      <path
        className="eye-slit"
        d={`M${outer} 17.1L${inner} 17.7L${inner} 19.9L${outer} 19.3Z`}
        {...SOLID}
      />
      <circle
        className="eye-glint"
        cx={(outer + inner) / 2}
        cy={18.5}
        r={0.62}
        fill="#fff"
        stroke="none"
        opacity={0}
      />
    </g>
  );
}

function Eyes() {
  return (
    <>
      <Eye side={-1} />
      <Eye side={1} />
    </>
  );
}

/** The one slot the faceplate has for a mouth. A single line, never a grille — the grille
 *  is what made these read as machines. */
function Mouth({ y = 25.6, w = 7.4 }: { y?: number; w?: number }) {
  return <path d={`M${22 - w / 2} ${y}h${w}`} strokeWidth={1.5} opacity={0.42} />;
}

/** The seams that make the shell look pressed rather than moulded: the crown across the
 *  brow and a panel line down each cheek. */
function Seams({ brow = true }: { brow?: boolean }) {
  return (
    <g opacity={0.32}>
      {brow && <path d="M13.6 13.4c2.6-3.1 14.2-3.1 16.8 0" strokeWidth={1.3} />}
      <path d="M14.6 21.8 16.9 26.8" strokeWidth={1.2} />
      <path d="M29.4 21.8 27.1 26.8" strokeWidth={1.2} />
    </g>
  );
}

/** The plain helmet, for the roles whose mark is fitted on top of it. */
function Plain({ children }: { children?: ReactNode }) {
  return (
    <>
      <Shell />
      <Seams />
      <Eyes />
      <Mouth />
      {children}
    </>
  );
}

function head(role: string): ReactNode {
  switch (role) {
    // the backlog, carried as a crest: the plate the approved items are ticked off on
    case "po":
      return (
        <>
          <Shell />
          <Seams brow={false} />
          <rect x={17.4} y={9.4} width={9.2} height={5.6} rx={1.7} {...TINT} />
          <path d="M19.3 12.2l1.7 1.8 3.5-3.4" strokeWidth={1.5} opacity={0.85} />
          <Eyes />
          <Mouth />
        </>
      );
    // the brim of the hard hat, over the helmet: the one who decides how it gets built
    case "architect":
      return (
        <Plain>
          <path d="M8.6 13.2h26.8" strokeWidth={1.8} />
          <path d="M14.2 13.2c0-4.6 2.6-7.4 7.8-7.4s7.8 2.8 7.8 7.4" {...TINT} />
        </Plain>
      );
    // vents at the temples: the machine under everything has to breathe
    case "backend":
      return (
        <>
          <Shell />
          <Seams brow={false} />
          <g opacity={0.5} strokeWidth={1.3}>
            <path d="M17.6 10.2h8.8M17 12.4h10M17.6 14.6h8.8" />
          </g>
          <Eyes />
          <Mouth />
        </>
      );
    // a visor band across the eyes, with the window's own lights set into it
    case "web_ui":
      return (
        <>
          <Shell />
          <Seams />
          <path d="M11.6 14.9h20.8v7.2H11.6z" {...TINT} />
          <path d="M11.7 14.9h20.6" strokeWidth={1.2} opacity={0.45} />
          <Eyes />
          <circle cx={13.6} cy={12.8} r={0.95} {...SOLID} opacity={0.6} />
          <circle cx={16.4} cy={12.8} r={0.95} {...SOLID} opacity={0.6} />
          <Mouth />
        </>
      );
    // a narrower shell and an earpiece slot: the one that lives in a hand
    case "mobile_ui":
      return (
        <>
          <path
            d="M22 5.6c5.2 0 8.7 3.4 8.7 8.8v5c0 5.5-3.4 10.1-8.7 11.4
               c-5.3-1.3-8.7-5.9-8.7-11.4v-5c0-5.4 3.5-8.8 8.7-8.8z"
            {...TINT}
          />
          <g opacity={0.32}>
            <path d="M15.6 13.6c2-2.6 10.8-2.6 12.8 0" strokeWidth={1.3} />
          </g>
          <path d="M19.8 9.2h4.4" strokeWidth={1.4} opacity={0.5} />
          <Eyes />
          <Mouth y={25.4} w={6} />
        </>
      );
    // the scope, dropped over one eye: the one looking for what is wrong
    case "qa":
      return (
        <>
          <Shell />
          <Seams />
          <Eye side={-1} />
          <circle cx={26.9} cy={18.4} r={4.6} strokeWidth={1.6} />
          <circle cx={26.9} cy={18.4} r={4.6} {...TINT} />
          <path d="M30.4 21.8 33.4 25" strokeWidth={1.7} />
          <Mouth />
        </>
      );
    // the faceted plate of a nut: the one that bolts the pipeline together
    case "devops":
      return (
        <>
          <path
            d="M22 5.2l9.4 5.3v10.6c0 5-3.6 9-9.4 10.1c-5.8-1.1-9.4-5.1-9.4-10.1V10.5z"
            {...TINT}
          />
          <g opacity={0.32}>
            <path d="M14.6 12.1 22 8.2l7.4 3.9" strokeWidth={1.3} />
            <path d="M15 22.2 17.1 27M29 22.2 26.9 27" strokeWidth={1.2} />
          </g>
          <Eyes />
          <Mouth />
        </>
      );
    // a brow ridge and the stamp: reads what waits at the gate and rules on it
    case "supervisor":
      return (
        <>
          <Shell />
          <Seams />
          <path d="M13.9 14.8 19.4 16.2" strokeWidth={1.4} opacity={0.65} />
          <path d="M30.1 14.8 24.6 16.2" strokeWidth={1.4} opacity={0.65} />
          <Eyes />
          <Mouth />
          <circle cx={33.4} cy={27.4} r={5.3} fill="var(--surface)" />
          <path d="M31.1 27.3l1.7 1.8 3.1-3.5" strokeWidth={1.7} />
        </>
      );
    // the Designer and anyone new: the shell with nothing fitted to it
    default:
      return <Plain />;
  }
}
