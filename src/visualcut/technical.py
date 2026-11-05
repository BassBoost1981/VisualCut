"""Stufe 1: Stille (ffmpeg silencedetect) und Szenenwechsel (PySceneDetect). Nur Messung."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .cache import ProgressFn, ProjectCache, emit
from .ingest import StageError
from .schema import MediaInfo, SceneChange, SilenceInterval, Stage, TechnicalResult

SILENCE_DB = -35.0
SILENCE_MIN = 0.15


def detect_silence(audio: Path, duration: float, threshold_db: float = SILENCE_DB, min_duration: float = SILENCE_MIN) -> list[SilenceInterval]:
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-nostats", "-i", str(audio), "-af", f"silencedetect=n={threshold_db}dB:d={min_duration}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise StageError(f"silencedetect fehlgeschlagen: {proc.stderr[-1000:]}")
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", proc.stderr)]
    out: list[SilenceInterval] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        out.append(SilenceInterval(start=max(0.0, s), end=max(max(0.0, s), e)))
    return out


def detect_scenes(proxy: Path, fps: float) -> list[SceneChange]:
    from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video

    found: dict[int, set[str]] = {}
    for name, det in (("content", ContentDetector(threshold=27.0)), ("adaptive", AdaptiveDetector())):
        video = open_video(str(proxy))
        sm = SceneManager()
        sm.add_detector(det)
        sm.detect_scenes(video)
        for cut in sm.get_cut_list():
            found.setdefault(cut.get_frames(), set()).add(name)
    return [
        SceneChange(frame=f, time=f / fps, detector="+".join(sorted(names)))
        for f, names in sorted(found.items())
    ]


def analyze_technical(media: MediaInfo, cache: ProjectCache, progress: ProgressFn | None = None, force: bool = False) -> TechnicalResult:
    stage = Stage.technical
    if cache.has(stage) and not force:
        emit(progress, "stage_skipped", stage, "Cache vorhanden")
        return cache.load(stage, TechnicalResult)
    emit(progress, "stage_start", stage)
    silences: list[SilenceInterval] = []
    if media.audio_path:
        silences = detect_silence(Path(media.audio_path), media.duration)
    emit(progress, "progress", stage, f"{len(silences)} Stille-Intervalle", 40)
    if not media.proxy_path:
        raise StageError("Kein Proxy vorhanden, Stufe 0 zuerst")
    scenes = detect_scenes(Path(media.proxy_path), media.fps)
    emit(progress, "progress", stage, f"{len(scenes)} Szenenwechsel", 95)
    result = TechnicalResult(silences=silences, scenes=scenes, silence_threshold_db=SILENCE_DB, silence_min_duration=SILENCE_MIN)
    cache.save(stage, result)
    emit(progress, "stage_done", stage)
    return result
