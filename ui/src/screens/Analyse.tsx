import { Alert, Button, Card, Chip, ProgressBar, Spinner } from "@heroui/react";
import { useEffect, useRef } from "react";
import type { Stage } from "../api/types";
import { STAGES, useJobProgress, type StageProgress } from "../lib/progress";
import { navigate } from "../lib/router";
import { useSettings } from "../lib/settings";

const STAGE_INFO: Record<Stage, { title: string; detail: string }> = {
  ingest: { title: "Stufe 0 · Ingest", detail: "Proxy, Audio, Hash" },
  technical: { title: "Stufe 1 · Technische Analyse", detail: "Szenen, Stille" },
  speech: { title: "Stufe 2 · Transkription", detail: "faster-whisper + whisperX" },
  fusion: { title: "Stufe 4 · Fusion und Snapping", detail: "Regeln, Wortgrenzen, Frames" },
};

export function Analyse({ jobId }: { jobId: string }) {
  const { job, events, stages, status, error } = useJobProgress(jobId);
  const setLastHash = useSettings((s) => s.setLastHash);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (job) setLastHash(job.content_hash);
  }, [job, setLastHash]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const doneCount = STAGES.filter((s) => stages[s].state === "done" || stages[s].state === "skipped").length;
  const running = STAGES.find((s) => stages[s].state === "running");
  const overall = Math.round(
    (STAGES.reduce((acc, s) => acc + (stages[s].state === "pending" || stages[s].state === "failed" ? 0 : stages[s].state === "running" ? stages[s].percent : 100), 0) /
      STAGES.length),
  );

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-6">
      <div className="flex flex-wrap items-center gap-4">
        <div>
          <h1 className="text-base font-semibold">Analyse</h1>
          <div className="font-mono text-xs text-text-muted">Job {jobId}{job ? ` · Projekt ${job.content_hash.slice(0, 12)}…` : ""}</div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-text-muted">Gesamt</span>
          <span className="font-semibold">{overall} %</span>
          {status === "running" && running && <span className="text-xs text-text-muted">· {STAGE_INFO[running].title}</span>}
          {status === "connecting" && <Spinner size="sm" />}
        </div>
        <div className="ml-auto flex gap-2">
          {status === "done" && job && (
            <>
              <Button variant="primary" onPress={() => navigate({ screen: "review", hash: job.content_hash })}>
                Review öffnen
              </Button>
              <Button variant="outline" onPress={() => navigate({ screen: "export", hash: job.content_hash })}>
                Export
              </Button>
            </>
          )}
          <Button variant="ghost" onPress={() => navigate({ screen: "start" })}>
            Zur Startseite
          </Button>
        </div>
      </div>

      {error && (
        <Alert status="danger">
          <Alert.Content>
            <Alert.Title>Analyse fehlgeschlagen</Alert.Title>
            <Alert.Description>
              <span className="font-mono text-xs">{error}</span>
            </Alert.Description>
          </Alert.Content>
        </Alert>
      )}
      {status === "done" && (
        <Alert status="success">
          <Alert.Content>
            <Alert.Title>Analyse fertig</Alert.Title>
            <Alert.Description>{doneCount} von {STAGES.length} Stufen, Ergebnis liegt im Cache.</Alert.Description>
          </Alert.Content>
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(320px,1.1fr)]">
        <ol className="flex flex-col gap-3">
          {STAGES.map((s, i) => (
            <StageRow key={s} index={i} stage={s} progress={stages[s]} />
          ))}
        </ol>
        <Card className="flex min-h-[320px] flex-col overflow-hidden p-0">
          <div className="flex items-center gap-3 border-b border-line px-4 py-3">
            <span className="font-semibold">Live-Log</span>
            <span className="text-xs text-text-muted">JSON-Lines, dieselben wie im CLI</span>
            <span className="ml-auto text-xs text-text-faint">{events.length} Einträge</span>
          </div>
          <div ref={logRef} className="max-h-[60vh] flex-1 overflow-auto bg-panel-dark p-3 font-mono text-xs leading-5">
            {events.length === 0 && <div className="text-text-faint">Warte auf Ereignisse …</div>}
            {events.map((ev, i) => (
              <div key={i} className="flex gap-2 whitespace-pre-wrap">
                <span className={ev.event === "error" ? "text-[#F31260]" : ev.event === "stage_done" || ev.event === "job_done" ? "text-[#45D483]" : "text-text-faint"}>
                  {ev.event.padEnd(13)}
                </span>
                <span className="text-text-muted">{ev.stage ?? ""}</span>
                <span className="text-text">{ev.message}</span>
                {ev.percent != null && <span className="text-text-faint">{Math.round(ev.percent)} %</span>}
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}

function StageRow({ index, stage, progress }: { index: number; stage: Stage; progress: StageProgress }) {
  const info = STAGE_INFO[stage];
  const color = progress.state === "failed" ? "danger" : progress.state === "running" ? "accent" : "success";
  const label = { pending: "wartet", running: "läuft", done: "fertig", skipped: "Cache", failed: "Fehler" }[progress.state];
  const chipColor = { pending: "default", running: "accent", done: "success", skipped: "success", failed: "danger" }[progress.state] as
    | "default"
    | "accent"
    | "success"
    | "danger";
  const took = progress.startedAt && progress.endedAt ? `${((progress.endedAt - progress.startedAt) / 1000).toFixed(1)} s` : "";
  return (
    <li>
      <Card className={`flex flex-col gap-2 p-4 ${progress.state === "pending" ? "opacity-60" : ""}`}>
        <div className="flex items-center gap-3">
          <span className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold ${progress.state === "done" || progress.state === "skipped" ? "bg-[#17C964] text-[#052e16]" : progress.state === "running" ? "bg-primary text-white" : progress.state === "failed" ? "bg-[#F31260] text-white" : "bg-line text-text-muted"}`}>
            {index}
          </span>
          <div className="min-w-0 flex-1">
            <div className="font-semibold">{info.title}</div>
            <div className="text-xs text-text-muted">{info.detail}</div>
          </div>
          {took && <span className="font-mono text-xs text-text-faint">{took}</span>}
          <Chip size="sm" variant="soft" color={chipColor}>
            {label}
          </Chip>
        </div>
        <ProgressBar aria-label={info.title} value={progress.percent} maxValue={100} color={color} size="sm">
          <ProgressBar.Track>
            <ProgressBar.Fill />
          </ProgressBar.Track>
        </ProgressBar>
        {progress.message && <div className="truncate text-xs text-text-muted">{progress.message}</div>}
      </Card>
    </li>
  );
}
