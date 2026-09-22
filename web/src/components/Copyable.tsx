// A block of output (a log, a diff, JSON) with a copy button in its top-right corner,
// so a failing gate's output or a history detail can be pasted somewhere in one click.
import { useEffect, useState, type ReactNode } from "react";
import { useT } from "../i18n";

export function Copyable({ text, children }: { text: string; children: ReactNode }) {
  const tx = useT();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(id);
  }, [copied]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // no clipboard (plain http, old browser): select the text so ctrl+c works
      const range = document.createRange();
      const el = document.activeElement?.closest?.(".copyable")?.querySelector("pre, .diff");
      if (el) {
        range.selectNodeContents(el);
        window.getSelection()?.removeAllRanges();
        window.getSelection()?.addRange(range);
      }
      return;
    }
    setCopied(true);
  };
  return (
    <div className="copyable">
      <button
        type="button"
        className={`btn ghost copy-btn${copied ? " copied" : ""}`}
        onClick={() => void copy()}
        title={tx("Copy to clipboard")}
      >
        {copied ? tx("Copied") : tx("Copy")}
      </button>
      {children}
    </div>
  );
}
