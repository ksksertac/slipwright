// A unified diff, coloured by line kind. Small on purpose: no third-party highlighter.
export function looksLikeDiff(text: string): boolean {
  return /^(diff --git|--- |\+\+\+ |@@ )/m.test(text);
}

export function Diff({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="diff">
      {lines.map((line, i) => {
        let cls = "";
        if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff --git")) {
          cls = "meta";
        } else if (line.startsWith("@@")) cls = "hunk";
        else if (line.startsWith("+")) cls = "add";
        else if (line.startsWith("-")) cls = "del";
        return (
          <div key={i} className={cls}>
            {line || " "}
          </div>
        );
      })}
    </div>
  );
}
