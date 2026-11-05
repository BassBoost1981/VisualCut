"""Ebene A, Körperbewegung: RTMPose über rtmlib/ONNX bei 5 fps, MediaPipe Pose als CPU-Fallback.

Aus den Gelenkpositionen der Hauptperson entstehen pro Sample:
- Bewegungsenergie (mittlere Gelenkverschiebung in Personenhöhen pro Sekunde),
- Rumpfenergie (Verschiebung von Schulter-/Hüftmitte, Gestikulieren bewegt den Rumpf kaum),
- Periodizität der Rumpfbahn (Autokorrelation, Tanz-Indikator),
- Personenzahl.
Daraus Kandidaten für dancing, empty_frame, standing_up, sitting_down und Kandidatenfenster für Ebene B.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..schema import Event
from .frames import iter_frames, size_for

SAMPLE_FPS = 5.0
SHORT_SIDE = 360
KP_CONF = 0.3
DET_EVERY = 5                # Personendetektor einmal pro Sekunde, dazwischen Boxen aus den Gelenken
MAX_PERSONS = 2
PERSON_MIN_SCORE = 0.45
PERSON_MIN_HEIGHT = 0.2      # Anteil der Bildhöhe
BODY = list(range(5, 17))    # COCO-17 ohne Gesicht
TORSO = [5, 6, 11, 12]       # Schultern und Hüften
LOWER = [11, 12, 13, 14, 15, 16]  # Hüften, Knie, Knöchel
LOWER_CONF = 0.4
LOWER_MIN = 3

# Kalibriert an einem Tanzvideo und einem Talking-Head-Stream (2026-11-05): Ganzkörper- und Rumpfenergie
# unterscheiden die beiden kaum (Gestikulieren), die Unterkörperenergie schon (am Schreibtisch nicht sichtbar).
MOTION_THRESHOLD = 0.35      # Ganzkörperenergie, ab der eine Person "sich bewegt" (Regel 3 ohne Unterkörper)
LOWER_THRESHOLD = 0.08       # Unterkörperenergie für Tanzen/Gehen und für Regel 3
LOWER_VISIBLE = 0.5          # Anteil der Samples pro Sekunde mit sichtbarem Unterkörper
PERIOD_WINDOW = 8.0          # Sekunden
DANCE_MIN = 3.0              # Sekunden
DANCE_GAP = 2.0
EMPTY_MIN = 2.0
POSTURE_SHIFT = 0.12         # Anteil der Bildhöhe

Estimator = Callable[[np.ndarray], tuple[np.ndarray, np.ndarray]]


@dataclass
class PoseTrack:
    fps: float
    motion: np.ndarray
    torso: np.ndarray
    persons: np.ndarray
    center_y: np.ndarray
    lower: np.ndarray = field(default_factory=lambda: np.zeros(0))
    periodicity: np.ndarray = field(default_factory=lambda: np.zeros(0))
    backend: str = ""


# ---------------------------------------------------------------- Schätzer


def _rtmlib() -> tuple[Estimator, str]:
    import onnxruntime
    from rtmlib import RTMPose, YOLOX, Body

    device = "cuda" if "CUDAExecutionProvider" in onnxruntime.get_available_providers() else "cpu"
    cfg = Body.MODE["lightweight"]
    det = YOLOX(cfg["det"], model_input_size=cfg["det_input_size"], backend="onnxruntime", device=device)
    est = RTMPose(cfg["pose"], model_input_size=cfg["pose_input_size"], backend="onnxruntime", device=device)
    # Eigene Sessions ohne Spin-Wait: ORT hält sonst alle Kerne busy und bremst den ffmpeg-Decoder aus
    from rtmlib.tools.file import download_checkpoint

    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = max(1, min(8, (os.cpu_count() or 4) // 2))
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    providers = ["CUDAExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
    for tool, url in ((det, cfg["det"]), (est, cfg["pose"])):
        tool.session = onnxruntime.InferenceSession(download_checkpoint(url), sess_options=opts, providers=providers)
    state: dict = {"k": 0, "boxes": []}

    def run(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])  # rtmlib erwartet BGR
        h, w = bgr.shape[:2]
        if state["k"] % DET_EVERY == 0 or not state["boxes"]:
            boxes = [b for b in np.asarray(det(bgr)).reshape(-1, 4)]
            # nur die größten Personen (Spiegelbilder, Overlays und Zuschauer kosten sonst je einen Pose-Lauf)
            state["boxes"] = sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))[:MAX_PERSONS]
        state["k"] += 1
        if not state["boxes"]:
            return np.zeros((0, 17, 2), np.float32), np.zeros((0, 17), np.float32)
        kp, sc = est(bgr, bboxes=state["boxes"])
        kp, sc = np.asarray(kp, np.float32).reshape(-1, 17, 2), np.asarray(sc, np.float32).reshape(-1, 17)
        # Boxen bis zur nächsten Detektion aus den Gelenken nachführen
        boxes = []
        for k, s in zip(kp, sc):
            good = k[s >= KP_CONF]
            if len(good) < 4:
                continue
            (x0, y0), (x1, y1) = good.min(0), good.max(0)
            px, py = 0.15 * (x1 - x0), 0.15 * (y1 - y0)
            boxes.append(np.array([max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py)], np.float32))
        state["boxes"] = boxes
        return kp, sc

    return run, f"rtmlib/rtmpose ({device})"


MP_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/"
                "pose_landmarker_lite.task")
MP_TO_COCO = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]


def models_dir() -> Path:
    base = os.environ.get("VISUALCUT_MODELS") or os.path.join(os.environ.get("TORCH_HOME", str(Path.home() / ".cache")), "visualcut")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _mediapipe() -> tuple[Estimator, str]:
    import urllib.request

    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    model = models_dir() / "pose_landmarker_lite.task"
    if not model.exists():
        urllib.request.urlretrieve(MP_MODEL_URL, model)
    landmarker = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model)), running_mode=vision.RunningMode.VIDEO, num_poses=4,
    ))
    state = {"ts": 0}

    def run(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h, w = rgb.shape[:2]
        state["ts"] += int(1000 / SAMPLE_FPS)
        res = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)), state["ts"])
        kps, scs = [], []
        for person in res.pose_landmarks:
            kps.append([[person[i].x * w, person[i].y * h] for i in MP_TO_COCO])
            scs.append([float(person[i].visibility or 0.0) for i in MP_TO_COCO])
        return np.asarray(kps, np.float32).reshape(-1, 17, 2), np.asarray(scs, np.float32).reshape(-1, 17)

    return run, "mediapipe (cpu)"


def make_estimator() -> tuple[Estimator, str]:
    """RTMPose bevorzugt, MediaPipe als Fallback. ImportError, wenn keins von beiden installiert ist."""
    errors = []
    for factory in (_rtmlib, _mediapipe):
        try:
            return factory()
        except Exception as e:  # noqa: BLE001 - Fallback-Kette, Grund wird gemeldet
            errors.append(f"{factory.__name__.strip('_')}: {e}")
    raise ImportError("; ".join(errors))


# ---------------------------------------------------------------- Signale


def _persons(kp: np.ndarray, sc: np.ndarray, frame_h: int) -> list[tuple[np.ndarray, np.ndarray, float]]:
    out = []
    for k, s in zip(kp, sc):
        good = s >= KP_CONF
        if good.sum() < 4 or s.mean() < PERSON_MIN_SCORE:
            continue
        ys = k[good, 1]
        height = float(ys.max() - ys.min())
        if height < PERSON_MIN_HEIGHT * frame_h:
            continue
        out.append((k, s, height))
    return out


def _center(k: np.ndarray, s: np.ndarray) -> np.ndarray | None:
    idx = [i for i in TORSO if s[i] >= KP_CONF]
    if len(idx) < 2:
        return None
    return k[idx].mean(axis=0)


def track_signals(samples: list[tuple[np.ndarray, np.ndarray]], frame_h: int, fps: float = SAMPLE_FPS) -> PoseTrack:
    """Aus (Keypoints, Scores) pro Sample die Zeitreihen der Hauptperson."""
    n = len(samples)
    motion, torso, lower = np.zeros(n), np.zeros(n), np.zeros(n)
    persons = np.zeros(n, dtype=int)
    center_y = np.full(n, np.nan)
    cx_series, cy_series = np.full(n, np.nan), np.full(n, np.nan)
    prev: tuple[np.ndarray, np.ndarray, float] | None = None
    prev_c: np.ndarray | None = None
    for i, (kp, sc) in enumerate(samples):
        people = _persons(kp, sc, frame_h)
        persons[i] = len(people)
        if not people:
            prev, prev_c = None, None
            continue
        if prev_c is not None:  # gleiche Person wie im vorigen Sample, sonst die größte
            dist = [np.linalg.norm((_center(k, s) if _center(k, s) is not None else k.mean(0)) - prev_c) for k, s, _ in people]
            main = people[int(np.argmin(dist))]
            if min(dist) > 0.3 * frame_h:
                main, prev = max(people, key=lambda p: p[2]), None
        else:
            main = max(people, key=lambda p: p[2])
        k, s, height = main
        c = _center(k, s)
        if c is not None:
            center_y[i] = c[1] / frame_h
            cx_series[i], cy_series[i] = c[0] / height, c[1] / height
        if prev is not None:
            pk, ps, ph = prev
            good = [j for j in BODY if s[j] >= KP_CONF and ps[j] >= KP_CONF]
            h = (height + ph) / 2
            if good:
                motion[i] = float(np.linalg.norm(k[good] - pk[good], axis=1).mean() / h * fps)
            low = [j for j in LOWER if s[j] >= LOWER_CONF and ps[j] >= LOWER_CONF]
            if len(low) >= LOWER_MIN:  # Unterkörper sichtbar: Gestikulieren am Schreibtisch zählt nicht
                lower[i] = float(np.linalg.norm(k[low] - pk[low], axis=1).mean() / h * fps)
            pc = _center(pk, ps)
            if c is not None and pc is not None:
                torso[i] = float(np.linalg.norm(c - pc) / h * fps)
        prev, prev_c = main, c if c is not None else k.mean(0)
    track = PoseTrack(fps=fps, motion=motion, torso=torso, persons=persons, center_y=center_y, lower=lower)
    track.periodicity = periodicity(cx_series, cy_series, fps)
    return track


def _acf_peak(x: np.ndarray, min_lag: int, max_lag: int) -> float:
    x = x[~np.isnan(x)]
    if len(x) < max_lag + 4:
        return 0.0
    x = x - np.polyval(np.polyfit(np.arange(len(x)), x, 1), np.arange(len(x)))  # Trend raus (Gehen)
    var = float((x * x).sum())
    if var < 1e-9:
        return 0.0
    best = 0.0
    for lag in range(min_lag, max_lag + 1):
        best = max(best, float((x[:-lag] * x[lag:]).sum() / var))
    return best


def periodicity(cx: np.ndarray, cy: np.ndarray, fps: float = SAMPLE_FPS) -> np.ndarray:
    """Pro Sample: stärkste Autokorrelation der Rumpfbahn (x oder y) im Fenster von 8 s, Perioden 0,4 bis 3 s."""
    n = len(cx)
    half = int(PERIOD_WINDOW * fps / 2)
    lo, hi = max(2, int(0.4 * fps)), int(3.0 * fps)
    out = np.zeros(n)
    step = max(1, int(fps / 2))  # alle 0,5 s rechnen, dazwischen halten
    last = 0.0
    for i in range(n):
        if i % step == 0:
            a, b = max(0, i - half), min(n, i + half)
            last = max(_acf_peak(cx[a:b], lo, hi), _acf_peak(cy[a:b], lo, hi))
        out[i] = last
    return out


def smooth(x: np.ndarray, width: int) -> np.ndarray:
    if len(x) == 0 or width <= 1:
        return x.astype(float)
    k = np.ones(width) / width
    return np.convolve(x.astype(float), k, mode="same")


def _runs(flag: np.ndarray, max_gap: int = 0) -> list[tuple[int, int]]:
    """Zusammenhängende True-Bereiche [a, b) mit Lücken bis max_gap Samples."""
    runs: list[tuple[int, int]] = []
    i, n = 0, len(flag)
    while i < n:
        if not flag[i]:
            i += 1
            continue
        a = i
        while i < n and flag[i]:
            i += 1
        if runs and a - runs[-1][1] <= max_gap:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((a, i))
    return runs


def _ev(type_: str, start: float, end: float, conf: float) -> Event:
    return Event(id=f"pose-{type_}-{start:.1f}", type=type_, start=round(max(0.0, start), 3), end=round(end, 3),
                 confidence=round(float(min(1.0, max(0.0, conf))), 3), sources=["pose"])


def detections(track: PoseTrack) -> list[Event]:
    fps = track.fps
    out: list[Event] = []
    sec = max(1, int(fps))
    # Tanz-Kandidat: Unterkörper sichtbar und in Bewegung. Gehen erfüllt das auch, X-CLIP trennt die beiden.
    lo = smooth(track.lower, sec)
    vis = smooth((track.lower > 0).astype(float), sec)
    dance = (lo >= LOWER_THRESHOLD) & (vis >= LOWER_VISIBLE)
    dance_runs = [(a, b) for a, b in _runs(dance, max_gap=int(DANCE_GAP * fps)) if (b - a) / fps >= DANCE_MIN]
    for a, b in dance_runs:
        per = float(track.periodicity[a:b].mean()) if len(track.periodicity) else 0.0
        out.append(_ev("dancing", a / fps, b / fps, 0.4 + 0.4 * per))  # rhythmischer = sicherer
    for a, b in _runs(track.persons == 0, max_gap=1):
        if (b - a) / fps >= EMPTY_MIN:
            out.append(_ev("empty_frame", a / fps, b / fps, 0.7))
    # Haltungswechsel: Rumpfmitte springt dauerhaft um mehr als 12 % der Bildhöhe
    y = track.center_y
    w = int(2 * fps)
    last_t = -1e9
    for i in range(w, len(y) - w):
        before, after = y[i - w:i - w // 2], y[i + w // 2:i + w]
        if np.isnan(before).all() or np.isnan(after).all():
            continue
        d = float(np.nanmean(after) - np.nanmean(before))
        if any(a <= i < b for a, b in dance_runs):
            continue  # beim Tanzen springt die Rumpfmitte ständig
        if abs(d) >= POSTURE_SHIFT and i / fps - last_t > 3.0:
            last_t = i / fps
            out.append(_ev("sitting_down" if d > 0 else "standing_up", i / fps - 1.0, i / fps + 1.0,
                           min(0.8, 0.4 + abs(d))))
    return out


def candidate_windows(track: PoseTrack, pad: float = 1.0) -> list[tuple[float, float]]:
    """Fenster für Ebene B: deutliche Bewegung, Unterkörper in Bewegung oder Personenzahl ändert sich."""
    fps = track.fps
    sec = max(1, int(fps))
    flag = (smooth(track.motion, 2 * sec) >= MOTION_THRESHOLD) | (smooth(track.lower, sec) >= LOWER_THRESHOLD)
    change = np.zeros(len(flag), dtype=bool)
    change[1:] = track.persons[1:] != track.persons[:-1]
    flag |= change
    return [(max(0.0, a / fps - pad), b / fps + pad) for a, b in _runs(flag, max_gap=int(2 * fps))]


def analyze(proxy: Path, width: int, height: int, duration: float, progress: Callable[[float], None] | None = None,
            estimator: tuple[Estimator, str] | None = None) -> PoseTrack:
    est, backend = estimator or make_estimator()
    w, h = size_for(width, height, SHORT_SIDE)
    samples = []
    total = max(1, int(duration * SAMPLE_FPS))
    for k, (_t, frame) in enumerate(iter_frames(proxy, SAMPLE_FPS, w, h)):
        samples.append(est(frame))
        if progress and k % 50 == 0:
            progress(min(1.0, k / total))
    track = track_signals(samples, h)
    track.backend = backend
    return track
