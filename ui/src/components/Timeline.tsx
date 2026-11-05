import { Button } from "@heroui/react";
import { useEffect, useMemo, useRef, type RefObject } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.js";
import type { Cut, SceneChange } from "../api/types";
import { fmtDuration } from "../lib/format";
import { REASON_COLOR, REASON_LABEL, REASONS } from "../lib/reasons";
import { useReview } from "../lib/review-store";

interface Props {
  audioUrl: string;
  duration: number;
  cuts: Cut[];
  scenes: SceneChange[];
  videoRef: RefObject<HTMLVideoElement | null>;
  currentTime: number;
}

function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/**
 * Wellenform (wavesurfer.js auf dem WAV aus Stufe 0) plus Cut-Spur als Regionen und Szenenwechsel als Marker.
 * wavesurfer spielt nichts ab: der Cursor folgt dem Video, Klick in die Wellenform spult das Video.
 */
export function Timeline({ audioUrl, duration, cuts, scenes, videoRef, currentTime }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null);
  const selectedCutId = useReview((s) => s.selectedCutId);
  const select = useReview((s) => s.select);
  const pxPerSec = useReview((s) => s.pxPerSec);
  const setPxPerSec = useReview((s) => s.setPxPerSec);
  const cutsRef = useRef(cuts);
  cutsRef.current = cuts;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const regions = RegionsPlugin.create();
    const ws = WaveSurfer.create({
      container: el,
      url: audioUrl,
      height: 72,
      waveColor: "#52525b",
      progressColor: "#338EF7",
      cursorColor: "#338EF7",
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 1,
      normalize: true,
      minPxPerSec: useReview.getState().pxPerSec,
      autoScroll: true,
      autoCenter: true,
      dragToSeek: false,
      interact: true,
      plugins: [regions],
    });
    wsRef.current = ws;
    regionsRef.current = regions;
    ws.on("interaction", (t) => {
      const v = videoRef.current;
      if (v) v.currentTime = t;
      ws.pause();
    });
    regions.on("region-clicked", (region: Region, e: MouseEvent) => {
      e.stopPropagation();
      const cut = cutsRef.current.find((c) => c.id === region.id);
      if (!cut) return;
      select(cut.id);
      const v = videoRef.current;
      if (v) v.currentTime = Math.max(0, (cut.start ?? 0) - 0.5);
    });
    return () => {
      ws.destroy();
      wsRef.current = null;
      regionsRef.current = null;
    };
    // Nur einmal pro Audio-URL aufbauen
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [audioUrl]);

  // Cut-Regionen und Szenenmarker neu zeichnen, wenn sich Cuts oder Auswahl ändern
  useEffect(() => {
    const ws = wsRef.current;
    const regions = regionsRef.current;
    if (!ws || !regions) return;
    const draw = () => {
      regions.clearRegions();
      for (const s of scenes) {
        regions.addRegion({ id: `scene-${s.frame}`, start: s.time, color: "#71717A", drag: false, resize: false });
      }
      for (const c of cuts) {
        if (c.start == null || c.end == null) continue;
        const rejected = c.status === "rejected";
        const color = REASON_COLOR[c.reason];
        const alpha = rejected ? 0.15 : c.status === "accepted" ? 0.75 : 0.4;
        const r = regions.addRegion({
          id: c.id,
          start: c.start,
          end: c.end,
          color: hexToRgba(color, alpha),
          drag: false,
          resize: false,
          content: c.end - c.start > 1.5 ? REASON_LABEL[c.reason] : undefined,
          avoidOverlapping: false,
        });
        if (r.element) {
          r.element.style.outline = c.id === selectedCutId ? "2px solid #ECEDEE" : c.status === "open" ? `1px dashed ${color}` : "none";
          r.element.style.outlineOffset = "-1px";
          r.element.style.borderRadius = "4px";
          r.element.style.cursor = "pointer";
          r.element.title = `${REASON_LABEL[c.reason]} · ${c.confidence.toFixed(2)} · ${c.status}`;
        }
      }
    };
    if (ws.getDuration() > 0) draw();
    const off = ws.on("ready", draw);
    return () => off();
  }, [cuts, scenes, selectedCutId]);

  useEffect(() => {
    const ws = wsRef.current;
    if (!ws || ws.getDuration() === 0) return;
    if (Math.abs(ws.getCurrentTime() - currentTime) > 0.05) ws.setTime(currentTime);
  }, [currentTime]);

  useEffect(() => {
    const ws = wsRef.current;
    if (!ws || ws.getDuration() === 0) return;
    ws.zoom(pxPerSec);
  }, [pxPerSec]);

  // Strg + Mausrad zoomt
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setPxPerSec(useReview.getState().pxPerSec * (e.deltaY < 0 ? 1.25 : 0.8));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [setPxPerSec]);

  const legend = useMemo(() => {
    const seen = new Set(cuts.map((c) => c.reason));
    return REASONS.filter((r) => seen.has(r));
  }, [cuts]);

  return (
    <section aria-label="Timeline" className="flex flex-col gap-2 rounded-2xl border border-line bg-panel px-4 pb-4 pt-3.5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="font-semibold">Timeline</div>
        <div className="flex flex-wrap gap-2.5 text-xs text-text-muted">
          {legend.map((r) => (
            <span key={r} className="inline-flex items-center gap-1.5">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: REASON_COLOR[r] }} />
              {REASON_LABEL[r]}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-0.5 bg-[#71717A]" />
            Szene
          </span>
        </div>
        <div className="ml-auto flex items-center gap-1.5 text-xs text-text-muted">
          <span className="font-mono">{fmtDuration(currentTime)} / {fmtDuration(duration)}</span>
          <span className="ml-2">Zoom</span>
          <Button size="sm" variant="secondary" isIconOnly aria-label="Herauszoomen" onPress={() => setPxPerSec(pxPerSec * 0.7)}>
            −
          </Button>
          <Button size="sm" variant="secondary" isIconOnly aria-label="Hineinzoomen" onPress={() => setPxPerSec(pxPerSec * 1.4)}>
            +
          </Button>
        </div>
      </div>
      <div ref={containerRef} className="rounded-lg bg-panel-dark" />
      <div className="text-[11px] text-text-faint">Klick in die Wellenform spult das Video · Strg + Mausrad zoomt · Klick auf einen Cut wählt ihn aus</div>
    </section>
  );
}
