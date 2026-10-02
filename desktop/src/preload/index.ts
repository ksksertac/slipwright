// The page's only door to the machine: a fixed set of calls, each one an IPC message the
// main process checks. No Node, no ipcRenderer, nothing generic is exposed -- the page
// can ask for exactly what this list says and nothing else.

import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";
import type { AgentApi, AppState } from "../shared/types";

const api: AgentApi = {
  state: () => ipcRenderer.invoke("state"),
  onState: (listener) => {
    const handler = (_event: IpcRendererEvent, state: AppState) => listener(state);
    ipcRenderer.on("state", handler);
    return () => ipcRenderer.removeListener("state", handler);
  },
  history: () => ipcRenderer.invoke("history"),
  pair: (code) => ipcRenderer.invoke("pair", code),
  forget: () => ipcRenderer.invoke("forget"),
  saveSettings: (patch) => ipcRenderer.invoke("saveSettings", patch),
  saveAgent: (agent, patch) => ipcRenderer.invoke("saveAgent", agent, patch),
  saveSecret: (name, value) => ipcRenderer.invoke("saveSecret", name, value),
  saveSource: (github, user, bitbucket) => ipcRenderer.invoke("saveSource", github, user, bitbucket),
  saveJira: (site, email, token) => ipcRenderer.invoke("saveJira", site, email, token),
  detect: () => ipcRenderer.invoke("detect"),
  chooseWorkDir: () => ipcRenderer.invoke("chooseWorkDir"),
};

contextBridge.exposeInMainWorld("agent", api);
