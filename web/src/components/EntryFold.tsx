// A history entry's detail behind a fold, read when the fold is opened (see EntryDetail).
import { useState, type CSSProperties, type ReactNode } from "react";
import type { Job, Transition } from "../api/client";
import { Detail } from "./Detail";
import { hasDetail, useEntryDetail } from "./EntryDetail";
import { Loading } from "./ui";

export function EntryFold({
  job,
  entry,
  summary,
  style,
}: {
  job: Job;
  entry: Transition | undefined;
  summary: ReactNode;
  style?: CSSProperties;
}) {
  const [open, setOpen] = useState(false);
  const detail = useEntryDetail(job, entry, open);
  if (!entry || !hasDetail(entry)) return null;
  return (
    <details style={style} onToggle={(e) => setOpen(e.currentTarget.open)}>
      {summary}
      {detail.loading ? <Loading rows={2} /> : <Detail text={detail.text} />}
    </details>
  );
}
