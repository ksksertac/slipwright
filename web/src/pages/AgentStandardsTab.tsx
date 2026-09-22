// An agent's Standards tab (T9.6): one flat list of rules — what this agent does and
// watches out for — each added, edited or removed on its own, in any language. A rule is
// one "##" section of the domain's Markdown; the pages, the linter, the index and the
// review branch stay behind the API. The shared (core) rules every agent reads are the
// same rows in a collapsed group; the retrieval tools (search test, index settings) sit
// under "Advanced" at the bottom.
import { useState, type ReactNode } from "react";
import { describeError, type StandardsRule } from "../api/client";
import {
  useCreateStandardsRule,
  useDeleteStandardsRule,
  useProjects,
  useReindexStandards,
  useSaveStandardsRule,
  useSaveStandardsSettings,
  useStandardsRules,
  useStandardsSearch,
  useStandardsStatus,
} from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { IconEdit, IconPlus, IconSearch, IconTrash } from "../components/icons";
import { ConfirmModal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { ErrorBox, Loading } from "../components/ui";
import { useT } from "../i18n";

const DOMAINS = ["product", "architecture", "backend", "web", "mobile", "testing", "devops"];

export function AgentStandardsTab({ role, domain }: { role: string; domain: string }) {
  const tx = useT();
  const projects = useProjects();
  const status = useStandardsStatus();
  const { user } = useAuth();
  const admin = !!user?.is_admin;
  const [projectId, setProjectId] = useState<string | null>(null); // null = every project
  const [pick, setPick] = useState(domain === "*" ? "backend" : domain);
  const listDomain = domain === "*" ? pick : domain;
  const [adding, setAdding] = useState(false);
  const topK = status.data?.settings.top_k;

  return (
    <div className="stack">
      <div className="card">
        <div className="row spread" style={{ flexWrap: "wrap" }}>
          <div className="row" style={{ gap: 10 }}>
            <label className="small muted" htmlFor="std-scope">
              {tx("Scope")}
            </label>
            <select
              id="std-scope"
              value={projectId ?? ""}
              onChange={(e) => {
                setProjectId(e.target.value || null);
                setAdding(false);
              }}
            >
              <option value="">{tx("every project")}</option>
              {(projects.data ?? [])
                .filter((p) => p.repo_path)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {tx("only {name}", { name: p.name })}
                  </option>
                ))}
            </select>
            {domain === "*" && (
              <select value={pick} onChange={(e) => setPick(e.target.value)}>
                {DOMAINS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            )}
          </div>
          {admin && (
            <button className="btn primary small" onClick={() => setAdding(true)}>
              <IconPlus /> {tx("Add rule")}
            </button>
          )}
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>
          {topK
            ? tx(
                "At each step the {role} agent reads the rules below that best match its task (up to {k}), plus the shared rules. Write them in any language — the model reads it.",
                { role, k: topK },
              )
            : tx(
                "At each step the {role} agent reads the rules below that best match its task, plus the shared rules. Write them in any language — the model reads it.",
                { role },
              )}
          {projectId
            ? ` ${tx("Rules in this scope apply to that project only and win over the shared list.")}`
            : ""}
        </p>
      </div>

      <RuleList
        projectId={projectId}
        domain={listDomain}
        admin={admin}
        adding={adding}
        onAddDone={() => setAdding(false)}
        title={tx("Rules")}
        empty={
          projectId
            ? tx("No project-specific rules yet — a rule added here applies to that project only.")
            : tx("No rules yet. Add the first one.")
        }
      />

      <details className="card">
        <summary>
          <strong>{tx("Shared rules — every agent")}</strong>{" "}
          <span className="muted small">
            {tx("Read in full by every agent on every project; a rule above never overrides them.")}
          </span>
        </summary>
        <div style={{ marginTop: 12 }}>
          {projectId ? (
            <p className="muted small">
              {tx("Shared rules are edited under the every-project scope.")}
            </p>
          ) : null}
          <RuleList
            projectId={null}
            domain="core"
            admin={admin && !projectId}
            adding={false}
            onAddDone={() => undefined}
            empty={tx("No shared rules.")}
            flush
          />
        </div>
      </details>

      <details className="card">
        <summary>
          <strong>{tx("Advanced — search test and index")}</strong>
        </summary>
        <div className="stack" style={{ marginTop: 12 }}>
          <TrySearch projectId={projectId} domain={listDomain} />
          <IndexSettings admin={admin} projectId={projectId} />
        </div>
      </details>
    </div>
  );
}

// -- the list ---------------------------------------------------------------------------------

function RuleList({
  projectId,
  domain,
  admin,
  adding,
  onAddDone,
  title,
  empty,
  flush = false,
}: {
  projectId: string | null;
  domain: string;
  admin: boolean;
  adding: boolean;
  onAddDone: () => void;
  title?: string;
  empty: string;
  flush?: boolean;
}) {
  const tx = useT();
  const rules = useStandardsRules(projectId, domain);
  const create = useCreateStandardsRule(projectId);
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<StandardsRule | null>(null);

  if (rules.isLoading) return <Loading />;
  if (rules.error) return <ErrorBox error={rules.error} />;
  const items = rules.data ?? [];
  const inner = (
    <>
      {adding && (
        <RuleEditor
          heading=""
          text=""
          busy={create.isPending}
          error={create.error ? describeError(create.error) : null}
          onCancel={onAddDone}
          onSave={(heading, text) =>
            create.mutate(
              { domain, heading, text },
              {
                onSuccess: () => {
                  toast.ok(tx("Rule added"));
                  onAddDone();
                },
              },
            )
          }
        />
      )}
      {items.length === 0 && !adding ? (
        <div className="empty" style={{ padding: 24 }}>
          <div className="small">{empty}</div>
        </div>
      ) : (
        <ul className="rules">
          {items.map((r) =>
            editing === r.id ? (
              <li key={r.id} className="rule">
                <EditRow projectId={projectId} rule={r} onDone={() => setEditing(null)} />
              </li>
            ) : (
              <li key={r.id} className="rule">
                <div className="rule-body">
                  <strong>{r.heading}</strong>
                  <Markdown text={r.text} />
                </div>
                {admin && (
                  <div className="rule-actions">
                    <button
                      className="btn ghost icon"
                      title={tx("Edit")}
                      aria-label={tx("Edit")}
                      onClick={() => setEditing(r.id)}
                    >
                      <IconEdit />
                    </button>
                    <button
                      className="btn ghost icon"
                      title={tx("Delete")}
                      aria-label={tx("Delete")}
                      onClick={() => setDeleting(r)}
                    >
                      <IconTrash />
                    </button>
                  </div>
                )}
              </li>
            ),
          )}
        </ul>
      )}
      {deleting && (
        <DeleteRule projectId={projectId} rule={deleting} onClose={() => setDeleting(null)} />
      )}
    </>
  );
  if (flush) return inner;
  return (
    <div className="card flush">
      <div className="card-head">
        <h3>
          {title} <span className="badge plain">{items.length}</span>
        </h3>
      </div>
      <div className="card-body">{inner}</div>
    </div>
  );
}

function EditRow({
  projectId,
  rule,
  onDone,
}: {
  projectId: string | null;
  rule: StandardsRule;
  onDone: () => void;
}) {
  const tx = useT();
  const save = useSaveStandardsRule(projectId);
  const toast = useToast();
  return (
    <RuleEditor
      heading={rule.heading}
      text={rule.text}
      busy={save.isPending}
      error={save.error ? describeError(save.error) : null}
      onCancel={onDone}
      onSave={(heading, text) =>
        save.mutate(
          { id: rule.id, heading, text },
          {
            onSuccess: () => {
              toast.ok(tx("Rule saved"));
              onDone();
            },
          },
        )
      }
    />
  );
}

function DeleteRule({
  projectId,
  rule,
  onClose,
}: {
  projectId: string | null;
  rule: StandardsRule;
  onClose: () => void;
}) {
  const tx = useT();
  const remove = useDeleteStandardsRule(projectId);
  const toast = useToast();
  return (
    <ConfirmModal
      title={tx("Delete rule")}
      body={tx("Delete “{heading}”? It stops reaching the agent as soon as the index refreshes.", {
        heading: rule.heading,
      })}
      confirmLabel={tx("Delete")}
      busy={remove.isPending}
      error={remove.error ? describeError(remove.error) : null}
      onClose={onClose}
      onConfirm={() =>
        remove.mutate(rule.id, {
          onSuccess: () => {
            toast.ok(tx("Rule deleted"));
            onClose();
          },
        })
      }
    />
  );
}

// -- one rule's form (add and edit share it) ------------------------------------------------

function RuleEditor({
  heading: initialHeading,
  text: initialText,
  busy,
  error,
  onSave,
  onCancel,
}: {
  heading: string;
  text: string;
  busy: boolean;
  error: string | null;
  onSave: (heading: string, text: string) => void;
  onCancel: () => void;
}) {
  const tx = useT();
  const [heading, setHeading] = useState(initialHeading);
  const [text, setText] = useState(initialText);
  const ready = heading.trim().length > 0 && text.trim().length > 0;
  return (
    <form
      className="rule-editor"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !busy) onSave(heading.trim(), text.trim());
      }}
    >
      <input
        type="text"
        value={heading}
        autoFocus
        placeholder={tx("Rule title — e.g. Every story has an acceptance criterion")}
        onChange={(e) => setHeading(e.target.value)}
      />
      <textarea
        value={text}
        spellCheck={false}
        placeholder={tx(
          "What the agent must do or watch out for, and why. Markdown is fine; keep it under 400 words.",
        )}
        onChange={(e) => setText(e.target.value)}
        style={{ minHeight: 120 }}
      />
      {error && <div className="callout error">{error}</div>}
      <div className="row">
        <button className="btn primary small" type="submit" disabled={!ready || busy}>
          {busy ? tx("Saving…") : tx("Save")}
        </button>
        <button className="btn small" type="button" onClick={onCancel} disabled={busy}>
          {tx("Cancel")}
        </button>
      </div>
    </form>
  );
}

// -- try a search --------------------------------------------------------------------------

function TrySearch({ projectId, domain }: { projectId: string | null; domain: string }) {
  const tx = useT();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [d, setD] = useState(domain);
  const hits = useStandardsSearch(projectId, d, q);
  return (
    <div>
      <h3>{tx("Try a search")}</h3>
      <p className="muted small">
        {tx(
          "Type a task the way a phase goal reads and see which rules the agent would be given, ranked.",
        )}
      </p>
      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          setQ(text.trim());
        }}
      >
        <input
          type="text"
          style={{ flex: "1 1 240px", width: "auto" }}
          placeholder={tx("e.g. add a Kafka consumer that retries failed messages")}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <select value={d} onChange={(e) => setD(e.target.value)} style={{ width: 160 }}>
          {DOMAINS.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
          <option value="*">{tx("all domains")}</option>
        </select>
        <button className="btn small" disabled={!text.trim()}>
          <IconSearch /> {tx("Search")}
        </button>
      </form>
      {hits.isFetching && <Loading rows={2} />}
      {hits.error && <ErrorBox error={hits.error} />}
      {hits.data && hits.data.length === 0 && (
        <div className="muted small" style={{ marginTop: 8 }}>
          {tx("Nothing matched; the agent would get the domain's opening rules instead.")}
        </div>
      )}
      {hits.data && hits.data.length > 0 && (
        <ol className="hits">
          {hits.data.map((h) => (
            <li key={h.id}>
              <details>
                <summary>
                  <strong>{h.heading}</strong>{" "}
                  <span className="mono small muted">
                    {h.page} · {h.scope} · score {h.score.toFixed(3)} (kw {h.keyword.toFixed(2)},
                    sem {h.semantic.toFixed(2)})
                  </span>
                </summary>
                <Markdown text={h.text} />
              </details>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// -- index settings --------------------------------------------------------------------------

function IndexSettings({ admin, projectId }: { admin: boolean; projectId: string | null }) {
  const tx = useT();
  const status = useStandardsStatus();
  const save = useSaveStandardsSettings();
  const reindex = useReindexStandards();
  const toast = useToast();
  const [draft, setDraft] = useState<{
    embedder: string;
    embedding_model: string;
    local_model: string;
    top_k: number;
    token_budget: number;
  } | null>(null);
  if (status.isLoading) return <Loading rows={2} />;
  if (status.error) return <ErrorBox error={status.error} />;
  if (!status.data) return null;
  const s = status.data;
  const form = draft ?? s.settings;
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(s.settings);
  const per = Object.entries(s.per_domain)
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");
  return (
    <div>
      <div className="row spread">
        <h3>{tx("Index")}</h3>
        {admin && (
          <button
            className="btn small"
            disabled={reindex.isPending}
            onClick={() =>
              reindex.mutate(projectId, {
                onSuccess: (r) => toast.ok(`Reindexed: ${r.chunks} sections`),
                onError: (e) => toast.bad(describeError(e)),
              })
            }
          >
            {reindex.isPending ? tx("Reindexing…") : tx("Reindex now")}
          </button>
        )}
      </div>
      <div className="muted small">
        {s.chunks} sections indexed, {s.embedded} with embeddings ({s.settings.embedder}
        {s.settings.embedder === "openai"
          ? ` · ${s.settings.embedding_model}`
          : s.settings.embedder === "local"
            ? ` · ${s.settings.local_model}`
            : ""}
        ) · {per}
      </div>
      <div className="grid-2" style={{ marginTop: 10 }}>
        <Field label={tx("Embedder")}>
          <select
            value={form.embedder}
            disabled={!admin}
            onChange={(e) => setDraft({ ...form, embedder: e.target.value })}
          >
            <option value="none">{tx("none — keyword search only")}</option>
            <option value="openai">{tx("openai — text embeddings (needs an OpenAI key)")}</option>
            <option value="local">{tx("local — sentence-transformers on this machine")}</option>
            <option value="hashing">{tx("hashing — offline stand-in")}</option>
          </select>
        </Field>
        {form.embedder === "openai" && (
          <Field label={tx("Embedding model")}>
            <input
              type="text"
              className="mono"
              value={form.embedding_model}
              disabled={!admin}
              onChange={(e) => setDraft({ ...form, embedding_model: e.target.value })}
            />
          </Field>
        )}
        {form.embedder === "local" && (
          <Field label={tx("Local model")}>
            <input
              type="text"
              className="mono"
              value={form.local_model}
              disabled={!admin}
              onChange={(e) => setDraft({ ...form, local_model: e.target.value })}
            />
          </Field>
        )}
        <Field label={tx("Sections per role (top k)")}>
          <input
            type="number"
            min={1}
            max={20}
            value={form.top_k}
            disabled={!admin}
            onChange={(e) => setDraft({ ...form, top_k: Number(e.target.value) })}
          />
        </Field>
        <Field label={tx("Token budget per prompt")}>
          <input
            type="number"
            min={200}
            max={20000}
            step={100}
            value={form.token_budget}
            disabled={!admin}
            onChange={(e) => setDraft({ ...form, token_budget: Number(e.target.value) })}
          />
        </Field>
      </div>
      {admin && (
        <div className="row" style={{ marginTop: 10 }}>
          <button
            className="btn primary small"
            disabled={!dirty || save.isPending}
            onClick={() =>
              save.mutate(form, {
                onSuccess: () => {
                  toast.ok("Index settings saved; reindex to apply a new embedder");
                  setDraft(null);
                },
              })
            }
          >
            {save.isPending ? tx("Saving…") : tx("Save settings")}
          </button>
          {save.error && <span className="error small">{describeError(save.error)}</span>}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
    </div>
  );
}

// -- a small Markdown renderer (headings, lists, paragraphs, inline code) ---------------------

export function Markdown({ text }: { text: string }) {
  const body = text.replace(/^---[\s\S]*?---\s*/, ""); // front-matter is not content
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) {
      blocks.push(<p key={blocks.length}>{inline(para.join(" "))}</p>);
      para = [];
    }
    if (list.length) {
      blocks.push(
        <ul key={blocks.length}>
          {list.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      list = [];
    }
  };
  for (const raw of body.split("\n")) {
    const line = raw.trimEnd();
    if (/^#{1,3} /.test(line)) {
      flush();
      const level = line.indexOf(" ");
      const content = inline(line.slice(level + 1));
      blocks.push(
        level === 1 ? (
          <h2 key={blocks.length}>{content}</h2>
        ) : level === 2 ? (
          <h3 key={blocks.length}>{content}</h3>
        ) : (
          <h4 key={blocks.length}>{content}</h4>
        ),
      );
    } else if (/^[-*] /.test(line)) {
      if (para.length) flush();
      list.push(line.slice(2));
    } else if (line === "") {
      flush();
    } else {
      if (list.length) flush();
      para.push(line);
    }
  }
  flush();
  return <div className="markdown">{blocks}</div>;
}

function inline(text: string): ReactNode {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    if (part.startsWith("**") && part.endsWith("**"))
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    return part;
  });
}
