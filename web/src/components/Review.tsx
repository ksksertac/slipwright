// The standards review (T9.5) as people read it: a findings table, and the review
import { useT } from "../i18n";
// record a history entry carries as JSON rendered through it.
export interface ReviewRecord {
  phase: number;
  round: number;
  mode: string;
  summary?: string;
  violations: {
    section: string;
    file: string;
    line?: number | null;
    severity: "blocking" | "advisory";
    message: string;
    fix?: string;
  }[];
  blocking: number;
  advisory: number;
  verdict: string;
}

export function ViolationsTable({ violations }: { violations: ReviewRecord["violations"] }) {
  const tx = useT();
  if (violations.length === 0) return <div className="muted small">{tx("No findings.")}</div>;
  return (
    <table className="violations">
      <thead>
        <tr>
          <th>{tx("Severity")}</th>
          <th>{tx("Section")}</th>
          <th>{tx("Where")}</th>
          <th>{tx("Finding")}</th>
        </tr>
      </thead>
      <tbody>
        {violations.map((v, i) => (
          <tr key={i}>
            <td>
              <span className={`badge plain ${v.severity === "blocking" ? "bad" : "work"}`}>
                {v.severity}
              </span>
            </td>
            <td>{v.section}</td>
            <td className="mono small">
              {v.file}
              {v.line ? `:${v.line}` : ""}
            </td>
            <td>
              {v.message}
              {v.fix && <div className="muted small">fix: {v.fix}</div>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A review record (JSON in the history detail) as a findings table. */
export function ReviewDetail({ text }: { text: string }) {
  let record: ReviewRecord | null = null;
  try {
    record = JSON.parse(text) as ReviewRecord;
  } catch {
    record = null;
  }
  if (!record) return <pre>{text}</pre>;
  return (
    <div>
      {record.summary && <p className="small">{record.summary}</p>}
      <ViolationsTable violations={record.violations} />
    </div>
  );
}
