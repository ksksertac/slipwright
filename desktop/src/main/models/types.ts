// One model call, whichever model answers it. Every provider returns the model's text
// exactly as it came: the server parses and validates it as it would its own provider's
// answer, so nothing here tries to "fix" JSON (docs/machines-protocol.md §1).

export interface Image {
  media_type: string;
  data: string;
  label?: string | null;
}

export interface ModelCall {
  system: string;
  prompt: string;
  images: Image[];
  thinkingDepth: string | null;
  model: string;
  /** The read-only checkout, or null: the model then answers from the prompt alone. */
  checkout: string | null;
  /** An empty directory of the call's own, for a CLI to run in when there is no checkout
   *  and to keep pictures in. */
  scratch: string;
  timeoutMs: number;
  signal: AbortSignal;
  log: (text: string) => void;
}

export interface ModelAnswer {
  text: string;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
}

export type FailureKind = "rejected" | "error" | "timeout";

/** Why a call could not be answered, in the protocol's three kinds: `rejected` is the plan
 *  or the key (asking again will not help), `timeout` ran out of time, `error` anything else. */
export class ModelFailure extends Error {
  constructor(
    message: string,
    readonly kind: FailureKind,
  ) {
    super(message);
  }
}

/** The call was taken back (409 on progress) or the app is stopping: nobody wants an answer. */
export class Cancelled extends Error {}

/** Words a provider uses when the plan, the key or a limit -- not the request -- is the
 *  problem. Shared by both CLIs: they report it as text, not as a status. */
export const REFUSED =
  /usage limit|rate limit|limit reached|quota|credit balance|not logged in|please run \/login|log ?in|invalid api key|unauthori[sz]ed|forbidden|\b401\b|\b403\b|subscription|plan/i;

/** What a CLI agent is told before the server's system text: it is answering one request
 *  for a program, and the only thing it may touch is the code it was given to read. */
export function preamble(checkout: boolean): string {
  return checkout
    ? "You are answering one request for an automated system. The current directory is a " +
        "read-only checkout of the project at the commit the request was written from; you " +
        "may read and search it to inform your answer. Do not modify files, run commands " +
        "or browse. Reply with the answer only, exactly in the format the request asks for.\n\n"
    : "You are answering one request for an automated system. Everything you need is in " +
        "this message. Do not run commands, read or write files, or browse: reply with the " +
        "answer only, exactly in the format the request asks for.\n\n";
}

/** A CLI is shown pictures as files without their labels, so the prompt says which is which. */
export function imageLabels(paths: string[], images: Image[]): string {
  if (!images.length) return "";
  const lines = images.map((image, n) => `Image ${n + 1}${image.label ? ` (${image.label})` : ""}: ${paths[n]}`);
  return `The request comes with these pictures:\n${lines.join("\n")}\n\n`;
}

/** The environment a model CLI runs in: the person's own (it is their CLI, signed in as
 *  them), minus what belongs to this app's Electron runtime. */
export function cliEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {};
  for (const [name, value] of Object.entries(process.env)) {
    if (!name.startsWith("ELECTRON_") && name !== "NODE_OPTIONS") env[name] = value;
  }
  return env;
}
