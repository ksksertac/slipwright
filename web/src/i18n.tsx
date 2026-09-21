// The UI's language. Keys are the English source strings; a translation maps them to
// the other language, and a missing translation shows the English so nothing is ever
// blank. The choice lives in localStorage (default Turkish) and never reaches the
// server: which language the *agents* write in is a per-project setting.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { TR } from "./i18n/tr";

export type Lang = "tr" | "en";
const KEY = "slipwright.lang";

function stored(): Lang {
  try {
    const v = localStorage.getItem(KEY);
    return v === "en" || v === "tr" ? v : "tr";
  } catch {
    return "tr";
  }
}

type Vars = Record<string, string | number>;
export type T = (key: string, vars?: Vars) => string;

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void; t: T } | null>(null);

function fill(text: string, vars?: Vars): string {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(stored);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(KEY, l);
    } catch {
      /* private mode: the choice lasts for the session */
    }
    document.documentElement.lang = l;
  }, []);
  const t = useCallback<T>(
    (key, vars) => fill(lang === "tr" ? (TR[key] ?? key) : key, vars),
    [lang],
  );
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

/** The language outside React (helpers like timeAgo): what the provider last set. */
export function currentLang(): Lang {
  return stored();
}

export function useT(): T {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useT outside LangProvider");
  return ctx.t;
}

export function useLang(): { lang: Lang; setLang: (l: Lang) => void } {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang outside LangProvider");
  return { lang: ctx.lang, setLang: ctx.setLang };
}
