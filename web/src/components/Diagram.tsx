// The Architect's drawing of the product: a Mermaid flowchart it writes with the plan, drawn
// here and again in the project's README. Mermaid is most of a megabyte, so it is loaded
// the first time a drawing is on screen and never on the pages that have none.
//
// The source is a model's, so Mermaid keeps its strict security level: labels are text,
// never HTML, and a click handler in the source does nothing.
import { useEffect, useId, useState } from "react";
import { Modal } from "./Modal";
import { useT } from "../i18n";

type MermaidApi = typeof import("mermaid").default;
let loading: Promise<MermaidApi> | null = null;

function mermaid(): Promise<MermaidApi> {
  loading ??= import("mermaid").then((m) => m.default);
  return loading;
}

/** The page's own colours, read when a drawing is made: Mermaid's are its own, and a
 *  white chart on the dark theme was the first thing anybody would see. */
function palette(): Record<string, string> {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    background: v("--surface"),
    primaryColor: v("--accent-soft"),
    primaryBorderColor: v("--accent"),
    primaryTextColor: v("--text"),
    secondaryColor: v("--surface-2"),
    tertiaryColor: v("--surface-3"),
    clusterBkg: v("--surface-2"),
    clusterBorder: v("--line-strong"),
    lineColor: v("--text-2"),
    textColor: v("--text"),
    edgeLabelBackground: v("--surface"),
    // the body's, not the root's: the root has none of its own and Mermaid fell to serif
    fontFamily: getComputedStyle(document.body).fontFamily,
    fontSize: "15px",
  };
}

/** Changes whenever the theme does, chosen by hand or by the system. */
function useThemeStamp(): string {
  const read = () =>
    `${document.documentElement.getAttribute("data-theme") ?? ""}:${
      window.matchMedia("(prefers-color-scheme: dark)").matches
    }`;
  const [stamp, setStamp] = useState(read);
  useEffect(() => {
    const update = () => setStamp(read());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributeFilter: ["data-theme"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
    };
  }, []);
  return stamp;
}

/** The SVG for one source, or why there is none. */
function useDrawing(source: string): { svg: string | null; failed: boolean } {
  const id = `diagram-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const theme = useThemeStamp();
  const [drawn, setDrawn] = useState<{ svg: string | null; failed: boolean }>({
    svg: null,
    failed: false,
  });
  useEffect(() => {
    let live = true;
    mermaid()
      .then(async (m) => {
        m.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          themeVariables: palette(),
          flowchart: { htmlLabels: false, curve: "basis" },
        });
        const { svg } = await m.render(id, source);
        if (live) setDrawn({ svg, failed: false });
      })
      .catch(() => {
        // a drawing the model got wrong is shown as what it wrote, not as nothing
        if (live) setDrawn({ svg: null, failed: true });
        document.getElementById(`d${id}`)?.remove(); // Mermaid's own error box
      });
    return () => {
      live = false;
    };
  }, [id, source, theme]);
  return drawn;
}

/** A drawing that fits its column, and opens full size when pressed. */
export function Diagram({ source }: { source: string }) {
  const tx = useT();
  const [open, setOpen] = useState(false);
  const { svg, failed } = useDrawing(source);
  if (failed) return <pre className="diagram-source">{source}</pre>;
  if (!svg) return <div className="diagram loading" aria-busy="true" />;
  return (
    <>
      <button
        type="button"
        className="diagram"
        onClick={() => setOpen(true)}
        title={tx("Open the drawing full size")}
        aria-label={tx("Open the drawing full size")}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      {open && (
        <Modal title={tx("Architecture")} onClose={() => setOpen(false)} wide>
          <div className="diagram full" dangerouslySetInnerHTML={{ __html: svg }} />
        </Modal>
      )}
    </>
  );
}
