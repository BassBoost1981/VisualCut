import { Alert, Button, Card, Checkbox, Chip, Description, Input, Label, Radio, RadioGroup, Spinner } from "@heroui/react";
import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, type ExportResult } from "../api/client";
import { useCuts, useProject } from "../api/queries";
import type { CutReason } from "../api/types";
import { basename, dirname, fmtDuration, fmtPercent } from "../lib/format";
import { REASON_COLOR, REASON_LABEL } from "../lib/reasons";
import { navigate } from "../lib/router";

type Format = "fcpxml" | "otio" | "edl" | "preview";

const FORMATS: { id: Format; title: string; hint: string; tag?: string }[] = [
  { id: "fcpxml", title: "FCPXML", hint: "DaVinci Resolve Import. Behält Marker und Clipnamen.", tag: "Empfohlen" },
  { id: "otio", title: "OpenTimelineIO", hint: "Kanonisches Format. Für Pipelines, Agenten und andere Werkzeuge." },
  { id: "edl", title: "EDL (CMX 3600)", hint: "Fallback für jedes Schnittprogramm. Keine Marker, keine Namen." },
  { id: "preview", title: "Vorschau-Render (MP4)", hint: "ffmpeg schneidet den Proxy direkt. Zum Gegenhören, kein Ersatz für Resolve." },
];

export function Export({ hash }: { hash: string }) {
  const project = useProject(hash);
  const cuts = useCuts(hash);
  const [format, setFormat] = useState<Format>("fcpxml");
  const [openAsCut, setOpenAsCut] = useState(false);
  const [out, setOut] = useState("");
  const [result, setResult] = useState<ExportResult | { path: string } | null>(null);

  const media = project.data?.media;
  const stem = media ? basename(media.path).replace(/\.[^.]+$/, "") : "export";
  const defaultOut = media ? `${dirname(media.path)}\\${stem}_visualcut.${format === "preview" ? "mp4" : format}` : "";

  const stats = useMemo(() => {
    const list = cuts.data?.cuts ?? [];
    const by = (s: string) => list.filter((c) => (c.status ?? "open") === s);
    const accepted = by("accepted");
    const open = by("open");
    const rejected = by("rejected");
    const removeSec = [...accepted, ...(openAsCut ? open : [])].reduce((a, c) => a + ((c.end ?? 0) - (c.start ?? 0)), 0);
    const reasons = new Map<CutReason, number>();
    for (const c of list) if (c.status !== "rejected") reasons.set(c.reason, (reasons.get(c.reason) ?? 0) + 1);
    return { accepted, open, rejected, removeSec, reasons };
  }, [cuts.data, openAsCut]);

  const run = useMutation({
    mutationFn: async () => {
      const target = out.trim() || defaultOut;
      if (format === "preview") return api.renderPreview(hash, { out: target, open_as_cut: openAsCut });
      return api.exportProject(hash, { format, out: target, open_as_cut: openAsCut });
    },
    onSuccess: (r) => setResult(r),
  });

  if (project.isLoading || cuts.isLoading) return <div className="p-6"><Spinner /></div>;
  if (project.error || !media)
    return (
      <div className="p-6">
        <Alert status="danger">
          <Alert.Content>
            <Alert.Description>Projekt nicht gefunden: {project.error?.message}</Alert.Description>
          </Alert.Content>
        </Alert>
      </div>
    );

  const duration = media.duration;
  const after = Math.max(0, duration - stats.removeSec);

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 p-6">
      <div className="flex flex-wrap items-center gap-4">
        <div>
          <h1 className="text-base font-semibold">{basename(media.path)}</h1>
          <div className="text-xs text-text-muted">
            {stats.accepted.length} angenommen · {stats.rejected.length} verworfen · {stats.open.length} offen
            {stats.open.length > 0 && !openAsCut && " · offene Cuts werden als Marker exportiert"}
          </div>
        </div>
        <Button variant="outline" className="ml-auto" onPress={() => navigate({ screen: "review", hash })}>
          Zurück zum Review
        </Button>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.3fr)_minmax(300px,1fr)]">
        <div className="flex flex-col gap-5">
          <Card className="flex flex-col gap-4 p-5">
            <Card.Header>
              <Card.Title>Format</Card.Title>
            </Card.Header>
            <Card.Content>
              <RadioGroup aria-label="Format" value={format} onChange={(v) => setFormat(v as Format)} className="flex flex-col gap-2">
                {FORMATS.map((f) => (
                  <Radio key={f.id} value={f.id} className="rounded-xl border border-line bg-panel-dark px-3 py-2">
                    <Radio.Content>
                      <Radio.Control>
                        <Radio.Indicator />
                      </Radio.Control>
                      <div className="flex flex-col">
                        <Label className="flex items-center gap-2 font-semibold">
                          {f.title}
                          {f.tag && (
                            <Chip size="sm" variant="soft" color="accent">
                              {f.tag}
                            </Chip>
                          )}
                        </Label>
                        <Description className="text-xs text-text-muted">{f.hint}</Description>
                      </div>
                    </Radio.Content>
                  </Radio>
                ))}
              </RadioGroup>
            </Card.Content>
          </Card>

          <Card className="flex flex-col gap-4 p-5">
            <Card.Header>
              <Card.Title>Optionen</Card.Title>
            </Card.Header>
            <Card.Content className="flex flex-col gap-4">
              <Checkbox isSelected={openAsCut} onChange={setOpenAsCut}>
                <Checkbox.Content>
                  <Checkbox.Control>
                    <Checkbox.Indicator />
                  </Checkbox.Control>
                  <div className="flex flex-col">
                    <Label className="font-semibold">Offene Cuts schneiden</Label>
                    <Description className="text-xs text-text-muted">
                      Ohne Häkchen bleiben unsichere Stellen im Bild und werden als Marker gesetzt (<code className="font-mono">--open-as-cut</code>).
                    </Description>
                  </div>
                </Checkbox.Content>
              </Checkbox>
              <div className="flex flex-col gap-1">
                <Label>Zieldatei</Label>
                <Input
                  aria-label="Zieldatei"
                  value={out}
                  onChange={(e) => setOut(e.target.value)}
                  placeholder={defaultOut}
                  className="font-mono"
                  fullWidth
                />
                <span className="text-xs text-text-faint">Leer lassen: neben dem Original.</span>
              </div>
            </Card.Content>
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card className="flex flex-col gap-4 p-5">
            <Card.Header>
              <Card.Title>Zusammenfassung</Card.Title>
            </Card.Header>
            <Card.Content className="flex flex-col gap-3">
              <div className="flex items-center gap-2 font-mono text-lg">
                <span className="text-text-muted">{fmtDuration(duration)}</span>
                <span className="text-text-faint">→</span>
                <span className="font-semibold">{fmtDuration(after)}</span>
                <span className="text-sm font-semibold text-[#45D483]">−{fmtPercent(duration ? stats.removeSec / duration : 0)}</span>
              </div>
              <dl className="grid grid-cols-[1fr_auto] gap-y-1.5 text-sm">
                <dt className="text-text-muted">Schnitte in der Timeline</dt>
                <dd className="font-semibold">{stats.accepted.length + (openAsCut ? stats.open.length : 0)}</dd>
                <dt className="text-text-muted">Marker (offen)</dt>
                <dd className="font-semibold">{openAsCut ? 0 : stats.open.length}</dd>
                <dt className="text-text-muted">Verworfene Vorschläge</dt>
                <dd className="font-semibold">{stats.rejected.length} (nicht exportiert)</dd>
              </dl>
              <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                {[...stats.reasons.entries()].map(([r, n]) => (
                  <span key={r} className="inline-flex items-center gap-1.5 text-xs text-text-muted">
                    <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: REASON_COLOR[r] }} />
                    {REASON_LABEL[r]} {n}
                  </span>
                ))}
              </div>
            </Card.Content>
            <Card.Footer className="flex flex-col gap-3">
              <Button variant="primary" fullWidth onPress={() => run.mutate()} isDisabled={run.isPending}>
                {run.isPending ? <Spinner size="sm" /> : `${FORMATS.find((f) => f.id === format)?.title} exportieren`}
              </Button>
              {run.error && (
                <Alert status="danger">
                  <Alert.Content>
                    <Alert.Description>{run.error.message}</Alert.Description>
                  </Alert.Content>
                </Alert>
              )}
              {result && (
                <Alert status="success">
                  <Alert.Content>
                    <Alert.Title>Geschrieben</Alert.Title>
                    <Alert.Description>
                      <span className="font-mono text-xs break-all">{result.path}</span>
                      {"clips" in result && (
                        <span className="mt-1 block text-xs text-text-muted">
                          {result.clips} Clips · {result.cuts_applied} Schnitte · {result.markers} Marker
                        </span>
                      )}
                    </Alert.Description>
                  </Alert.Content>
                </Alert>
              )}
            </Card.Footer>
          </Card>
          <Card className="flex flex-col gap-2 p-5 text-sm">
            <Card.Header>
              <Card.Title>Danach in Resolve</Card.Title>
            </Card.Header>
            <Card.Content>
              <ol className="list-decimal space-y-1 pl-5 text-text-muted">
                <li>Datei → Import → Timeline, die FCPXML wählen.</li>
                <li>Originaldatei relinken, falls gefragt.</li>
                <li>Marker sind die offenen Cuts.</li>
              </ol>
            </Card.Content>
          </Card>
        </div>
      </div>
    </div>
  );
}
