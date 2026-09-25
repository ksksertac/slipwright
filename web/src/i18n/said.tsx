// What the agents said, in the language the platform is set to.
//
// `useT` translates the *interface*: strings that live in this repository, looked up by
// their English source. This is the other half -- the strings the agents wrote, which no
// repository can know in advance. A project has its own language (the one Jira and the
// pull request see) and it need not be the platform's, so the server keeps every piece of
// agent prose in both and hands over a map keyed by what the agent actually wrote.
//
// `say(text)` is that lookup, and it is deliberately total: a string with no entry yet --
// because the server is still working through the project, or the provider is down, or
// the project is already written in this language -- comes back exactly as it was. A page
// therefore never waits on this and never shows a gap.
import { createContext, useCallback, useContext, type ReactNode } from "react";
import { useTranslations } from "../api/hooks";
import { useLang } from "../i18n";

export type Say = (text: string | null | undefined) => string;

const SayContext = createContext<Say>((text) => text ?? "");

/** Loads the bridge for one project (or, with `projectId={null}`, for every project) and
 *  puts `say` in reach of everything below it. */
export function SayProvider({
  projectId,
  children,
}: {
  projectId: string | null;
  children: ReactNode;
}) {
  const { lang } = useLang();
  const bridge = useTranslations(projectId, lang);
  const texts = bridge.data?.texts;
  const say = useCallback<Say>(
    (text) => {
      const source = text ?? "";
      return texts?.[source] ?? texts?.[source.trim()] ?? source;
    },
    [texts],
  );
  return <SayContext.Provider value={say}>{children}</SayContext.Provider>;
}

/** Outside a provider this is the identity, so a component can call it unconditionally. */
export function useSay(): Say {
  return useContext(SayContext);
}
