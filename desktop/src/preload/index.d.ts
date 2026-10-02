import type { AgentApi } from "../shared/types";

declare global {
  interface Window {
    agent: AgentApi;
  }
}
