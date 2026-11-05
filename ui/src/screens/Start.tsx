import { Alert, Button, Card, Chip, Input, Spinner } from "@heroui/react";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api, type ProjectSummary } from "../api/client";
import { useProjects } from "../api/queries";
import { basename, fmtDuration } from "../lib/format";
import { href, navigate } from "../lib/router";
import { LANGUAGES, useSettings, WHISPER_MODELS } from "../lib/settings";

export function Start() {
  const projects = useProjects();
  const settings = useSettings();
  const [path, setPath] = useState("");
  const [dragging, setDragging] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: (p: string) =>
      api.analyze({ path: p, stage: settings.stage, whisper_model: settings.whisperModel, language: settings.language }),
    onSuccess: (job) => {
      settings.setLastHash(job.content_hash);
      navigate({ screen: "analyse", jobId: job.job_id });
    },
  });

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (!file) return;
    // Der Browser gibt den vollständigen Pfad nicht preis, nur den Namen.
    const withPath = file as File & { path?: string };
    if (withPath.path) {
      setPath(withPath.path);
      setHint(null);
    } else {
      setPath((p) => (p.trim() ? p : file.name));
      setHint(`Der Browser verrät den Ordner von „${file.name}“ nicht. Bitte den vollständigen Pfad eintragen.`);
    }
  };

  const canStart = path.trim().length > 0 && !start.isPending;

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <div className="grid gap-6 md:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
        <Card className="flex flex-col gap-4 p-6">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`flex flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-10 text-center transition-colors ${dragging ? "border-primary-accent bg-[#0b2447]" : "border-line-light bg-panel-dark"}`}
          >
            <svg aria-hidden="true" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#338EF7" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 16V4M6 10l6-6 6 6M4 20h16" />
            </svg>
            <div className="text-base font-semibold">Video hierher ziehen</div>
            <div className="max-w-md text-sm text-text-muted">
              oder den Pfad unten eintragen. MP4, MOV, MKV, MXF. Das Video bleibt auf diesem Rechner.
            </div>
          </div>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (canStart) start.mutate(path.trim());
            }}
          >
            <Input
              aria-label="Pfad zur Videodatei"
              placeholder="E:\Videos\aufnahme.mp4"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              className="font-mono"
              fullWidth
            />
            {hint && (
              <Alert status="warning">
                <Alert.Content>
                  <Alert.Description>{hint}</Alert.Description>
                </Alert.Content>
              </Alert>
            )}
            {start.error && (
              <Alert status="danger">
                <Alert.Content>
                  <Alert.Title>Analyse konnte nicht starten</Alert.Title>
                  <Alert.Description>{start.error.message}</Alert.Description>
                </Alert.Content>
              </Alert>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Chip size="sm" variant="soft">Sprache: {LANGUAGES.find((l) => l.id === settings.language)?.label ?? settings.language}</Chip>
              <Chip size="sm" variant="soft">Whisper: {WHISPER_MODELS.find((m) => m.id === settings.whisperModel)?.id ?? settings.whisperModel}</Chip>
              <Chip size="sm" variant="soft">bis Stufe: {settings.stage}</Chip>
              <a href={href({ screen: "settings" })} className="text-xs text-text-muted underline-offset-2 hover:underline">
                ändern
              </a>
              <Button type="submit" variant="primary" className="ml-auto" isDisabled={!canStart}>
                {start.isPending ? <Spinner size="sm" /> : "Analyse starten"}
              </Button>
            </div>
          </form>
        </Card>
        <Card className="flex flex-col gap-3 p-5">
          <Card.Header>
            <Card.Title>System</Card.Title>
          </Card.Header>
          <Card.Content>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-text-muted">Whisper</dt>
              <dd>{settings.whisperModel}</dd>
              <dt className="text-text-muted">Sprache</dt>
              <dd>{settings.language}</dd>
              <dt className="text-text-muted">Cache</dt>
              <dd>{projects.data ? `${projects.data.length} Projekte` : "…"}</dd>
            </dl>
            <p className="mt-4 text-xs text-text-faint">
              Analyse und Transkription laufen im Backend (<code className="font-mono">visualcut serve</code>). Dieselben Daten
              liefert das CLI.
            </p>
          </Card.Content>
        </Card>
      </div>

      <section className="flex flex-col gap-3">
        <div className="flex items-baseline gap-3">
          <h2 className="text-base font-semibold">Projekte</h2>
          <span className="text-sm text-text-muted">{projects.data ? `${projects.data.length} analysiert` : ""}</span>
        </div>
        {projects.isLoading && <Spinner />}
        {projects.error && (
          <Alert status="danger">
            <Alert.Content>
              <Alert.Description>Projekte konnten nicht geladen werden: {projects.error.message}</Alert.Description>
            </Alert.Content>
          </Alert>
        )}
        {projects.data && projects.data.length === 0 && (
          <p className="text-sm text-text-muted">Noch keine Projekte. Oben ein Video angeben und analysieren.</p>
        )}
        <div className="flex flex-col gap-2">
          {projects.data?.map((p) => (
            <ProjectRow key={p.content_hash} project={p} onAnalyse={() => start.mutate(p.path)} />
          ))}
        </div>
      </section>
    </div>
  );
}

function ProjectRow({ project, onAnalyse }: { project: ProjectSummary; onAnalyse: () => void }) {
  const done = project.stages_done.includes("fusion");
  const setLastHash = useSettings((s) => s.setLastHash);
  return (
    <Card className="flex flex-row flex-wrap items-center gap-4 px-5 py-3">
      <div className="min-w-0 flex-1">
        <div className="truncate font-semibold" title={project.path}>
          {basename(project.path)}
        </div>
        <div className="truncate font-mono text-xs text-text-faint">{project.path}</div>
      </div>
      <div className="font-mono text-sm text-text-muted">{fmtDuration(project.duration)}</div>
      <div className="text-xs text-text-muted">
        {project.fps.toLocaleString("de-DE", { maximumFractionDigits: 2 })} fps
      </div>
      {done ? (
        <Chip size="sm" variant="soft" color="success">
          {project.cuts} Cuts
        </Chip>
      ) : (
        <Chip size="sm" variant="soft" color="warning">
          Stufe {project.stages_done.length} von 4
        </Chip>
      )}
      <div className="flex gap-2">
        {done ? (
          <>
            <Button
              size="sm"
              variant="primary"
              onPress={() => {
                setLastHash(project.content_hash);
                navigate({ screen: "review", hash: project.content_hash });
              }}
            >
              Review öffnen
            </Button>
            <Button
              size="sm"
              variant="outline"
              onPress={() => {
                setLastHash(project.content_hash);
                navigate({ screen: "export", hash: project.content_hash });
              }}
            >
              Export
            </Button>
          </>
        ) : (
          <Button size="sm" variant="secondary" onPress={onAnalyse}>
            Analyse fortsetzen
          </Button>
        )}
      </div>
    </Card>
  );
}
