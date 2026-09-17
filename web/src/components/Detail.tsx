import { Diff, looksLikeDiff } from "./Diff";

function prettyJson(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return null;
  }
}

/** Renders a history entry's long-form detail: a diff, pretty JSON, or plain text. */
export function Detail({ text }: { text: string | null | undefined }) {
  if (!text) return <span className="muted">no detail</span>;
  if (looksLikeDiff(text)) return <Diff text={text} />;
  const json = prettyJson(text);
  return <pre>{json ?? text}</pre>;
}
