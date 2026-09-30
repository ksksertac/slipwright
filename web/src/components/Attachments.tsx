// Files a person gives the agents: a requirements document, a PDF of screens, a photo of a
// whiteboard. Each is read once by the Product Owner's model when it arrives; what that
// reading made of it is shown under the file, because it is what the agents will work from.
//
// A file's name and contents are the person's own and are never translated. The reading is
// agent prose and goes through say(), like every other read-only thing an agent wrote.
import { useRef, useState, type Dispatch, type DragEvent, type SetStateAction } from "react";
import { describeError, type Attachment } from "../api/client";
import {
  useAttachments,
  useDeleteAttachment,
  useReadAttachmentAgain,
  useUploadAttachment,
} from "../api/hooks";
import { useT } from "../i18n";
import { useSay } from "../i18n/said";
import { IconPaperclip, IconTrash } from "./icons";

/** What the server reads. It judges a file by its contents, not this list; the list only
 *  keeps the browser's picker from offering what would be refused. */
const ACCEPT = ".pdf,.docx,.png,.jpg,.jpeg,.gif,.webp,.txt,.md,.markdown,.csv,.json,.yaml,.yml";
const MAX_MB = 50;

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** A drop zone that is also a button: click to choose, or drop files on it. */
export function FilePicker({
  onFiles,
  busy,
  disabled,
}: {
  onFiles: (files: File[]) => void;
  busy?: boolean;
  disabled?: boolean;
}) {
  const tx = useT();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  return (
    <div
      className={`file-drop${over ? " over" : ""}${disabled ? " disabled" : ""}`}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          input.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <IconPaperclip width={18} height={18} />
      <span>
        {busy
          ? tx("Uploading…")
          : tx(
              "Drop files here or click to choose — PDF, Word, images or text, up to {n} MB each",
              {
                n: MAX_MB,
              },
            )}
      </span>
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = ""; // the same file chosen again is a new choice
          if (files.length) onFiles(files);
        }}
      />
    </div>
  );
}

/** Upload one file after another and say which did not make it. Files over the limit are
 *  refused here, before a byte is sent. */
function useUploads(projectId: string, draft: boolean, onDone?: (a: Attachment) => void) {
  const tx = useT();
  const upload = useUploadAttachment(projectId);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const send = async (files: File[]) => {
    setBusy(true);
    const failed: string[] = [];
    for (const file of files) {
      if (file.size > MAX_MB * 1024 * 1024) {
        failed.push(`${file.name}: ${tx("larger than {n} MB", { n: MAX_MB })}`);
        continue;
      }
      try {
        onDone?.(await upload.mutateAsync({ file, draft }));
      } catch (err) {
        failed.push(`${file.name}: ${describeError(err)}`);
      }
    }
    setErrors(failed);
    setBusy(false);
  };
  return { send, busy, errors };
}

function Reading({ a, onAgain }: { a: Attachment; onAgain?: () => void }) {
  const tx = useT();
  const say = useSay();
  const r = a.reading;
  if (a.reading_state === "pending" || a.reading_state === "reading") {
    return <span className="badge work">{tx("Being read…")}</span>;
  }
  if (a.reading_state === "failed") {
    return (
      <div className="small">
        <span className="badge bad">{tx("Could not be read")}</span>{" "}
        {r?.note && <span className="faint">{r.note}</span>}{" "}
        {a.text_chars > 0 && (
          <span className="muted">{tx("Its text still reaches the agents.")}</span>
        )}{" "}
        {onAgain && (
          <button type="button" className="btn small ghost" onClick={onAgain}>
            {tx("Read again")}
          </button>
        )}
      </div>
    );
  }
  if (!r) return null;
  const kind =
    r.kind === "screens" ? tx("Screens") : r.kind === "document" ? tx("Document") : tx("Other");
  return (
    <div className="small stack" style={{ gap: 4 }}>
      <div>
        <span className="badge ok">{kind}</span>{" "}
        {r.screens.length > 0 && (
          <span className="faint">{tx("{n} screen(s)", { n: r.screens.length })}</span>
        )}{" "}
        {r.requirements.length > 0 && (
          <span className="faint">{tx("{n} requirement(s)", { n: r.requirements.length })}</span>
        )}
      </div>
      {r.summary && <div className="muted">{say(r.summary)}</div>}
      {(r.screens.length > 0 || r.requirements.length > 0) && (
        <details>
          <summary className="faint">{tx("What the agents will work from")}</summary>
          {r.screens.length > 0 && (
            <ul>
              {r.screens.map((s, i) => (
                <li key={i}>
                  <strong>{say(s.title)}</strong>
                  {s.page ? (
                    <span className="faint"> · {tx("page {n}", { n: s.page })}</span>
                  ) : null}
                  <div className="muted">{say(s.description)}</div>
                </li>
              ))}
            </ul>
          )}
          {r.requirements.length > 0 && (
            <ul>
              {r.requirements.map((q, i) => (
                <li key={i}>{say(q)}</li>
              ))}
            </ul>
          )}
        </details>
      )}
      {r.note && <div className="faint">{r.note}</div>}
    </div>
  );
}

function Row({
  a,
  projectId,
  readOnly,
  onRemoved,
}: {
  a: Attachment;
  projectId: string;
  readOnly?: boolean;
  onRemoved?: (id: string) => void;
}) {
  const tx = useT();
  const remove = useDeleteAttachment(projectId);
  const again = useReadAttachmentAgain(projectId);
  const picture = a.media_type.startsWith("image/");
  const href = `/api/attachments/${a.id}/file`;
  return (
    <li className="file-row">
      {picture ? (
        <a href={`${href}?inline=true`} target="_blank" rel="noreferrer" className="file-thumb">
          <img src={`${href}?inline=true`} alt="" />
        </a>
      ) : (
        <span className="file-thumb">
          <IconPaperclip width={18} height={18} />
        </span>
      )}
      <div className="file-body">
        <div className="row spread">
          <a href={href} className="file-name">
            {a.name}
          </a>
          <span className="faint small">
            {size(a.size)}
            {a.pages ? ` · ${tx("{n} page(s)", { n: a.pages })}` : ""}
            {a.scope === "job" ? ` · ${tx("this development only")}` : ""}
          </span>
        </div>
        <Reading a={a} onAgain={readOnly ? undefined : () => again.mutate(a.id)} />
      </div>
      {!readOnly && (
        <button
          type="button"
          className="btn icon ghost"
          title={tx("Remove")}
          aria-label={tx("Remove")}
          disabled={remove.isPending}
          onClick={() => remove.mutate(a.id, { onSuccess: () => onRemoved?.(a.id) })}
        >
          <IconTrash width={16} height={16} />
        </button>
      )}
    </li>
  );
}

export function AttachmentList({
  items,
  projectId,
  readOnly,
  onRemoved,
}: {
  items: Attachment[];
  projectId: string;
  readOnly?: boolean;
  onRemoved?: (id: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <ul className="file-list">
      {items.map((a) => (
        <Row key={a.id} a={a} projectId={projectId} readOnly={readOnly} onRemoved={onRemoved} />
      ))}
    </ul>
  );
}

function Errors({ errors }: { errors: string[] }) {
  if (errors.length === 0) return null;
  return (
    <div className="callout error small">
      {errors.map((e) => (
        <div key={e}>{e}</div>
      ))}
    </div>
  );
}

/** The project's own files: every development of the project reads them, like the brief. */
export function ProjectFiles({ projectId, readOnly }: { projectId: string; readOnly?: boolean }) {
  const tx = useT();
  const files = useAttachments(projectId);
  const { send, busy, errors } = useUploads(projectId, false);
  const items = files.data ?? [];
  if (readOnly && items.length === 0) return null;
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{tx("Documents and screens")}</h3>
      <p className="muted small">
        {tx(
          "Requirements, specifications, mock-ups, screenshots. Each is read once when it arrives; the Product Owner plans from them, and the Designer keeps to the screens.",
        )}
      </p>
      <AttachmentList items={items} projectId={projectId} readOnly={readOnly} />
      {!readOnly && <FilePicker onFiles={(f) => void send(f)} busy={busy} disabled={busy} />}
      <Errors errors={errors} />
    </div>
  );
}

/** Files chosen for a development that has not been started yet. They are uploaded as
 *  drafts straight away -- so a refused one is said now, not after pressing the button --
 *  and handed to the development when it is. */
export function DraftFiles({
  projectId,
  drafts,
  onChange,
}: {
  projectId: string;
  drafts: Attachment[];
  // an updater, not a value: files arrive one after another while the list is held
  onChange: Dispatch<SetStateAction<Attachment[]>>;
}) {
  const { send, busy, errors } = useUploads(projectId, true, (a) => onChange((old) => [...old, a]));
  return (
    <div className="stack" style={{ gap: 8, marginTop: 8 }}>
      <AttachmentList
        items={drafts}
        projectId={projectId}
        onRemoved={(id) => onChange((old) => old.filter((d) => d.id !== id))}
      />
      <FilePicker onFiles={(f) => void send(f)} busy={busy} disabled={busy} />
      <Errors errors={errors} />
    </div>
  );
}

/** What a development was given: the project's files and its own. */
export function JobFiles({ projectId, jobId }: { projectId: string; jobId: string }) {
  const tx = useT();
  const files = useAttachments(projectId, jobId);
  const items = files.data ?? [];
  if (items.length === 0) return null;
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{tx("Documents and screens")}</h3>
      <AttachmentList items={items} projectId={projectId} readOnly />
    </div>
  );
}

/** Files picked before the project exists, sent once it does. */
export function PendingFiles({
  files,
  onChange,
}: {
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const tx = useT();
  const [errors, setErrors] = useState<string[]>([]);
  return (
    <div className="stack" style={{ gap: 8 }}>
      {files.length > 0 && (
        <ul className="file-list">
          {files.map((f, i) => (
            <li className="file-row" key={`${f.name}-${i}`}>
              <span className="file-thumb">
                <IconPaperclip width={18} height={18} />
              </span>
              <div className="file-body">
                <div className="row spread">
                  <span className="file-name">{f.name}</span>
                  <span className="faint small">{size(f.size)}</span>
                </div>
              </div>
              <button
                type="button"
                className="btn icon ghost"
                title={tx("Remove")}
                aria-label={tx("Remove")}
                onClick={() => onChange(files.filter((_, j) => j !== i))}
              >
                <IconTrash width={16} height={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <FilePicker
        onFiles={(picked) => {
          const big = picked.filter((f) => f.size > MAX_MB * 1024 * 1024);
          setErrors(big.map((f) => `${f.name}: ${tx("larger than {n} MB", { n: MAX_MB })}`));
          onChange([...files, ...picked.filter((f) => f.size <= MAX_MB * 1024 * 1024)]);
        }}
      />
      <Errors errors={errors} />
    </div>
  );
}

export interface SourceRef {
  file: string;
  page?: number | null;
}

/** Where to look at one place in a file: the page of a PDF drawn, a picture shown, anything
 *  else downloaded. */
function sourceHref(a: Attachment, page?: number | null): string {
  if (a.media_type === "application/pdf" && page) return `/api/attachments/${a.id}/pages/${page}`;
  if (a.media_type.startsWith("image/")) return `/api/attachments/${a.id}/file?inline=true`;
  return `/api/attachments/${a.id}/file`;
}

function SourceChip({ source, found }: { source: SourceRef; found?: Attachment }) {
  const tx = useT();
  const label = (
    <>
      <IconPaperclip width={12} height={12} /> {source.file}
      {source.page ? ` · ${tx("page {n}", { n: source.page })}` : ""}
    </>
  );
  return found ? (
    <a
      className="chip idle source-chip"
      href={sourceHref(found, source.page)}
      target="_blank"
      rel="noreferrer"
    >
      {label}
    </a>
  ) : (
    <span className="chip idle source-chip">{label}</span>
  );
}

function LinkedSources({
  sources,
  projectId,
  jobId,
}: {
  sources: SourceRef[];
  projectId: string;
  jobId?: string;
}) {
  const files = useAttachments(projectId, jobId);
  const byName = new Map((files.data ?? []).map((a) => [a.name, a]));
  return (
    <span className="source-chips">
      {sources.map((s, i) => (
        <SourceChip key={i} source={s} found={byName.get(s.file)} />
      ))}
    </span>
  );
}

/** The files (and pages) a story was drawn from. Linked to them when the page knows which
 *  project it is on; named only, where it does not. */
export function Sources({
  sources,
  projectId,
  jobId,
}: {
  sources?: SourceRef[] | null;
  projectId?: string | null;
  jobId?: string;
}) {
  if (!sources || sources.length === 0) return null;
  if (projectId) return <LinkedSources sources={sources} projectId={projectId} jobId={jobId} />;
  return (
    <span className="source-chips">
      {sources.map((s, i) => (
        <SourceChip key={i} source={s} />
      ))}
    </span>
  );
}
