// Two flags, drawn rather than typed. The emoji ones (🇹🇷 🇬🇧) are regional-indicator
// pairs, and Windows ships no glyph for them: on the very machines most of these people
// are using they arrive as the bare letters in a box. So: small SVGs, 3:2, no gradients,
// legible at 18px in either theme.
import { useId, type SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = (p: P) => ({ viewBox: "0 0 30 20", "aria-hidden": true, ...p });

export const FlagTR = (p: P) => (
  <svg {...base(p)}>
    <rect width="30" height="20" fill="#e30a17" />
    {/* the crescent is one white disc with a red one bitten out of it */}
    <circle cx="11.5" cy="10" r="5" fill="#fff" />
    <circle cx="12.9" cy="10" r="4" fill="#e30a17" />
    <polygon
      points="20.4,10 18.65,10.62 18.6,12.47 17.48,11 15.7,11.53 16.75,10 15.7,8.47 17.48,9 18.6,7.53 18.65,9.38"
      fill="#fff"
    />
  </svg>
);

export const FlagGB = (p: P) => {
  // each instance clips against its own id, so two flags on a page cannot borrow one
  // another's shape
  const id = useId();
  return (
    <svg {...base(p)}>
      <clipPath id={id}>
        <rect width="30" height="20" />
      </clipPath>
      <g clipPath={`url(#${id})`}>
        <rect width="30" height="20" fill="#012169" />
        <path d="M0 0 30 20M30 0 0 20" stroke="#fff" strokeWidth="4.5" />
        <path d="M0 0 30 20M30 0 0 20" stroke="#c8102e" strokeWidth="2" />
        <path d="M15 0V20M0 10H30" stroke="#fff" strokeWidth="7.5" />
        <path d="M15 0V20M0 10H30" stroke="#c8102e" strokeWidth="4.5" />
      </g>
    </svg>
  );
};
