"""Ebene A, Audio-Ereignisse: CLAP Zero-Shot auf 2-Sekunden-Fenstern (Hop 1 s) gegen die `audio_prompt`s aus
events.yaml. Hintergrundklassen (Sprechen, Stille) stehen mit im Softmax, damit ein Event gegen sie gewinnen muss."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..schema import Event, EventCatalog

MODEL = "laion/clap-htsat-unfused"
SR = 48000
WINDOW = 2.0
HOP = 1.0
MIN_PROB = 0.6
BATCH = 32
# Feste Vergleichsklassen für Sprache: ohne sie hält CLAP aufgeregtes Sprechen für Lachen
# (Talking-Head-Stream: 63 % der Fenster "laughter", mit diesen Klassen 8 %, Musik im Tanzvideo unverändert 95 %).
SPEECH_CONTRAST = ["a woman talking excitedly", "a man talking", "speech"]


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    x, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, sr


def resample(x: np.ndarray, sr: int, target: int = SR) -> np.ndarray:
    if sr == target:
        return x
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(sr, target)
    return resample_poly(x, target // g, sr // g).astype(np.float32)


def windows(n_samples: int, sr: int) -> list[tuple[int, int]]:
    w, h = int(WINDOW * sr), int(HOP * sr)
    if n_samples <= 0:
        return []
    starts = list(range(0, max(1, n_samples - w + 1), h))
    return [(s, min(n_samples, s + w)) for s in starts]


def probs_to_detections(probs: np.ndarray, starts: list[float], types: list[str], background: set[str]) -> list[Event]:
    """Pro Typ: zusammenhängende Fenster mit Wahrscheinlichkeit >= MIN_PROB -> eine Detektion (Quelle clap)."""
    out: list[Event] = []
    for j, t in enumerate(types):
        if t in background:
            continue
        run: list[int] = []
        for i in range(len(starts) + 1):
            hit = i < len(starts) and probs[i, j] >= MIN_PROB
            if hit:
                run.append(i)
                continue
            if run:
                a, b = starts[run[0]], starts[run[-1]] + WINDOW
                conf = float(probs[run, j].mean())
                out.append(Event(id=f"clap-{t}-{a:.1f}", type=t, start=round(a, 3), end=round(b, 3),
                                 confidence=round(conf, 3), sources=["clap"]))
                run = []
    return out


def detect(audio_path: Path, catalog: EventCatalog, device: str, progress: Callable[[float], None] | None = None,
           model_name: str = MODEL) -> list[Event]:
    defs = [d for d in catalog.events if d.audio_prompt]
    if not any(not d.background for d in defs):
        return []
    import torch
    from transformers import ClapModel, ClapProcessor

    x, sr = load_audio(audio_path)
    y = resample(x, sr)
    spans = windows(len(y), SR)
    model = ClapModel.from_pretrained(model_name).to(device).eval()
    processor = ClapProcessor.from_pretrained(model_name)
    try:
        prompts = [d.audio_prompt for d in defs] + SPEECH_CONTRAST
        text = processor(text=prompts, return_tensors="pt", padding=True).to(device)
        rows: list[np.ndarray] = []
        for b in range(0, len(spans), BATCH):
            clips = [y[s:e] for s, e in spans[b:b + BATCH]]
            audio = processor(audio=clips, sampling_rate=SR, return_tensors="pt").to(device)
            with torch.no_grad():
                out = model(**text, **audio)
            rows.append(out.logits_per_audio.softmax(-1).float().cpu().numpy())
            if progress:
                progress(min(1.0, (b + BATCH) / max(1, len(spans))))
        probs = np.concatenate(rows) if rows else np.zeros((0, len(prompts)))
    finally:
        del model
        if device == "cuda":
            torch.cuda.empty_cache()
    starts = [s / SR for s, _ in spans]
    types = [d.type for d in defs] + [f"_speech{i}" for i in range(len(SPEECH_CONTRAST))]
    background = {d.type for d in defs if d.background} | {t for t in types if t.startswith("_")}
    return probs_to_detections(probs, starts, types, background)
