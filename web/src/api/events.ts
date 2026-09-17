// Live updates: one EventSource on /api/events per mounted page. Every event names the
// project and job it concerns, so we invalidate exactly those queries and React Query
// refetches what is on screen. Reconnects with backoff when the connection drops.
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { keys } from "./hooks";

interface LiveEvent {
  type: string;
  project_id: string | null;
  job_id: string | null;
  payload: Record<string, unknown>;
}

export function useLiveEvents(projectId?: string, onNotice?: (text: string) => void) {
  const qc = useQueryClient();
  useEffect(() => {
    let source: EventSource | null = null;
    let retry = 1000;
    let timer: number | undefined;
    let closed = false;

    const handle = (event: LiveEvent) => {
      const pid = event.project_id;
      if (pid) {
        void qc.invalidateQueries({ queryKey: keys.project(pid) }); // jobs/board/progress/...
      }
      void qc.invalidateQueries({ queryKey: keys.projects });
      void qc.invalidateQueries({ queryKey: keys.overview });
      void qc.invalidateQueries({ queryKey: ["overview", "badge"] });
      void qc.invalidateQueries({ queryKey: keys.agents });
      void qc.invalidateQueries({ queryKey: ["activity"] });
      if (event.job_id) {
        void qc.invalidateQueries({ queryKey: keys.job(event.job_id) });
      }
      if (event.type === "supervisor.auto_approved" && onNotice) {
        const gate = String(event.payload.gate ?? "gate");
        const confidence = Number(event.payload.confidence ?? 0);
        onNotice(`Supervisor approved the ${gate} (confidence ${confidence.toFixed(2)})`);
      }
      if (event.type === "test_run.state" && typeof event.payload.run_id === "string") {
        void qc.invalidateQueries({ queryKey: keys.testRun(event.payload.run_id) });
        void qc.invalidateQueries({ queryKey: keys.testRunOutput(event.payload.run_id) });
      }
    };

    const connect = () => {
      if (closed) return;
      const url = projectId ? `/api/events?project_id=${projectId}` : "/api/events";
      source = new EventSource(url, { withCredentials: true });
      const onMessage = (e: MessageEvent<string>) => {
        retry = 1000;
        try {
          handle(JSON.parse(e.data) as LiveEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
      for (const type of [
        "job.state",
        "job.data",
        "test_run.state",
        "activity",
        "project",
        "supervisor.auto_approved",
      ]) {
        source.addEventListener(type, onMessage as EventListener);
      }
      source.onerror = () => {
        source?.close();
        source = null;
        timer = window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      source?.close();
    };
  }, [projectId, qc, onNotice]);
}
