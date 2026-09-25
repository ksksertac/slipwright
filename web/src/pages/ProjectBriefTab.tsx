// What the agents are told the project is (T11.1-T11.3). Two ways in, one list: a
// repository with code is read by the Architect, an empty one is asked about by the
// Product Owner. Either way the person edits the lines and approves them — nothing here
// reaches an agent until they do.
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  describeError,
  type BriefCategory,
  type BriefItem,
  type BriefView,
  type IntakeQuestion,
} from "../api/client";
import { useAnalyseProject, useBrief, useIntake, useProject, useSaveBrief } from "../api/hooks";
import { IconEdit, IconPlus, IconTrash } from "../components/icons";
import { useToast } from "../components/Toast";
import { ErrorBox, Loading } from "../components/ui";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";

/** A brief line with nothing optional: what the editor works on. */
type Row = {
  id: string;
  category: BriefCategory;
  title: string;
  detail: string;
  source: NonNullable<BriefItem["source"]>;
};

function toRow(item: BriefItem, index: number): Row {
  return {
    id: item.id ?? `row-${index}`,
    category: item.category ?? "architecture",
    title: item.title,
    detail: item.detail ?? "",
    source: item.source ?? "analysis",
  };
}

const CATEGORIES: BriefCategory[] = [
  "product",
  "stack",
  "architecture",
  "modules",
  "conventions",
  "testing",
  "deployment",
  "risks",
];

export function ProjectBriefTab({ projectId }: { projectId: string }) {
  const tx = useT();
  const project = useProject(projectId);
  const brief = useBrief(projectId, true);

  if (brief.isLoading || project.isLoading) return <Loading />;
  if (brief.error) return <ErrorBox error={brief.error} />;
  if (!brief.data || !project.data) return null;
  const view = brief.data;

  return (
    <div className="stack">
      <div className="card">
        <h2 style={{ marginTop: 0 }}>{tx("What the agents know about this project")}</h2>
        <p className="muted small" style={{ marginBottom: 0 }}>
          {view.kind === "analysis"
            ? tx(
                "The Architect reads the checkout and writes down what this project is. Every agent is handed this list at every step, so strike out anything wrong and correct anything half-right before you approve it.",
              )
            : tx(
                "The repository is empty, so the Product Owner asks you about the product. Your answers become the first development and the list below, which every agent is handed at every step.",
              )}
        </p>
      </div>

      {view.kind === "intake" && !view.brief.intake?.done ? (
        <IntakePanel projectId={projectId} view={view} />
      ) : (
        <BriefEditor projectId={projectId} view={view} />
      )}
    </div>
  );
}

// -- the analysis / the list ---------------------------------------------------------------

function BriefEditor({ projectId, view }: { projectId: string; view: BriefView }) {
  const tx = useT();
  const say = useSay();
  const toast = useToast();
  const navigate = useNavigate();
  const analyse = useAnalyseProject(projectId);
  const save = useSaveBrief(projectId);
  const running = view.brief.state === "running";
  const [items, setItems] = useState<Row[]>(view.brief.items.map(toRow));
  const [touched, setTouched] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);

  // follow the server until the person starts editing: an analysis lands while they are
  // watching it, and the list has to appear (state adjusted during render, no effects)
  const serverItems = view.brief.items;
  const [seen, setSeen] = useState(serverItems);
  if (seen !== serverItems) {
    setSeen(serverItems);
    if (!touched) setItems(serverItems.map(toRow));
  }

  const grouped = useMemo(() => {
    const out = new Map<BriefCategory, Row[]>();
    for (const item of items) out.set(item.category, [...(out.get(item.category) ?? []), item]);
    return [...out.entries()];
  }, [items]);

  const change = (id: string, patch: Partial<Row>) => {
    setTouched(true);
    setItems((old) => old.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  };
  const remove = (id: string) => {
    setTouched(true);
    setItems((old) => old.filter((i) => i.id !== id));
  };
  const add = () => {
    setTouched(true);
    const id = `new-${Date.now()}`;
    setItems((old) => [
      ...old,
      { id, category: "architecture", title: "", detail: "", source: "human" },
    ]);
    setEditing(id);
  };

  const approve = () =>
    save.mutate(
      { items: items.filter((i) => i.title.trim() !== ""), approve: true },
      {
        onSuccess: () => {
          setTouched(false);
          toast.ok(tx("Saved — the agents read this from now on"));
          navigate(`/projects/${projectId}/developments`);
        },
      },
    );

  if (view.brief.state === "empty" && !running) {
    return (
      <div className="card empty" style={{ padding: 32, textAlign: "center" }}>
        <p>{tx("Nothing has been written down yet.")}</p>
        <button
          className="btn primary"
          disabled={analyse.isPending}
          onClick={() => analyse.mutate()}
        >
          {analyse.isPending ? tx("Reading the repository…") : tx("Analyse the repository")}
        </button>
        {analyse.error && <p className="bad small">{describeError(analyse.error)}</p>}
      </div>
    );
  }

  return (
    <div className="stack">
      {running && <div className="card muted">{tx("Reading the repository…")}</div>}
      {view.brief.state === "failed" && (
        <div className="card">
          <p className="bad">{view.brief.error}</p>
          <button className="btn" onClick={() => analyse.mutate()}>
            {tx("Try again")}
          </button>
        </div>
      )}
      {view.brief.summary && !running && (
        <div className="card">
          <p style={{ margin: 0 }}>{say(view.brief.summary)}</p>
        </div>
      )}

      <div className="card">
        <div className="row spread">
          <strong>
            {tx("Project brief")} <span className="badge">{items.length}</span>
          </strong>
          <div className="row">
            <button className="btn ghost" onClick={add}>
              <IconPlus /> {tx("Add a line")}
            </button>
            {view.brief.state !== "empty" && (
              <button className="btn ghost" disabled={running} onClick={() => analyse.mutate()}>
                {tx("Analyse again")}
              </button>
            )}
          </div>
        </div>
        {items.length === 0 ? (
          <div className="empty" style={{ padding: 24 }}>
            <div className="small">{tx("No lines yet.")}</div>
          </div>
        ) : (
          grouped.map(([category, rows]) => (
            <section key={category} style={{ marginTop: 16 }}>
              <div className="faint small">{tx(category)}</div>
              <ul className="rules">
                {rows.map((item) =>
                  editing === item.id ? (
                    <li key={item.id} className="rule">
                      <ItemEditor
                        item={item}
                        onChange={(patch) => change(item.id, patch)}
                        onDone={() => setEditing(null)}
                      />
                    </li>
                  ) : (
                    <li key={item.id} className="rule">
                      <div className="rule-body">
                        <strong>{say(item.title)}</strong>
                        {item.detail && <p className="muted small">{say(item.detail)}</p>}
                      </div>
                      <div className="rule-actions">
                        <button
                          className="btn ghost icon"
                          title={tx("Edit")}
                          aria-label={tx("Edit")}
                          onClick={() => setEditing(item.id)}
                        >
                          <IconEdit />
                        </button>
                        <button
                          className="btn ghost icon danger"
                          title={tx("Delete")}
                          aria-label={tx("Delete")}
                          onClick={() => remove(item.id)}
                        >
                          <IconTrash />
                        </button>
                      </div>
                    </li>
                  ),
                )}
              </ul>
            </section>
          ))
        )}
      </div>

      <div className="card row spread">
        <div className="small muted">
          {view.brief.state === "ready"
            ? tx("Approved — every agent reads this.")
            : tx("Not approved yet: the agents are told nothing until you approve it.")}
        </div>
        <div className="row">
          <button
            className="btn"
            disabled={save.isPending || !touched}
            onClick={() =>
              save.mutate(
                { items: items.filter((i) => i.title.trim() !== ""), approve: false },
                {
                  onSuccess: () => {
                    setTouched(false);
                    toast.ok(tx("Saved"));
                  },
                },
              )
            }
          >
            {tx("Save draft")}
          </button>
          <button
            className="btn primary"
            disabled={save.isPending || items.length === 0}
            onClick={approve}
          >
            {tx("Approve and continue")}
          </button>
        </div>
      </div>
      {save.error && <ErrorBox error={save.error} />}
    </div>
  );
}

function ItemEditor({
  item,
  onChange,
  onDone,
}: {
  item: Row;
  onChange: (patch: Partial<Row>) => void;
  onDone: () => void;
}) {
  const tx = useT();
  return (
    <div className="form" style={{ width: "100%" }}>
      <div className="field">
        <label>{tx("Category")}</label>
        <select
          value={item.category}
          onChange={(e) => onChange({ category: e.target.value as BriefCategory })}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {tx(c)}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>{tx("Title")}</label>
        <input
          type="text"
          autoFocus
          value={item.title}
          onChange={(e) => onChange({ title: e.target.value })}
        />
      </div>
      <div className="field">
        <label>{tx("Detail")}</label>
        <textarea value={item.detail} onChange={(e) => onChange({ detail: e.target.value })} />
      </div>
      <div className="row">
        <button className="btn" onClick={onDone}>
          {tx("Done")}
        </button>
      </div>
    </div>
  );
}

// -- the intake ------------------------------------------------------------------------------

function IntakePanel({ projectId, view }: { projectId: string; view: BriefView }) {
  const tx = useT();
  const say = useSay();
  const intake = useIntake(projectId);
  const running = view.brief.state === "running";
  const rounds = view.brief.intake?.rounds ?? [];
  const current = rounds.length > 0 ? (rounds[rounds.length - 1] ?? null) : null;
  const [answers, setAnswers] = useState<Record<string, string>>({});

  // a new round is a new form (state adjusted during render, no effects)
  const [round, setRound] = useState(current?.number ?? 0);
  if (round !== (current?.number ?? 0)) {
    setRound(current?.number ?? 0);
    setAnswers({});
  }

  if (running || (!current && intake.isPending)) {
    return <div className="card muted">{tx("The Product Owner is reading your answers…")}</div>;
  }

  if (!current) {
    return (
      <div className="card empty" style={{ padding: 32, textAlign: "center" }}>
        <p>{tx("Tell the agents what you are building and they will start from there.")}</p>
        <button className="btn primary" onClick={() => intake.mutate({})}>
          {tx("Start")}
        </button>
        {intake.error && <p className="bad small">{describeError(intake.error)}</p>}
      </div>
    );
  }

  const answered = current.questions.every((q) => (answers[q.id] ?? "").trim() !== "");
  const max = view.brief.intake?.max_rounds ?? 3;

  return (
    <div className="stack">
      {view.brief.summary && (
        <div className="card">
          <p style={{ margin: 0 }}>{say(view.brief.summary)}</p>
        </div>
      )}
      <div className="card">
        <div className="row spread">
          <strong>{tx("A few questions")}</strong>
          <span className="faint small">
            {tx("round {n} of {max}", { n: current.number, max })}
          </span>
        </div>
        <div className="form" style={{ marginTop: 12 }}>
          {current.questions.map((q: IntakeQuestion) => (
            <div className="field" key={q.id}>
              <label htmlFor={`q-${q.id}`}>{say(q.question)}</label>
              {q.why && <div className="faint small">{say(q.why)}</div>}
              <textarea
                id={`q-${q.id}`}
                rows={2}
                placeholder={q.hint ? say(q.hint) : ""}
                value={answers[q.id] ?? ""}
                onChange={(e) => setAnswers((old) => ({ ...old, [q.id]: e.target.value }))}
              />
            </div>
          ))}
          <div className="row">
            <button
              className="btn primary"
              disabled={!answered || intake.isPending}
              onClick={() => intake.mutate(answers)}
            >
              {tx("Send the answers")}
            </button>
          </div>
        </div>
      </div>
      {rounds.length > 1 && (
        <details className="card">
          <summary>
            <strong>{tx("What you answered before")}</strong>
          </summary>
          <div className="stack" style={{ marginTop: 12 }}>
            {rounds.slice(0, -1).map((r) => (
              <div key={r.number}>
                {r.questions.map((q) => (
                  <p key={q.id} className="small">
                    <strong>{say(q.question)}</strong>
                    <br />
                    {q.answer}
                  </p>
                ))}
              </div>
            ))}
          </div>
        </details>
      )}
      {intake.error && <ErrorBox error={intake.error} />}
    </div>
  );
}
