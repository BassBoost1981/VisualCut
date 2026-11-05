"""Stufe 1b: Ereigniserkennung (PLAN.md Abschnitt 3, Stufe 1b).

Kaskade aus drei Ebenen, Modelle nacheinander geladen und entladen (VRAM):
- Ebene A, immer über das ganze Video: Pose (RTMPose/rtmlib, MediaPipe als Fallback) und CLAP (Audio).
- Ebene B, auf Kandidatenfenstern plus Grobraster: X-CLIP Zero-Shot, VideoMAE (Kinetics-400) als Bestätigung.
- Ebene C, nur bei Unsicherheit: Claude mit Einzelbildern, hartes Budget. Ohne API-Key bleiben die Fenster
  offen, der steuernde Agent kann sie beurteilen (`apply_judgments`).
Ergebnis ist `events.json` (EventsResult). Abhängigkeiten im Extra `events`; fehlen sie, wird die Stufe übersprungen.
"""

from __future__ import annotations

import contextlib
import importlib.util
import sys
from pathlib import Path

import numpy as np

from ..cache import ProgressFn, ProjectCache, emit
from ..ingest import StageError
from ..schema import (
    EventJudgments, EventsResult, EventStatus, EventWindow, MediaInfo, Stage, TechnicalResult,
)
from ..semantic import DEFAULT_MODEL
from . import catalog as catalog_mod
from .fuse import fuse_events

STAGE = Stage.events


def device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def missing() -> str | None:
    """Grund, warum die Stufe nicht laufen kann, sonst None."""
    has = {m: importlib.util.find_spec(m) is not None for m in ("rtmlib", "mediapipe", "transformers", "torch")}
    if not (has["rtmlib"] or has["mediapipe"]) and not (has["transformers"] and has["torch"]):
        return "weder rtmlib/mediapipe noch transformers/torch installiert, uv sync --extra events"
    return None


def merge_windows(spans: list[tuple[float, float]], duration: float, gap: float = 1.0) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted((max(0.0, a), min(duration, b)) for a, b in spans if b > a):
        if out and a <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def refuse(cache: ProjectCache, result: EventsResult, progress: ProgressFn | None = None) -> EventsResult:
    """Nur die Fusion neu (Label, Wirkung, Urteile), ohne Modelle."""
    events = fuse_events(result, catalog_mod.load(cache))
    if [e.model_dump() for e in events] != [e.model_dump() for e in result.events]:
        result.events = events
        cache.save(STAGE, result)
        emit(progress, "log", STAGE, "Events neu fusioniert (events.yaml oder Urteile geändert)")
    return result


def _layer(result: EventsResult, name: str, fn, progress: ProgressFn | None):
    """Eine Ebene ausführen; ein Fehler (Modell-Download, fehlendes Paket) überspringt nur diese Ebene."""
    try:
        return fn()
    except StageError:
        raise
    except Exception as e:  # noqa: BLE001 - Grund landet in layers und im Log
        result.layers[name] = f"übersprungen: {type(e).__name__}: {e}"[:300]
        emit(progress, "log", STAGE, f"{name} übersprungen: {e}")
        return None


def detect_events(
    media: MediaInfo, technical: TechnicalResult, cache: ProjectCache, progress: ProgressFn | None = None,
    force: bool = False, enabled: bool = True, vision: bool = True, budget: int | None = None,
    vision_model: str = DEFAULT_MODEL, client=None,
) -> EventsResult | None:
    """Stufe 1b. None, wenn übersprungen (--no-events oder Extra fehlt).
    stdout ist während der Modellarbeit auf stderr umgeleitet: rtmlib und transformers drucken Ladehinweise, und
    stdout gehört dem JSON (`--json`) bzw. dem MCP-Protokoll."""
    with contextlib.redirect_stdout(sys.stderr):
        return _detect_events(media, technical, cache, progress, force, enabled, vision, budget, vision_model, client)


def _detect_events(media, technical, cache, progress, force, enabled, vision, budget, vision_model, client):
    from . import action, audio_tags, pose, vision_llm

    cat = catalog_mod.load(cache)
    dh = catalog_mod.detection_hash(cat)
    if cache.has(STAGE) and not force:
        cached = cache.load(STAGE, EventsResult)
        if cached.detection_hash == dh:
            emit(progress, "stage_skipped", STAGE, "Cache vorhanden")
            return refuse(cache, cached, progress)
        emit(progress, "log", STAGE, "events.yaml geändert (Prompts), Stufe 1b wird neu gerechnet")
    if not enabled:
        emit(progress, "stage_skipped", STAGE, "Ereigniserkennung deaktiviert (--no-events)")
        return None
    why = missing()
    if why:
        emit(progress, "stage_skipped", STAGE, f"Extra fehlt: {why}")
        return None
    if not media.proxy_path:
        raise StageError("Kein Proxy vorhanden, Stufe 0 zuerst")
    emit(progress, "stage_start", STAGE)
    proxy = Path(media.proxy_path)
    dev = device()
    result = EventsResult(detection_hash=dh, vision_budget=cat.vision_budget if budget is None else budget,
                          motion_fps=pose.SAMPLE_FPS)
    spans: list[tuple[float, float]] = []

    def pct(lo: float, hi: float, what: str):
        return lambda f: emit(progress, "progress", STAGE, what, lo + (hi - lo) * f)

    # Ebene A: Pose
    track = _layer(result, "pose", lambda: pose.analyze(proxy, media.width, media.height, media.duration,
                                                         pct(2, 30, "Pose")), progress)
    pose_dets = []
    if track is not None:
        result.motion = [round(float(x), 3) for x in track.motion]
        result.motion_lower = [round(float(x), 3) for x in track.lower]
        pose_dets = pose.detections(track)
        result.detections += pose_dets
        spans += pose.candidate_windows(track) + [(d.start, d.end) for d in pose_dets]
        result.layers["pose"] = f"ok ({track.backend}, {len(pose_dets)} Kandidaten)"
    # Ebene A: Audio
    if media.audio_path:
        emit(progress, "progress", STAGE, "Audio-Ereignisse (CLAP)", 30)
        clap = _layer(result, "clap", lambda: audio_tags.detect(Path(media.audio_path), cat, dev, pct(30, 45, "CLAP")), progress)
        if clap is not None:
            result.detections += clap
            spans += [(d.start - 1, d.end + 1) for d in clap if d.type in {x.type for x in cat.events if x.prompt}]
            result.layers["clap"] = f"ok ({len(clap)} Detektionen)"
    else:
        result.layers["clap"] = "übersprungen: keine Tonspur"
    spans += [(s.time - 1, s.time + 1) for s in technical.scenes if "content" in s.detector]
    windows = merge_windows(spans, media.duration)
    # Ebene B: X-CLIP auf Kandidatenfenstern plus Raster, VideoMAE als zweite Meinung
    clips = action.plan_clips(media.duration, windows)
    emit(progress, "progress", STAGE, f"X-CLIP auf {len(clips)} Clips", 45)
    scores = _layer(result, "xclip", lambda: action.xclip_scores(proxy, media.width, media.height, clips, cat, dev,
                                                                  pct(45, 70, "X-CLIP")), progress) or []
    if "xclip" not in result.layers:
        xd = action.xclip_detections(scores, cat)
        result.detections += xd
        result.layers["xclip"] = f"ok ({len(scores)} Clips, {len(xd)} Detektionen)"
    targets = action.videomae_targets(scores, cat, pose_dets)
    emit(progress, "progress", STAGE, f"VideoMAE auf {len(targets)} Clips", 70)
    mae = _layer(result, "videomae", lambda: action.videomae_detections(
        proxy, media.width, media.height, targets, cat, media.duration, dev, pct(70, 85, "VideoMAE")), progress)
    if mae is not None:
        result.detections += mae
        result.layers["videomae"] = f"ok ({len(targets)} Clips, {len(mae)} Bestätigungen)"
    # Ebene C: unklare und widersprüchliche Fenster
    result.windows = vision_llm.uncertain_windows(scores, cat, np.asarray(result.motion_lower), result.motion_fps,
                                                  pose.LOWER_THRESHOLD)
    _judge(result, cat, proxy, media, cache, vision, vision_model, client, progress)
    result.events = fuse_events(result, cat)
    # Zweite Runde Ebene C: Beschreibung für bestätigte Highlight-Events (geht an Stufe 3), aus dem Restbudget
    extra = [EventWindow(id=f"w-{len(result.windows) + k + 1}", start=e.start, end=min(e.end, e.start + vision_llm.WINDOW_MAX),
                         candidates=[e.type], reason="Beschreibung für Highlight")
             for k, e in enumerate(x for x in result.events if x.status == EventStatus.confirmed
                                   and x.effect.value == "highlight" and not x.description)]
    if extra:
        result.windows += extra
        _judge(result, cat, proxy, media, cache, vision, vision_model, client, progress, windows=extra)
        result.events = fuse_events(result, cat)
    open_w = sum(w.judged_by is None for w in result.windows)
    if vision and result.vision_calls == 0 and open_w:
        result.layers["vision"] = f"übersprungen: kein API-Key oder Budget 0, {open_w} Fenster offen für den Agenten"
    elif vision and result.windows:
        result.layers["vision"] = f"ok ({result.vision_calls} Aufrufe, Budget {result.vision_budget}, {open_w} Fenster offen)"
    cache.save(STAGE, result)
    n_conf = sum(e.status == EventStatus.confirmed for e in result.events)
    emit(progress, "stage_done", STAGE,
         f"{n_conf} bestätigt, {len(result.events) - n_conf} Kandidaten, {open_w} Fenster offen")
    return result


def _judge(result: EventsResult, cat, proxy: Path, media: MediaInfo, cache: ProjectCache, vision: bool,
           vision_model: str, client, progress: ProgressFn | None, windows: list[EventWindow] | None = None) -> None:
    from . import vision_llm

    todo = windows if windows is not None else result.windows
    for w in todo:
        if not w.frames:
            w.frames = vision_llm.extract_frames(proxy, media.width, media.height, w, cache.path("event_frames"))
    if not vision:
        result.layers["vision"] = "übersprungen: --no-vision"
        return
    budget = max(0, result.vision_budget - result.vision_calls)
    judged, calls, status = vision_llm.judge(todo, cat, budget, vision_model, client, progress)
    result.judgments += judged
    result.vision_calls += calls
    result.layers["vision"] = status


def apply_judgments(cache: ProjectCache, submission: EventJudgments,
                    progress: ProgressFn | None = None) -> tuple[EventsResult, int]:
    """Ebene C vom steuernden Agenten: Urteile zu offenen Fenstern. Unbekannte Fenster oder Typen werden
    verworfen und gezählt, nicht korrigiert. Gibt (neues Ergebnis, verworfen) zurück."""
    from .vision_llm import allowed_types

    if not cache.has(STAGE):
        raise StageError("Keine Ereigniserkennung im Cache, zuerst: visualcut events <video>")
    result = cache.load(STAGE, EventsResult)
    cat = catalog_mod.load(cache)
    windows = {w.id: w for w in result.windows}
    allowed = set(allowed_types(cat)) | {"none"}
    source = submission.source if submission.source.startswith("agent") else f"agent:{submission.source}"
    valid, rejected = [], 0
    for j in submission.judgments:
        if j.window_id not in windows or j.type not in allowed:
            rejected += 1
            emit(progress, "log", STAGE, f"verworfen: Fenster {j.window_id!r} oder Typ {j.type!r} unbekannt")
            continue
        valid.append(j)
        windows[j.window_id].judged_by = source
    ids = {j.window_id for j in valid}
    result.judgments = [j for j in result.judgments if j.window_id not in ids] + valid
    result.events = fuse_events(result, cat)
    cache.save(STAGE, result)
    emit(progress, "stage_done", STAGE, f"{len(valid)} Urteile übernommen, {rejected} verworfen")
    return result, rejected
