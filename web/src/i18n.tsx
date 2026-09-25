// The UI's language. Keys are the English source strings; a translation maps them to
// the other language, and a missing translation shows the English so nothing is ever
// blank. The choice lives in localStorage and never reaches the server: which language
// the *agents* write in is a per-project setting.
//
// Nobody has chosen yet on a first visit, so the browser answers for them: a Turkish
// browser opens in Turkish, anything else in English. The moment the person picks a
// language themselves that is what is remembered, on every page including the ones
// before they have signed in.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { TR } from "./i18n/tr";

export type Lang = "tr" | "en";
const KEY = "slipwright.lang";

/** What the browser says this person reads, for as long as they have not said themselves. */
function fromBrowser(): Lang {
  try {
    const wanted = navigator.languages?.length ? navigator.languages : [navigator.language];
    for (const tag of wanted) {
      // "tr", "tr-TR", "tr-CY" -- the region does not change which of the two we speak
      const base = String(tag).toLowerCase().split("-")[0];
      if (base === "tr" || base === "en") return base;
    }
  } catch {
    /* no navigator: fall through to English */
  }
  return "en";
}

function stored(): Lang {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "en" || v === "tr") return v;
  } catch {
    /* private mode: the browser's guess it is */
  }
  return fromBrowser();
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
  }, []);
  const t = useCallback<T>(
    (key, vars) => fill(lang === "tr" ? (TR[key] ?? key) : key, vars),
    [lang],
  );
  // <html lang> follows too, so a screen reader and the browser's own offer to translate
  // agree with what is on screen -- from the first paint, not only after a change
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

/** The language outside React (helpers like timeAgo): what the provider last set. */
export function currentLang(): Lang {
  return stored();
}

/** A name as the platform writes it: one capital at the front, the rest lower case.
 *
 * Only the capital follows the platform's language, so a project called "istanbul" reads
 * as "İstanbul" in Turkish rather than "Istanbul". The rest deliberately does not:
 * Turkish would lower "API test" to "apı test", and "Api test" is what a person expects
 * to see in either language.
 *
 * Display only. The stored name stays exactly as it was typed -- that is what is
 * searched, what the edit form shows, and what goes to the server.
 */
export function sentenceCase(name: string): string {
  const text = name.trim();
  if (!text) return text;
  const [first, ...rest] = [...text];
  return (first ?? "").toLocaleUpperCase(currentLang()) + rest.join("").toLowerCase();
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
