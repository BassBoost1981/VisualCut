"""Ebene B, Aktionserkennung: X-CLIP Zero-Shot auf 2-Sekunden-Clips, VideoMAE (Kinetics-400) als zweite Meinung.

Clips kommen aus den Kandidatenfenstern von Ebene A (Bewegung, Personenzahl, Audio-Events, Szenenwechsel),
dazu ein Grobraster mit einem Clip alle 10 Sekunden, damit stille Ereignisse (Produkt in die Kamera halten)
nicht fehlen. Modelle werden nacheinander geladen und wieder entladen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..schema import Event, EventCatalog
from .frames import read_frames, size_for

XCLIP_MODEL = "microsoft/xclip-base-patch32"
VIDEOMAE_MODEL = "MCG-NJU/videomae-base-finetuned-kinetics"
CLIP_LEN = 2.0
CLIP_HOP = 2.0
GRID = 10.0
XCLIP_FRAMES = 8
MAE_FRAMES = 16
MAE_SPAN = 4.0
SHORT_SIDE = 224
XCLIP_MIN = 0.4          # ab hier wird der Top-Typ eines Clips zur Detektion
MAE_CHECK_MIN = 0.3      # ab hier prüft VideoMAE den X-CLIP-Typ nach
MAE_MIN = 0.15           # Summe der passenden Kinetics-Klassen für eine Bestätigung
MAE_MAX_CLIPS = 60
BATCH = 8


@dataclass
class ClipScore:
    start: float
    end: float
    probs: dict[str, float]

    def top(self, background: set[str]) -> tuple[str, float]:
        """Wahrscheinlichster Typ, Hintergrund eingeschlossen."""
        t = max(self.probs, key=lambda k: self.probs[k])
        return t, self.probs[t]


def plan_clips(duration: float, windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """2-Sekunden-Clips: lückenlos über die Kandidatenfenster, dazu alle 10 s einer. Doppelte (< 1 s Abstand) fallen weg."""
    starts: list[float] = []
    for a, b in windows:
        t = max(0.0, a)
        while t + CLIP_LEN <= min(b, duration) + 1e-6:
            starts.append(round(t, 3))
            t += CLIP_HOP
    t = GRID / 2 - CLIP_LEN / 2
    while t + CLIP_LEN <= duration + 1e-6:
        starts.append(round(t, 3))
        t += GRID
    out: list[float] = []
    for s in sorted(starts):
        if not out or s - out[-1] >= 1.0:
            out.append(s)
    if not out and duration > 0:
        out.append(0.0)
    return [(s, min(duration, s + CLIP_LEN)) for s in out]


def xclip_scores(proxy: Path, width: int, height: int, clips: list[tuple[float, float]], catalog: EventCatalog,
                 device: str, progress: Callable[[float], None] | None = None, model_name: str = XCLIP_MODEL) -> list[ClipScore]:
    defs = [d for d in catalog.events if d.prompt]
    if not clips or not any(not d.background for d in defs):
        return []
    import torch
    from transformers import AutoProcessor, XCLIPModel

    w, h = size_for(width, height, SHORT_SIDE)
    model = XCLIPModel.from_pretrained(model_name).to(device).eval()
    processor = AutoProcessor.from_pretrained(model_name)
    prompts = [d.prompt for d in defs]
    out: list[ClipScore] = []
    try:
        for b in range(0, len(clips), BATCH):
            batch = clips[b:b + BATCH]
            videos = [read_frames(proxy, s, e, XCLIP_FRAMES, w, h) for s, e in batch]
            keep = [(c, v) for c, v in zip(batch, videos) if len(v) == XCLIP_FRAMES]
            if not keep:
                continue
            inputs = processor(text=prompts, videos=[list(v) for _, v in keep], return_tensors="pt", padding=True).to(device)
            with torch.no_grad():
                probs = model(**inputs).logits_per_video.softmax(-1).float().cpu().numpy()
            for (s, e), p in zip([c for c, _ in keep], probs):
                out.append(ClipScore(s, e, {d.type: round(float(p[j]), 4) for j, d in enumerate(defs)}))
            if progress:
                progress(min(1.0, (b + BATCH) / len(clips)))
    finally:
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
    return out


def xclip_detections(scores: list[ClipScore], catalog: EventCatalog) -> list[Event]:
    background = {d.type for d in catalog.events if d.background}
    out = []
    for c in scores:
        t, p = c.top(background)
        if t in background or p < XCLIP_MIN:
            continue
        out.append(Event(id=f"xclip-{t}-{c.start:.1f}", type=t, start=c.start, end=c.end, confidence=round(p, 3),
                         sources=["xclip"]))
    return out


def videomae_targets(scores: list[ClipScore], catalog: EventCatalog, extra: list[Event]) -> list[tuple[float, float, str]]:
    """Clips, die VideoMAE nachprüft: X-CLIP-Top-Typ mit Kinetics-Liste ab 0,3, plus Ebene-A-Kandidaten mit Kinetics-Liste."""
    kin = {d.type for d in catalog.events if d.kinetics and not d.background}
    targets: list[tuple[float, float, str]] = []
    for c in scores:
        t, p = c.top(set())
        if t in kin and p >= MAE_CHECK_MIN:
            targets.append((c.start, c.end, t))
    for ev in extra:
        if ev.type in kin:
            mid = (ev.start + ev.end) / 2
            for t0 in (ev.start + 1.0, mid, ev.end - 3.0):
                if ev.start <= t0 and t0 + CLIP_LEN <= ev.end + 1e-6:
                    targets.append((t0, t0 + CLIP_LEN, ev.type))
    seen: set[tuple[int, str]] = set()
    uniq = []
    for s, e, t in sorted(targets):
        key = (int(s), t)
        if key not in seen:
            seen.add(key)
            uniq.append((s, e, t))
    if len(uniq) > MAE_MAX_CLIPS:  # gleichmäßig ausdünnen statt nur den Anfang zu prüfen
        idx = np.linspace(0, len(uniq) - 1, MAE_MAX_CLIPS).round().astype(int)
        uniq = [uniq[i] for i in sorted(set(idx))]
    return uniq


def kinetics_score(probs: np.ndarray, labels: dict[int, str], keywords: list[str]) -> float:
    kws = [k.lower() for k in keywords]
    return float(sum(p for i, p in enumerate(probs) if any(k in labels[i].lower() for k in kws)))


def videomae_detections(proxy: Path, width: int, height: int, targets: list[tuple[float, float, str]],
                        catalog: EventCatalog, duration: float, device: str,
                        progress: Callable[[float], None] | None = None, model_name: str = VIDEOMAE_MODEL) -> list[Event]:
    if not targets:
        return []
    import torch
    from transformers import AutoImageProcessor, VideoMAEForVideoClassification

    kw = {d.type: d.kinetics for d in catalog.events}
    w, h = size_for(width, height, SHORT_SIDE)
    model = VideoMAEForVideoClassification.from_pretrained(model_name).to(device).eval()
    processor = AutoImageProcessor.from_pretrained(model_name)
    labels = {int(k): v for k, v in model.config.id2label.items()}
    out: list[Event] = []
    try:
        for k, (s, e, t) in enumerate(targets):
            mid = (s + e) / 2
            a = max(0.0, min(mid - MAE_SPAN / 2, duration - MAE_SPAN))
            frames = read_frames(proxy, a, a + MAE_SPAN, MAE_FRAMES, w, h)
            if len(frames) != MAE_FRAMES:
                continue
            inputs = processor(list(frames), return_tensors="pt").to(device)
            with torch.no_grad():
                probs = model(**inputs).logits.softmax(-1)[0].float().cpu().numpy()
            score = kinetics_score(probs, labels, kw.get(t, []))
            if score >= MAE_MIN:
                out.append(Event(id=f"videomae-{t}-{s:.1f}", type=t, start=s, end=e, confidence=round(min(1.0, score), 3),
                                 sources=["videomae"]))
            if progress:
                progress((k + 1) / len(targets))
    finally:
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
    return out
