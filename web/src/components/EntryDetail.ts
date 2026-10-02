// A history entry's detail -- a diff, a build log -- read when somebody opens it.
//
// A development is sent without them (each entry carries `detail_size` instead): the page
// asks for the development every time anything happens to it, and one QA note once held a
// 145 MB diff that every one of those requests carried. The entry is fetched on its own,
// once, when it is opened; an entry is never rewritten, so it is not asked for again.
import type { Job, Transition } from "../api/client";
import { useTransition } from "../api/hooks";

export function hasDetail(t: Transition): boolean {
  return !!t.detail || (t.detail_size ?? 0) > 0;
}

/** The detail of `t`, an entry of `job.history`, fetched once `wanted`. */
export function useEntryDetail(
  job: Job,
  t: Transition | undefined,
  wanted: boolean,
): { text: string; loading: boolean } {
  const index = t ? job.history.indexOf(t) : -1;
  const missing = !!t && !t.detail && hasDetail(t);
  const fetched = useTransition(job.id, wanted && missing && index >= 0 ? index : null);
  if (!t) return { text: "", loading: false };
  if (!missing) return { text: t.detail ?? "", loading: false };
  return { text: fetched.data?.detail ?? "", loading: wanted && !fetched.data };
}
