import { Diff, looksLikeDiff } from "./Diff";
import { useT } from "../i18n";
import { Copyable } from "./Copyable";

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
  const tx = useT();
  if (!text) return <span className="muted">{tx("no detail")}</span>;
  if (looksLikeDiff(text))
    return (
      <Copyable text={text}>
        <Diff text={text} />
      </Copyable>
    );
  const json = prettyJson(text);
  return (
    <Copyable text={json ?? text}>
      <pre>{json ?? text}</pre>
    </Copyable>
  );
}
