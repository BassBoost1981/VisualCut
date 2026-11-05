import { useEffect, useRef, useState } from "react";
import { api, progressSocketUrl, type JobInfo } from "../api/client";
import type { ProgressEvent, Stage } from "../api/types";

export type StageState = "pending" | "running" | "done" | "skipped" | "failed";

export interface StageProgress {
  state: StageState;
  percent: number;
  message: string;
  startedAt?: number;
  endedAt?: number;
}

export interface JobProgress {
  job: JobInfo | null;
  events: ProgressEvent[];
  stages: Record<Stage, StageProgress>;
  status: "connecting" | "running" | "done" | "failed";
  error: string | null;
}

export const STAGES: Stage[] = ["ingest", "technical", "speech", "fusion"];

function emptyStages(): Record<Stage, StageProgress> {
  return Object.fromEntries(STAGES.map((s) => [s, { state: "pending", percent: 0, message: "" }])) as Record<
    Stage,
    StageProgress
  >;
}

/** Verfolgt einen Analyse-Job über den WebSocket `/ws/progress/{job_id}` (JSON-Lines wie im CLI). */
export function useJobProgress(jobId: string): JobProgress {
  const [job, setJob] = useState<JobInfo | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [status, setStatus] = useState<JobProgress["status"]>("connecting");
  const [error, setError] = useState<string | null>(null);
  const stagesRef = useRef(emptyStages());
  const [stages, setStages] = useState(stagesRef.current);

  useEffect(() => {
    let closed = false;
    stagesRef.current = emptyStages();
    setStages(stagesRef.current);
    setEvents([]);
    setError(null);
    setStatus("connecting");

    const apply = (raw: ProgressEvent) => {
      const ev = { ...raw, message: raw.message ?? "" };
      const now = Date.now();
      if (ev.stage) {
        const s = { ...stagesRef.current[ev.stage] };
        switch (ev.event) {
          case "stage_start":
            s.state = "running";
            s.percent = 0;
            s.startedAt = now;
            s.message = ev.message || "läuft";
            break;
          case "progress":
            s.state = "running";
            s.percent = ev.percent ?? s.percent;
            s.message = ev.message || s.message;
            if (!s.startedAt) s.startedAt = now;
            break;
          case "stage_done":
            s.state = "done";
            s.percent = 100;
            s.endedAt = now;
            s.message = ev.message || "fertig";
            break;
          case "stage_skipped":
            s.state = "skipped";
            s.percent = 100;
            s.endedAt = now;
            s.message = ev.message || "aus dem Cache";
            break;
          case "error":
            s.state = "failed";
            s.message = ev.message;
            break;
          default:
            break;
        }
        stagesRef.current = { ...stagesRef.current, [ev.stage]: s };
        setStages(stagesRef.current);
      } else if (ev.event === "error") {
        for (const st of STAGES) {
          if (stagesRef.current[st].state === "running") {
            stagesRef.current = { ...stagesRef.current, [st]: { ...stagesRef.current[st], state: "failed", message: ev.message } };
          }
        }
        setStages(stagesRef.current);
      }
      if (ev.event === "error") {
        setError(ev.message);
        setStatus("failed");
      }
      if (ev.event === "job_done") setStatus("done");
      if (ev.event === "closed") setStatus(ev.message === "failed" ? "failed" : "done");
      if (ev.event !== "closed") setEvents((prev) => [...prev, ev]);
    };

    void api
      .getJob(jobId)
      .then((info) => {
        if (closed) return;
        setJob(info);
      })
      .catch((e: Error) => {
        if (closed) return;
        setError(e.message);
        setStatus("failed");
      });

    const ws = new WebSocket(progressSocketUrl(jobId));
    ws.onopen = () => setStatus((s) => (s === "connecting" ? "running" : s));
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data as string) as ProgressEvent;
      apply(ev);
    };
    ws.onerror = () => {
      if (!closed) setError("WebSocket-Verbindung fehlgeschlagen");
    };
    ws.onclose = (e) => {
      if (closed) return;
      if (e.code === 4004) {
        setError("Job nicht gefunden (Server neu gestartet?)");
        setStatus("failed");
      }
      // Status nach dem Schließen vom Server bestätigen
      void api.getJob(jobId).then((info) => {
        if (closed) return;
        setJob(info);
        if (info.status === "failed") {
          setStatus("failed");
          setError(info.error);
        } else if (info.status === "done") setStatus("done");
      }).catch(() => undefined);
    };
    return () => {
      closed = true;
      ws.close();
    };
  }, [jobId]);

  return { job, events, stages, status, error };
}
