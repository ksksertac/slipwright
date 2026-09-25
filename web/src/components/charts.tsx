// The dashboard's three figures, drawn by hand against the styles in styles.css: no chart
// library, one measure per figure, thin marks on a hairline baseline, the peak labelled and
// the pointer for the rest, and every value reachable without a pointer in the folded table.
// One hue carries magnitude (the accent); the status colours appear only where a colour
// means running / waiting / done / failed, always beside the label and the count.
import { useState, type ReactNode } from "react";
import type { DayActivity, Overview, RoleWork } from "../api/client";
import { AgentIcon } from "./agents";
import { timeAgo } from "./ui";
import { useT, type T } from "../i18n";

function Figure({
  title,
  lead,
  children,
  table,
}: {
  title: string;
  lead?: ReactNode;
  children: ReactNode;
  table: { head: string[]; rows: (string | number)[][] };
}) {
  const tx = useT();
  return (
    <figure className="figure">
      <figcaption>
        <span className="figure-title">{title}</span>
        {lead && <span className="figure-lead">{lead}</span>}
      </figcaption>
      {children}
      <details className="figure-table">
        <summary>{tx("the numbers")}</summary>
        <table className="mini">
          <thead>
            <tr>
              {table.head.map((h, i) => (
                <th key={h} className={i === 0 ? "" : "num"}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className={j === 0 ? "" : "num"}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

function shortDay(iso: string, tx: T): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return tx("{day}.{month}", {
    day: d.getUTCDate(),
    month: String(d.getUTCMonth() + 1).padStart(2, "0"),
  });
}

/** The pace of the work: one column a day, the busiest day labelled. */
export function ActivityChart({ days }: { days: DayActivity[] }) {
  const tx = useT();
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...days.map((d) => d.events));
  const peak = days.findIndex((d) => d.events === max && max > 0);
  const total = days.reduce((sum, d) => sum + d.events, 0);
  const finished = days.reduce((sum, d) => sum + d.finished, 0);
  return (
    <Figure
      title={tx("The last {n} days", { n: days.length })}
      lead={
        <>
          <strong>{total}</strong> {tx("steps")} · <strong>{finished}</strong> {tx("finished")}
        </>
      }
      table={{
        head: [tx("Day"), tx("steps"), tx("finished")],
        rows: days.map((d) => [d.day, d.events, d.finished]),
      }}
    >
      <div className="chart-columns">
        <div className="cols">
          {days.map((d, i) => (
            <div
              key={d.day}
              className="band"
              tabIndex={0}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            >
              {i === peak && max > 0 && <span className="cap">{max}</span>}
              <span
                className="col"
                style={{ height: `${Math.max(d.events === 0 ? 0 : 3, (d.events / max) * 100)}%` }}
              />
              {hover === i && (
                <span className="chart-tip">
                  <strong>{d.events}</strong> {tx("steps")}
                  {d.finished > 0 && (
                    <>
                      {" "}
                      · <strong>{d.finished}</strong> {tx("finished")}
                    </>
                  )}
                  <span className="when">{d.day}</span>
                </span>
              )}
            </div>
          ))}
        </div>
        <div className="chart-x">
          <span>{days.length > 0 ? shortDay(days[0]!.day, tx) : ""}</span>
          <span>{days.length > 0 ? shortDay(days[days.length - 1]!.day, tx) : ""}</span>
        </div>
      </div>
    </Figure>
  );
}

/** Where the developments stand: one stacked bar, every part named beside its count. */
export function StateBar({ o }: { o: Overview }) {
  const tx = useT();
  const parts = [
    { key: "ok", label: tx("done"), value: o.jobs_done },
    { key: "work", label: tx("running"), value: o.jobs_running },
    { key: "wait", label: tx("waiting for you"), value: o.pending_approvals },
    { key: "bad", label: tx("failed"), value: o.jobs_failed },
  ];
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  return (
    <Figure
      title={tx("Where the developments stand")}
      lead={
        <>
          <strong>{o.jobs_total}</strong> {tx("in total")}
        </>
      }
      table={{
        head: [tx("State"), tx("Developments")],
        rows: parts.map((p) => [p.label, p.value]),
      }}
    >
      {total === 0 ? (
        <div className="muted small">{tx("No development yet")}</div>
      ) : (
        <div className="stackbar">
          {parts
            .filter((p) => p.value > 0)
            .map((p) => (
              <span
                key={p.key}
                className={`seg ${p.key}`}
                style={{ width: `${(p.value / total) * 100}%` }}
                title={`${p.label}: ${p.value}`}
              />
            ))}
        </div>
      )}
      <ul className="legend">
        {parts.map((p) => (
          <li key={p.key} className={p.value === 0 ? "off" : ""}>
            <span className={`key ${p.key}`} />
            {p.label}
            <span className="num">{p.value}</span>
          </li>
        ))}
      </ul>
    </Figure>
  );
}

/** Who did the work: one row per agent, named beside its bar, busiest first. */
export function RoleLoadChart({ roles }: { roles: RoleWork[] }) {
  const tx = useT();
  const rows = roles.filter((r) => r.runs > 0);
  const max = Math.max(1, ...rows.map((r) => r.runs));
  const total = rows.reduce((sum, r) => sum + r.runs, 0);
  return (
    <Figure
      title={tx("Who did the work")}
      lead={
        <>
          <strong>{total}</strong> {tx("steps")}
        </>
      }
      table={{
        head: [tx("Agent"), tx("steps")],
        rows: rows.map((r) => [tx(r.label), r.runs]),
      }}
    >
      {rows.length === 0 ? (
        <div className="muted small">{tx("Nothing has happened yet.")}</div>
      ) : (
        <ul className="barlist">
          {rows.map((r) => (
            <li key={r.role} title={r.last_used ? timeAgo(r.last_used) : undefined}>
              <span className="name truncate">
                {/* the role's own hue on its glyph, as on its card; the bar stays one
                    colour, because there the length is what carries the number */}
                <span className="role-ink" data-agent={r.role}>
                  <AgentIcon role={r.role} />
                </span>
                {tx(r.label)}
              </span>
              <span className="track">
                <span className="fill" style={{ width: `${(r.runs / max) * 100}%` }} />
              </span>
              <span className="num">{r.runs}</span>
            </li>
          ))}
        </ul>
      )}
    </Figure>
  );
}
