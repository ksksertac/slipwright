// An agent's Standards tab (T9.6): the pages of its domain, editable in place with a
// preview; the core rules every agent reads; a search box that ranks sections the way
// the agents' retrieval does; and the index settings (embedder, budget, reindex).
import { useMemo, useState, type ReactNode } from "react";
import { describeError, type StandardsPage } from "../api/client";
import {
  useCreateStandardsPage,
  useDeleteStandardsPage,
  useProjects,
  useReindexStandards,
  useSaveStandardsPage,
  useSaveStandardsSettings,
  useStandardsPage,
  useStandardsPages,
  useStandardsSearch,
  useStandardsStatus,
} from "../api/hooks";
import { useAuth } from "../auth/AuthProvider";
import { IconPlus, IconSearch, IconTrash } from "../components/icons";
import { ConfirmModal, Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { ErrorBox, Loading, timeAgo } from "../components/ui";
import { useT } from "../i18n";

const DOMAINS = ["product", "architecture", "backend", "web", "mobile", "testing", "devops"];

export function AgentStandardsTab({ role, domain }: { role: string; domain: string }) {
  const tx = useT();
  const projects = useProjects();
  const { user } = useAuth();
  const admin = !!user?.is_admin;
  const [projectId, setProjectId] = useState<string | null>(null); // null = global corpus
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState("");
  const [searchDomain, setSearchDomain] = useState(domain === "*" ? "backend" : domain);
  const listDomain = domain === "*" ? searchDomain : domain;
  const pages = useStandardsPages(projectId, listDomain);

  const visible = useMemo(() => {
    const all = pages.data ?? [];
    const q = filter.trim().toLowerCase();
    return all
      .filter((p) => p.domain !== "core")
      .filter((p) => !q || p.title.toLowerCase().includes(q) || p.path.includes(q));
  }, [pages.data, filter]);
  const core = (pages.data ?? []).find((p) => p.path === "core.md");

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
                setOpen(null);
              }}
            >
              <option value="">global corpus (every project)</option>
              {(projects.data ?? [])
                .filter((p) => p.repo_path)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    override for {p.name}
                  </option>
                ))}
            </select>
            {domain === "*" && (
              <select value={searchDomain} onChange={(e) => setSearchDomain(e.target.value)}>
                {DOMAINS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="row">
            <input
              type="search"
              placeholder={tx("filter pages")}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{ width: 200 }}
            />
            {admin && (
              <button className="btn primary small" onClick={() => setCreating(true)}>
                <IconPlus /> {tx("New page")}
              </button>
            )}
          </div>
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>
          The {role} agent reads the <code>{listDomain}</code> standards
          {projectId ? " — this project's overrides take precedence over the global pages" : ""}.
          Retrieval picks the sections that match each phase; the core rules below are always in the
          prompt.
        </p>
      </div>

      {pages.isLoading && <Loading />}
      {pages.error && <ErrorBox error={pages.error} />}
      {pages.data && (
        <div className="card flush">
          <div className="card-head">
            <h3>
              {tx("Pages")} <span className="badge plain">{visible.length}</span>
            </h3>
          </div>
          {visible.length === 0 ? (
            <div className="empty" style={{ padding: 24 }}>
              <div className="small">
                {projectId
                  ? "No overrides for this project yet — a new page here applies to it only."
                  : "No pages in this domain yet."}
              </div>
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{tx("Title")}</th>
                  <th>{tx("Path")}</th>
                  <th>{tx("Sections")}</th>
                  <th>{tx("Words")}</th>
                  <th>{tx("Last edit")}</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((p) => (
                  <tr key={p.path} className="clickable" onClick={() => setOpen(p.path)}>
                    <td>
                      <strong>{p.title}</strong>
                    </td>
                    <td className="mono small">{p.path}</td>
                    <td>{p.sections}</td>
                    <td>{p.words}</td>
                    <td className="muted small">{timeAgo(p.modified_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <CoreBlock
        projectId={projectId}
        page={core}
        admin={admin}
        onEdit={() => setOpen("core.md")}
      />
      <TrySearch projectId={projectId} domain={listDomain} />
      <IndexSettings admin={admin} projectId={projectId} />

      {open && (
        <PageEditor projectId={projectId} path={open} admin={admin} onClose={() => setOpen(null)} />
      )}
      {creating && (
        <NewPageModal
          projectId={projectId}
          domain={listDomain}
          onClose={() => setCreating(false)}
          onCreated={(path) => {
            setCreating(false);
            setOpen(path);
          }}
        />
      )}
    </div>
  );
}

// -- core.md ---------------------------------------------------------------------------------

function CoreBlock({
  projectId,
  page,
  admin,
  onEdit,
}: {
  projectId: string | null;
  page: StandardsPage | undefined;
  admin: boolean;
  onEdit: () => void;
}) {
  const tx = useT();
  const core = useStandardsPage(null, "core.md"); // core is global
  return (
    <div className="card">
      <div className="row spread">
        <h3>
          {tx("core.md")} <span className="badge plain">{tx("applies to all")}</span>
        </h3>
        {admin && !projectId && (
          <button className="btn small" onClick={onEdit}>
            {tx("Edit core rules")}
          </button>
        )}
      </div>
      <p className="muted small">
        Read by every agent on every project, in full, before any retrieved section; a retrieved
        standard never overrides it.
        {page ? ` ${page.sections} sections, ${page.words} words.` : ""}
      </p>
      {core.data ? (
        <details>
          <summary className="small">{tx("show the rules")}</summary>
          <Markdown text={core.data.text} />
        </details>
      ) : (
        <Loading rows={1} />
      )}
    </div>
  );
}

// -- page editor -----------------------------------------------------------------------------

function PageEditor({
  projectId,
  path,
  admin,
  onClose,
}: {
  projectId: string | null;
  path: string;
  admin: boolean;
  onClose: () => void;
}) {
  const tx = useT();
  const scope = path === "core.md" ? null : projectId;
  const page = useStandardsPage(scope, path);
  const save = useSaveStandardsPage(scope);
  const remove = useDeleteStandardsPage(scope);
  const toast = useToast();
  const [draft, setDraft] = useState<string | null>(null);
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const [deleting, setDeleting] = useState(false);
  const text = draft ?? page.data?.text ?? "";
  const dirty = draft !== null && draft !== page.data?.text;

  return (
    <Modal
      title={page.data ? `${page.data.title} — ${path}` : path}
      onClose={onClose}
      wide
      footer={
        <>
          {admin && path !== "core.md" && (
            <button className="btn danger" onClick={() => setDeleting(true)}>
              <IconTrash /> {tx("Delete")}
            </button>
          )}
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={onClose}>
            {tx("Close")}
          </button>
          {admin && (
            <button
              className="btn primary"
              disabled={!dirty || save.isPending}
              onClick={() =>
                save.mutate(
                  { path, text },
                  {
                    onSuccess: () => {
                      toast.ok("Page saved and reindexed");
                      setDraft(null);
                    },
                  },
                )
              }
            >
              {save.isPending ? tx("Saving…") : tx("Save")}
            </button>
          )}
        </>
      }
    >
      {page.isLoading && <Loading />}
      {page.error && <ErrorBox error={page.error} />}
      {page.data && (
        <>
          <nav className="tabs small" style={{ marginBottom: 10 }}>
            <a className={mode === "edit" ? "active" : ""} onClick={() => setMode("edit")}>
              {tx("Markdown")}
            </a>
            <a className={mode === "preview" ? "active" : ""} onClick={() => setMode("preview")}>
              {tx("Preview")}
            </a>
          </nav>
          {mode === "edit" ? (
            <textarea
              className="mono editor"
              value={text}
              readOnly={!admin}
              spellCheck={false}
              onChange={(e) => setDraft(e.target.value)}
              style={{ minHeight: 420 }}
            />
          ) : (
            <div className="preview">
              <Markdown text={text} />
            </div>
          )}
          <div className="muted small" style={{ marginTop: 6 }}>
            Front-matter (<code>domain</code>, <code>tags</code>, <code>applies_to</code>), one{" "}
            <code>{tx("# Title")}</code>
            {tx(", and")} <code>{tx("## sections")}</code>{" "}
            {tx(
              "under 400 words: each section is one retrievable chunk, so the heading should say what the rule is about. Saves are linted, reindexed at once and committed on the",
            )}{" "}
            <code>{tx("slipwright/standards")}</code> {tx("branch.")}
          </div>
          {save.error && <div className="callout error">{describeError(save.error)}</div>}
        </>
      )}
      {deleting && (
        <ConfirmModal
          title={tx("Delete page")}
          body={
            <>
              {tx("Delete")} <strong>{path}</strong>
              {tx("? Its sections stop being retrieved as soon as the index refreshes.")}
            </>
          }
          busy={remove.isPending}
          error={remove.error ? describeError(remove.error) : null}
          onClose={() => setDeleting(false)}
          onConfirm={() =>
            remove.mutate(path, {
              onSuccess: () => {
                toast.ok("Page deleted");
                onClose();
              },
            })
          }
        />
      )}
    </Modal>
  );
}

function NewPageModal({
  projectId,
  domain,
  onClose,
  onCreated,
}: {
  projectId: string | null;
  domain: string;
  onClose: () => void;
  onCreated: (path: string) => void;
}) {
  const tx = useT();
  const create = useCreateStandardsPage(projectId);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState(
    "## Rule\n\nState the rule, why it exists and how to apply it.\n",
  );
  return (
    <Modal
      title={`New ${domain} page`}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            {tx("Cancel")}
          </button>
          <button
            className="btn primary"
            disabled={!title.trim() || create.isPending}
            onClick={() =>
              create.mutate(
                { domain, title: title.trim(), text: body },
                { onSuccess: (page) => onCreated(page.path) },
              )
            }
          >
            {create.isPending ? tx("Creating…") : tx("Create")}
          </button>
        </>
      }
    >
      <div className="field">
        <label htmlFor="np-title">{tx("Title")}</label>
        <input
          id="np-title"
          type="text"
          value={title}
          autoFocus
          onChange={(e) => setTitle(e.target.value)}
          placeholder={tx("e.g. Queues and dead letters")}
        />
      </div>
      <div className="field">
        <label htmlFor="np-body">Sections (Markdown)</label>
        <textarea
          id="np-body"
          className="mono"
          value={body}
          spellCheck={false}
          onChange={(e) => setBody(e.target.value)}
          style={{ minHeight: 200 }}
        />
        <div className="help faint small">
          Front-matter and the title are added for you; the file goes to{" "}
          <code>
            {domain}/{title.trim() ? slugify(title) : "…"}.md
          </code>
          {projectId ? " under this project's .slipwright/standards" : " in the global corpus"}.
        </div>
      </div>
      {create.error && <div className="callout error">{describeError(create.error)}</div>}
    </Modal>
  );
}

function slugify(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "page"
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
    <div className="card">
      <h3>{tx("Try a search")}</h3>
      <p className="muted small">
        Type a task the way a phase goal reads and see which sections the agent would be given,
        ranked; the tool for tuning headings and chunking.
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
          Nothing matched; the agent would get the domain's opening sections instead.
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
    <div className="card">
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
            <option value="openai">openai — text embeddings (needs an OpenAI key)</option>
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
