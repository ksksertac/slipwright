// What this machine tells the server it can be given (docs/machines-protocol.md §1).
// A platform it builds, and a `write:<domain>` for every agent that is switched on *and*
// has a model it can actually run -- an agent with no usable model asking for work would
// only take calls it must then fail, and every failed call is a wait for somebody.

import type { AgentId, Detected, ModelChoice, Settings } from "@shared/types";

/** The domains each agent writes. Backend takes the two that belong to nobody else:
 *  documentation and the general phase a plan sometimes has. */
export const DOMAINS: Record<AgentId, string[]> = {
  backend: ["backend", "general", "docs"],
  web: ["web"],
  mobile: ["mobile"],
  devops: ["infra"],
};

export function agentFor(domain: string | null | undefined): AgentId {
  for (const [agent, domains] of Object.entries(DOMAINS) as [AgentId, string[]][]) {
    if (domain && domains.includes(domain)) return agent;
  }
  return "backend";
}

export interface Keys {
  anthropic: boolean;
  openai: boolean;
}

export function usable(choice: ModelChoice | null, detected: Detected, keys: Keys): boolean {
  if (!choice) return false;
  switch (choice.provider) {
    case "claude-code":
      return detected.claude.installed && detected.claude.signedIn !== false;
    case "codex":
      return detected.codex.installed && detected.codex.signedIn !== false;
    case "anthropic":
      return keys.anthropic;
    case "openai":
      return keys.openai;
  }
}

export function capabilities(settings: Settings, detected: Detected, keys: Keys): string[] {
  const out: string[] = [];
  if (settings.runBuilds) {
    if (detected.ios.ok) out.push("ios");
    if (detected.android.ok) out.push("android");
  }
  for (const [agent, domains] of Object.entries(DOMAINS) as [AgentId, string[]][]) {
    const own = settings.agents[agent];
    if (own.enabled && usable(own.model, detected, keys)) out.push(...domains.map((d) => `write:${d}`));
  }
  return out;
}
