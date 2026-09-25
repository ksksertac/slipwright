import { Fragment } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { useT } from "../i18n";

export interface Crumb {
  label: string;
  to?: string;
}

/**
 * Breadcrumbs rendered into the top bar from whichever page is mounted.
 *
 * A trail is only drawn when it leads somewhere: the last crumb repeats the page's own
 * <h1>, so with no clickable ancestor above it the top bar said "Dashboard" over a page
 * already titled "Dashboard" and added nothing. Pages at the top of the tree therefore
 * pass no crumbs at all, and this guard keeps the next one honest.
 */
export function Crumbs({ items }: { items: Crumb[] }) {
  const tx = useT();
  // the Layout renders #crumbs before any page mounts, so the lookup is safe at render
  const host = typeof document === "undefined" ? null : document.getElementById("crumbs");
  if (!host) return null;
  if (!items.slice(0, -1).some((c) => c.to)) return null;
  return createPortal(
    <>
      {items.map((c, i) => (
        <Fragment key={i}>
          {i > 0 && <span className="sep">/</span>}
          {c.to && i < items.length - 1 ? (
            <Link to={c.to} className="truncate">
              {tx(c.label)}
            </Link>
          ) : (
            <span className="current truncate">{tx(c.label)}</span>
          )}
        </Fragment>
      ))}
    </>,
    host,
  );
}
