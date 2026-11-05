import { Button, Kbd } from "@heroui/react";
import { useEffect, useState, type RefObject } from "react";
import type { Cut } from "../api/types";
import { fmtTimecode } from "../lib/format";
import { REASON_COLOR, REASON_LABEL } from "../lib/reasons";

interface Props {
  src: string;
  fps: number;
  videoRef: RefObject<HTMLVideoElement | null>;
  currentTime: number;
  activeCut: Cut | null;
  onPrevCut: () => void;
  onNextCut: () => void;
}

/** HTML-Video auf dem H.264-Proxy. Transport J/K/L und Leertaste kommen aus Review.tsx (Hotkeys). */
export function Player({ src, fps, videoRef, currentTime, activeCut, onPrevCut, onNextCut }: Props) {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const on = () => setPlaying(!v.paused);
    v.addEventListener("play", on);
    v.addEventListener("pause", on);
    return () => {
      v.removeEventListener("play", on);
      v.removeEventListener("pause", on);
    };
  }, [videoRef]);

  const toggle = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
  };

  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-line bg-black">
      <div className="relative aspect-video bg-[#0a0a0a]">
        <video ref={videoRef} src={src} className="h-full w-full" preload="metadata" playsInline onClick={toggle} />
        <div className="pointer-events-none absolute bottom-3 left-4 rounded-lg bg-black/60 px-2.5 py-1 font-mono text-[13px]">
          {fmtTimecode(currentTime, fps)}
        </div>
        {activeCut && (
          <div
            className="pointer-events-none absolute right-4 top-3 rounded-full px-2.5 py-1 text-[11px] font-semibold text-[#09090b]"
            style={{ background: REASON_COLOR[activeCut.reason] }}
          >
            im Cut: {REASON_LABEL[activeCut.reason]}
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-line bg-panel-dark px-3.5 py-2.5">
        <Button size="sm" variant="secondary" isIconOnly aria-label="Zum vorherigen Cut" onPress={onPrevCut}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 20L9 12l10-8zM5 19V5" /></svg>
        </Button>
        <Button size="sm" variant="secondary" isIconOnly aria-label="Rückwärts (J)" onPress={() => seekBy(videoRef, -5)}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M11 19l-9-7 9-7zM22 19l-9-7 9-7z" /></svg>
        </Button>
        <Button variant="primary" isIconOnly aria-label={playing ? "Pause (Leertaste)" : "Abspielen (Leertaste)"} onPress={toggle}>
          {playing ? (
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z" /></svg>
          ) : (
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4l12 8-12 8z" /></svg>
          )}
        </Button>
        <Button size="sm" variant="secondary" isIconOnly aria-label="Vorwärts (L)" onPress={() => seekBy(videoRef, 5)}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M13 5l9 7-9 7zM2 5l9 7-9 7z" /></svg>
        </Button>
        <Button size="sm" variant="secondary" isIconOnly aria-label="Zum nächsten Cut" onPress={onNextCut}>
          <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4l10 8-10 8zM19 5v14" /></svg>
        </Button>
        <div className="ml-auto flex flex-wrap items-center gap-1.5 text-xs text-text-muted">
          <Kbd>J</Kbd>
          <Kbd>K</Kbd>
          <Kbd>L</Kbd>
          <span>Transport</span>
          <Kbd className="ml-2">A</Kbd>
          <span>Annehmen</span>
          <Kbd>R</Kbd>
          <span>Verwerfen</span>
          <Kbd>O</Kbd>
          <span>Offen</span>
          <Kbd className="ml-2">↑</Kbd>
          <Kbd>↓</Kbd>
          <span>Cut wechseln</span>
        </div>
      </div>
    </div>
  );
}

export function seekBy(videoRef: RefObject<HTMLVideoElement | null>, delta: number): void {
  const v = videoRef.current;
  if (!v) return;
  v.currentTime = Math.max(0, Math.min(v.duration || Infinity, v.currentTime + delta));
}
