// QA's test cases, laid out to be scanned rather than read.
//
// A case is only a name and a sentence (`TestCase` in roles/results.py): QA writes the
// endpoint, the status it expects and the error code into prose. Rather than ask the model
// for more structure -- one more thing it can get wrong -- the prose is read here: an HTTP
// method followed by a path is an endpoint, a known status followed by an error code or a
// verb that says "returns" is a response. Anything not recognised stays plain text, so a
// case that names no endpoint loses nothing; a false match would be worse than a miss,
// which is why a bare number ("200 characters") is never taken for a status.
import type { ReactNode } from "react";
import { useSay } from "../i18n/said";

export interface CaseShape {
  name?: string;
  description?: string;
}

const METHODS = "GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS";
const STATUSES =
  "200|201|202|204|301|302|303|304|307|308|400|401|402|403|404|405|409|410|413|415|422|429|500|501|502|503|504";
// an error code the status carries (`invalid_credentials`), or a status's own name
const NAME = "[a-z]+_[a-z_]+|unauthenticated|unauthorized|forbidden|conflict";
// what may follow a status for it to be one: a name, or a word that says it is what came
// back -- in either language
const AFTER = `${NAME}|dön|don|verir|alır|alir|yanıt|ile\\s|returns?|responds?|with\\s|response`;
const TOKEN = new RegExp(
  "`([^`]+)`" + // `code`
    `|\\b(${METHODS})\\s+(\\/[^\\s,;)\`'"]*[^\\s,;.:)\`'"])` + // POST /api/tasks/{id}/done
    `|\\b(${STATUSES})\\b(?=\\s+(?:${AFTER}))(?:\\s+(${NAME})\\b)?`, // 401 invalid_credentials
  "gi",
);

type Part =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "endpoint"; method: string; path: string }
  | { kind: "status"; code: string; name?: string };

function parseCase(text: string): Part[] {
  const parts: Part[] = [];
  let at = 0;
  for (const m of text.matchAll(TOKEN)) {
    const start = m.index ?? 0;
    if (start > at) parts.push({ kind: "text", text: text.slice(at, start) });
    const [, code, method, path, status, name] = m;
    if (code !== undefined) {
      // a backticked "GET /x" is still an endpoint
      const inner = new RegExp(`^(${METHODS})\\s+(\\/\\S+)$`, "i").exec(code.trim());
      parts.push(
        inner?.[1] && inner[2]
          ? { kind: "endpoint", method: inner[1].toUpperCase(), path: inner[2] }
          : { kind: "code", text: code },
      );
    } else if (method && path) {
      parts.push({ kind: "endpoint", method: method.toUpperCase(), path });
    } else if (status) {
      parts.push({ kind: "status", code: status, name });
    }
    at = start + m[0].length;
  }
  if (at < text.length) parts.push({ kind: "text", text: text.slice(at) });
  return parts;
}

/** `GecerliBilgiyleOturumAcilir` -> "Gecerli bilgiyle oturum acilir": the name is a test
 * method's, and reads better as a sentence. The identifier itself stays beside it. */
function humanize(name: string): string {
  if (/\s/.test(name)) return name;
  const words = name
    .replace(/_/g, " ")
    .replace(/([a-zçğıöşü])([A-ZÇĞİÖŞÜ])/g, "$1 $2")
    .replace(/([A-ZÇĞİÖŞÜ]+)([A-ZÇĞİÖŞÜ][a-zçğıöşü])/g, "$1 $2")
    // a status stands apart ("Istekler401"); the 2 of "Pbkdf2" does not
    .replace(/([a-zA-Z])(\d{3})/g, "$1 $2")
    .replace(/(\d)([a-zA-Z])/g, "$1 $2")
    .split(/\s+/)
    .filter(Boolean)
    // an acronym (API, CSRF) keeps its capitals; a word does not
    .map((w, i) => (i > 0 && !/^[A-Z0-9]{2,}$/.test(w) ? w.toLowerCase() : w));
  return words.join(" ");
}

function Endpoint({ method, path }: { method: string; path: string }) {
  return (
    <code className="tc-ep">
      <span className={`tc-method ${method.toLowerCase()}`}>{method}</span>
      {path}
    </code>
  );
}

function Status({ code, name }: { code: string; name?: string }) {
  return (
    <span className={`tc-status s${code[0]}`}>
      {code}
      {name && <span className="tc-status-name">{name}</span>}
    </span>
  );
}

function render(parts: Part[]): ReactNode[] {
  return parts.map((p, i) => {
    switch (p.kind) {
      case "text":
        return p.text;
      case "code":
        return <code key={i}>{p.text}</code>;
      case "endpoint":
        return <Endpoint key={i} method={p.method} path={p.path} />;
      case "status":
        return <Status key={i} code={p.code} name={p.name} />;
    }
  });
}

function Case({ index, c }: { index: number; c: CaseShape }) {
  const say = useSay();
  const name = say(c.name);
  const parts = parseCase(say(c.description));
  // the endpoints a case touches, once each, in the order it names them
  const seen = new Set<string>();
  const endpoints = parts.filter((p): p is Extract<Part, { kind: "endpoint" }> => {
    if (p.kind !== "endpoint") return false;
    const key = `${p.method} ${p.path}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return (
    <li className="tc">
      <span className="tc-n">{index + 1}</span>
      <div className="tc-body">
        <div className="tc-head">
          <strong className="tc-title">{humanize(name)}</strong>
          {endpoints.length > 0 && (
            <span className="tc-eps">
              {endpoints.map((e) => (
                <Endpoint key={`${e.method} ${e.path}`} method={e.method} path={e.path} />
              ))}
            </span>
          )}
        </div>
        {name !== humanize(name) && <div className="tc-id mono">{name}</div>}
        {c.description && <div className="tc-desc">{render(parts)}</div>}
      </div>
    </li>
  );
}

export function TestCaseList({ cases }: { cases: CaseShape[] }) {
  return (
    <ol className="tc-list">
      {cases.map((c, i) => (
        <Case key={i} index={i} c={c} />
      ))}
    </ol>
  );
}
