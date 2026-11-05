import { Alert, Button, Chip, Spinner } from "@heroui/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { mediaUrl } from "../api/client";
import { useCuts, useDecide, useProject } from "../api/queries";
import type { Cut, CutStatus } from "../api/types";
import { CutPanel } from "../components/CutPanel";
import { Player, seekBy } from "../components/Player";
import { Timeline } from "../components/Timeline";
import { Transcript } from "../components/Transcript";
import { basename, fmtDuration, fmtPercent } from "../lib/format";
import { useReview } from "../lib/review-store";
import { navigate } from "../lib/router";
import { useSettings } from "../lib/settings";

export function Review({ hash }: { hash: string }) {
  const project = useProject(hash);
  const cutsQuery = useCuts(hash);
  const decide = useDecide(hash);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const { selectedCutId, select, reasonFilter, onlyOpen, onlyMaybe } = useReview();
  const setLastHash = useSettings((s) => s.setLastHash);

  useEffect(() => setLastHash(hash), [hash, setLastHash]);
  useEffect(() => () => select(null), [select]);

  // Zeit per requestAnimationFrame, damit Cursor und Mitlauf flüssig sind
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) setCurrentTime((t) => (Math.abs(t - v.currentTime) > 0.02 ? v.currentTime : t));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const allCuts = useMemo(() => cutsQuery.data?.cuts ?? [], [cutsQuery.data]);
  const visible = useMemo(
    () =>
      allCuts
        .filter((c) => (!reasonFilter || c.reason === reasonFilter) && (!onlyOpen || c.status === "open") && (!onlyMaybe || c.maybe))
        .sort((a, b) => (a.start ?? 0) - (b.start ?? 0)),
    [allCuts, reasonFilter, onlyOpen, onlyMaybe],
  );
  const selected = useMemo(() => allCuts.find((c) => c.id === selectedCutId) ?? null, [allCuts, selectedCutId]);
  const activeCut = useMemo(
    () => allCuts.find((c) => c.status !== "rejected" && c.start != null && c.end != null && currentTime >= c.start && currentTime < c.end) ?? null,
    [allCuts, currentTime],
  );

  const seek = useCallback((t: number) => {
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, t);
  }, []);

  const jumpTo = useCallback(
    (cut: Cut) => {
      select(cut.id);
      seek((cut.start ?? 0) - 0.5);
    },
    [select, seek],
  );

  const step = useCallback(
    (dir: 1 | -1) => {
      if (visible.length === 0) return;
      const idx = visible.findIndex((c) => c.id === selectedCutId);
      let next: Cut | undefined;
      if (idx < 0) {
        next = dir > 0 ? visible.find((c) => (c.start ?? 0) > currentTime) ?? visible[0] : [...visible].reverse().find((c) => (c.start ?? 0) < currentTime) ?? visible[visible.length - 1];
      } else {
        next = visible[(idx + dir + visible.length) % visible.length];
      }
      if (next) jumpTo(next);
    },
    [visible, selectedCutId, currentTime, jumpTo],
  );

  const decideSelected = useCallback(
    (status: CutStatus, advance = true) => {
      if (!selected) return;
      decide.mutate({ cutId: selected.id, status });
      if (advance) {
        const idx = visible.findIndex((c) => c.id === selected.id);
        const next = visible[idx + 1];
        if (next) jumpTo(next);
      }
    },
    [selected, decide, visible, jumpTo],
  );

  const opts = { preventDefault: true, enableOnFormTags: false };
  useHotkeys("space", () => { const v = videoRef.current; if (!v) return; if (v.paused) void v.play(); else v.pause(); }, opts, []);
  useHotkeys("k", () => videoRef.current?.pause(), opts, []);
  useHotkeys("j", () => seekBy(videoRef, -5), opts, []);
  useHotkeys("l", () => seekBy(videoRef, 5), opts, []);
  useHotkeys("left", () => seekBy(videoRef, -1 / (project.data?.media.fps ?? 25)), opts, [project.data]);
  useHotkeys("right", () => seekBy(videoRef, 1 / (project.data?.media.fps ?? 25)), opts, [project.data]);
  useHotkeys("a", () => decideSelected("accepted"), opts, [decideSelected]);
  useHotkeys("r", () => decideSelected("rejected"), opts, [decideSelected]);
  useHotkeys("o", () => decideSelected("open", false), opts, [decideSelected]);
  useHotkeys("down, n", () => step(1), opts, [step]);
  useHotkeys("up, p", () => step(-1), opts, [step]);
  useHotkeys("enter", () => { if (selected) jumpTo(selected); }, opts, [selected, jumpTo]);

  if (project.isLoading || cutsQuery.isLoading) return <div className="p-6"><Spinner /></div>;
  if (project.error || !project.data)
    return (
      <div className="p-6">
        <Alert status="danger">
          <Alert.Content>
            <Alert.Title>Projekt nicht gefunden</Alert.Title>
            <Alert.Description>{project.error?.message ?? hash}</Alert.Description>
          </Alert.Content>
        </Alert>
      </div>
    );

  const a = project.data;
  const media = a.media;
  const words = a.speech?.words ?? [];
  const scenes = (a.technical?.scenes ?? []).filter((s) => s.detector.includes("content"));
  const counts = {
    accepted: allCuts.filter((c) => c.status === "accepted").length,
    rejected: allCuts.filter((c) => c.status === "rejected").length,
    open: allCuts.filter((c) => c.status === "open").length,
  };
  const removed = allCuts.filter((c) => c.status === "accepted").reduce((s, c) => s + ((c.end ?? 0) - (c.start ?? 0)), 0);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-4 border-b border-line px-6 py-3.5">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold" title={media.path}>
            {basename(media.path)}
          </div>
          <div className="text-xs text-text-muted">
            {media.width}×{media.height} · {media.fps.toLocaleString("de-DE", { maximumFractionDigits: 2 })} fps · {a.speech?.model ? `Whisper ${a.speech.model}` : "kein Transkript"}
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-[10px] border border-line bg-panel px-3 py-1.5 font-mono text-[13px]">
          <span className="text-text-muted">{fmtDuration(media.duration)}</span>
          <span className="text-text-faint">→</span>
          <span className="font-medium">{fmtDuration(media.duration - removed)}</span>
          <span className="font-semibold text-[#45D483]">−{fmtPercent(media.duration ? removed / media.duration : 0)}</span>
        </div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          <Chip size="sm" variant="soft">{allCuts.length} Cuts</Chip>
          <Chip size="sm" variant="soft" color="success">{counts.accepted} angenommen</Chip>
          <Chip size="sm" variant="soft" color="danger">{counts.rejected} verworfen</Chip>
          <Chip size="sm" variant="soft" color="warning">{counts.open} offen</Chip>
        </div>
        <div className="ml-auto flex gap-2">
          {decide.error && <span className="self-center text-xs text-[#F31260]">Speichern fehlgeschlagen: {decide.error.message}</span>}
          <Button variant="primary" onPress={() => navigate({ screen: "export", hash })}>
            Exportieren
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(340px,440px)]">
        <div className="flex min-w-0 flex-col gap-4">
          <Player
            src={mediaUrl(hash, "proxy")}
            fps={media.fps}
            videoRef={videoRef}
            currentTime={currentTime}
            activeCut={activeCut}
            onPrevCut={() => step(-1)}
            onNextCut={() => step(1)}
          />
          {media.has_audio ? (
            <Timeline
              audioUrl={mediaUrl(hash, "audio")}
              duration={media.duration}
              cuts={visible}
              scenes={scenes}
              events={a.events ?? []}
              videoRef={videoRef}
              currentTime={currentTime}
            />
          ) : (
            <div className="rounded-2xl border border-line bg-panel p-4 text-sm text-text-muted">Keine Tonspur, keine Wellenform.</div>
          )}
          <CutPanel
            cut={selected}
            words={words}
            fps={media.fps}
            pending={decide.isPending}
            onDecide={(s) => decideSelected(s, s !== "open")}
            onJump={() => selected && jumpTo(selected)}
          />
        </div>
        <Transcript words={words} cuts={visible} currentTime={currentTime} onSeek={seek} />
      </div>
    </div>
  );
}
