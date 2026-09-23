// A history entry's long-form detail, laid out as what it is: a diff, the backlog tree,
// the plan's decisions and phases, the list of test cases, a review record. JSON is the
// fallback, not the default — and the raw record stays one click away under every layout.
import type { ReactNode } from "react";
import { Diff, looksLikeDiff } from "./Diff";
import { useT, type T } from "../i18n";
import { Copyable } from "./Copyable";
import { BreakdownTree, type BreakdownShape, type PlanShape } from "./Breakdown";
import { ViolationsTable, type ReviewRecord } from "./Review";
import { DomainBadge } from "./agents";

type Dict = Record<string, unknown>;

const isDict = (v: unknown): v is Dict => typeof v === "object" && v !== null && !Array.isArray(v);
const isStringList = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string");
const isDictList = (v: unknown): v is Dict[] => Array.isArray(v) && v.every(isDict);
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

interface CaseShape {
  name?: string;
  description?: string;
}

function parseJson(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return undefined;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return undefined;
  }
}

export function Detail({ text }: { text: string | null | undefined }) {
  const tx = useT();
  if (!text) return <span className="muted">{tx("no detail")}</span>;
  if (looksLikeDiff(text))
    return (
      <Copyable text={text}>
        <Diff text={text} />
      </Copyable>
    );
  const value = parseJson(text);
  if (value === undefined)
    return (
      <Copyable text={text}>
        <pre>{text}</pre>
      </Copyable>
    );
  const pretty = JSON.stringify(value, null, 2);
  const blocks = layout(value, tx);
  if (blocks.length === 0)
    return (
      <Copyable text={pretty}>
        <pre>{pretty}</pre>
      </Copyable>
    );
  return (
    <div className="detail">
      {blocks}
      <details className="raw">
        <summary>{tx("the record as JSON")}</summary>
        <Copyable text={pretty}>
          <pre>{pretty}</pre>
        </Copyable>
      </details>
    </div>
  );
}

/** The parts of a record we know how to lay out, in reading order; empty when none. */
function layout(value: unknown, tx: T): ReactNode[] {
  // stage-one QA details written before the summary moved in are a bare array of cases
  if (isDictList(value) && value.length > 0 && value.every((c) => typeof c.name === "string"))
    return [<CaseList key="cases" cases={value as CaseShape[]} title={tx("Test cases")} />];
  if (!isDict(value)) return [];

  if (isDictList(value.violations) && typeof value.verdict === "string") {
    const record = value as unknown as ReviewRecord;
    return [
      record.summary ? <p key="summary">{record.summary}</p> : null,
      <ViolationsTable key="violations" violations={record.violations} />,
    ].filter(Boolean);
  }

  const out: ReactNode[] = [];
  const summary = str(value.summary)?.trim();
  if (summary)
    out.push(
      <p key="summary" className="lead">
        {summary}
      </p>,
    );

  if (isStringList(value.decisions) && value.decisions.length > 0)
    out.push(
      <section key="decisions">
        <h4>{tx("Decisions")}</h4>
        <ul>
          {value.decisions.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      </section>,
    );

  const breakdown = asBreakdown(value);
  const phases: PlanShape["phases"] = (isDictList(value.phases) ? value.phases : []).map((p) => ({
    goal: str(p.goal) ?? "",
    domain: str(p.domain),
    files: isStringList(p.files) ? p.files : undefined,
  }));
  if (breakdown)
    out.push(
      <section key="backlog">
        <h4>{tx("Backlog")}</h4>
        <BreakdownTree plan={{ phases, breakdown }} />
      </section>,
    );
  else if (phases.length > 0)
    out.push(
      <section key="phases">
        <h4>{tx("Phases")}</h4>
        <ol className="phases">
          {phases.map((p, i) => (
            <li key={i}>
              {p.goal} <DomainBadge domain={p.domain} />
              {p.files && p.files.length > 0 && (
                <span className="muted small mono"> — {p.files.join(", ")}</span>
              )}
            </li>
          ))}
        </ol>
      </section>,
    );

  if (isDictList(value.test_cases) && value.test_cases.length > 0)
    out.push(
      <CaseList key="cases" cases={value.test_cases as CaseShape[]} title={tx("Test cases")} />,
    );
  return out;
}

/** The backlog, whether it is the record itself or the plan's copy of it. */
function asBreakdown(value: Dict): BreakdownShape | null {
  const nested = isDict(value.breakdown) ? value.breakdown.epics : undefined;
  const epics = isDictList(value.epics) ? value.epics : isDictList(nested) ? nested : null;
  return epics && epics.length > 0 ? ({ epics } as unknown as BreakdownShape) : null;
}

function CaseList({ cases, title }: { cases: CaseShape[]; title: string }) {
  return (
    <section>
      <h4>{title}</h4>
      <ol className="cases">
        {cases.map((c, i) => (
          <li key={i}>
            <strong>{c.name}</strong>
            {c.description && <div className="muted small">{c.description}</div>}
          </li>
        ))}
      </ol>
    </section>
  );
}
