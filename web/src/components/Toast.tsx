import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

type Kind = "ok" | "bad" | "info";
interface Toast {
  id: number;
  kind: Kind;
  text: string;
}
export interface ToastApi {
  push: (text: string, kind?: Kind) => void;
  ok: (text: string) => void;
  bad: (text: string) => void;
}

const Ctx = createContext<ToastApi | null>(null);
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Kind = "info") => {
    const id = ++seq;
    setToasts((t) => [...t, { id, kind, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  const api = useMemo<ToastApi>(
    () => ({ push, ok: (t) => push(t, "ok"), bad: (t) => push(t, "bad") }),
    [push],
  );
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(Ctx);
  if (!api) throw new Error("useToast outside ToastProvider");
  return api;
}
