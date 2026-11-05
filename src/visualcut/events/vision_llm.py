"""Ebene C: Vision-LLM nur bei Unsicherheit. Claude bekommt 4 bis 8 Frames pro Fenster und antwortet mit einem
Typ aus events.yaml (oder `none`), Konfidenz und Kurzbeschreibung, nie mit Zeitangaben.

Fenster entstehen, wenn X-CLIP zwischen 0,4 und 0,7 liegt oder Ebene A und B sich widersprechen (Unterkörper in
Bewegung, X-CLIP sagt Hintergrund). Hartes Budget pro Video (Standard 40). Ohne ANTHROPIC_API_KEY wird nichts
aufgerufen; die Fenster bleiben offen, und der steuernde Agent kann sie beurteilen (`visualcut events --judge`).
"""

from __future__ import annotations

import base64
from pathlib import Path

import numpy as np

from ..cache import ProgressFn, emit
from ..ingest import StageError
from ..schema import EventCatalog, EventJudgment, EventWindow, LLMEventJudgment, Stage
from ..semantic import API_KEY_ENV, DEFAULT_MODEL, has_api_key, load_prompt
from .action import ClipScore
from .frames import read_frames, size_for

PROMPT_VERSION = "vision_event_v1"
UNSURE_LOW, UNSURE_HIGH = 0.4, 0.7
FRAMES = 6
SHORT_SIDE = 512
WINDOW_MAX = 8.0
MAX_OUTPUT_TOKENS = 1000


def uncertain_windows(scores: list[ClipScore], catalog: EventCatalog, lower: np.ndarray, motion_fps: float,
                      lower_threshold: float) -> list[EventWindow]:
    """Unklare und widersprüchliche Clips, benachbarte mit gleichen Kandidaten zu Fenstern bis 8 s vereint."""
    background = {d.type for d in catalog.events if d.background}
    flagged: list[tuple[float, float, tuple[str, ...], str]] = []
    for c in scores:
        t, p = c.top(background)
        if t not in background and UNSURE_LOW <= p <= UNSURE_HIGH:
            flagged.append((c.start, c.end, (t,), f"X-CLIP unsicher ({t} {p:.2f})"))
            continue
        if t in background and len(lower):
            a, b = int(c.start * motion_fps), max(int(c.start * motion_fps) + 1, int(c.end * motion_fps))
            seg = lower[a:b]
            if len(seg) and float(seg.mean()) >= lower_threshold:
                ranked = sorted((k for k in c.probs if k not in background), key=lambda k: -c.probs[k])[:2]
                if ranked:
                    flagged.append((c.start, c.end, tuple(ranked), f"Widerspruch: Bewegung, X-CLIP sagt {t}"))
    windows: list[EventWindow] = []
    for s, e, cand, why in sorted(flagged):
        last = windows[-1] if windows else None
        if last and tuple(last.candidates) == cand and s - last.end <= 0.5 and e - last.start <= WINDOW_MAX:
            last.end = e
            continue
        windows.append(EventWindow(id=f"w-{len(windows) + 1}", start=s, end=e, candidates=list(cand), reason=why))
    return windows


def extract_frames(proxy: Path, width: int, height: int, window: EventWindow, out_dir: Path) -> list[str]:
    import cv2

    w, h = size_for(width, height, SHORT_SIDE)
    if w > h and w > 912:  # lange Seite begrenzen, 512 px kurze Seite reicht
        w, h = size_for(width, height, int(SHORT_SIDE * 912 / w))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, f in enumerate(read_frames(proxy, window.start, window.end, FRAMES, w, h)):
        p = out_dir / f"{window.id}_{k}.jpg"
        cv2.imwrite(str(p), np.ascontiguousarray(f[:, :, ::-1]), [cv2.IMWRITE_JPEG_QUALITY, 85])
        paths.append(str(p))
    return paths


def allowed_types(catalog: EventCatalog) -> list[str]:
    return [d.type for d in catalog.events if not d.background and d.prompt]


def validate(answer: LLMEventJudgment, window: EventWindow, catalog: EventCatalog,
             progress: ProgressFn | None = None) -> EventJudgment | None:
    """Typ muss in events.yaml stehen (oder none), Konfidenz in [0, 1]. Ungültiges wird verworfen und geloggt."""
    t = answer.type.strip()
    if t != "none" and t not in allowed_types(catalog):
        emit(progress, "log", Stage.events, f"verworfen ({window.id}): unbekannter Typ {t!r}")
        return None
    if not 0.0 <= answer.confidence <= 1.0:
        emit(progress, "log", Stage.events, f"verworfen ({window.id}): confidence {answer.confidence} außerhalb [0,1]")
        return None
    return EventJudgment(window_id=window.id, type=t, confidence=round(answer.confidence, 3),
                         description=answer.description.strip())


def _user_content(window: EventWindow, catalog: EventCatalog) -> list[dict]:
    labels = {d.type: d.label for d in catalog.events}
    content: list[dict] = []
    for p in window.frames:
        data = base64.standard_b64encode(Path(p).read_bytes()).decode()
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    cands = ", ".join(f"{t} ({labels.get(t, t)})" for t in window.candidates)
    allowed = ", ".join(allowed_types(catalog))
    content.append({"type": "text", "text": f"Fraglich: {cands}. Grund: {window.reason}.\nErlaubte Typen: {allowed}, none."})
    return content


def call_model(client, model: str, system: str, window: EventWindow, catalog: EventCatalog) -> LLMEventJudgment:
    import anthropic

    try:
        response = client.messages.parse(
            model=model, max_tokens=MAX_OUTPUT_TOKENS, system=system,
            messages=[{"role": "user", "content": _user_content(window, catalog)}], output_format=LLMEventJudgment,
        )
    except anthropic.APIStatusError as e:
        raise StageError(f"Claude API {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise StageError(f"Claude API nicht erreichbar: {e}") from e
    if response.parsed_output is None:
        raise StageError(f"Vision-Antwort unvollständig (stop_reason={response.stop_reason})")
    return response.parsed_output


def judge(windows: list[EventWindow], catalog: EventCatalog, budget: int, model: str = DEFAULT_MODEL, client=None,
          progress: ProgressFn | None = None) -> tuple[list[EventJudgment], int, str]:
    """Höchstens `budget` Aufrufe, unsicherste Fenster zuerst. Gibt (Urteile, Aufrufe, Status) zurück."""
    open_windows = [w for w in windows if w.judged_by is None and w.frames]
    if not open_windows:
        return [], 0, "keine unklaren Fenster"
    if client is None and not has_api_key():
        return [], 0, f"übersprungen: {API_KEY_ENV} nicht gesetzt, {len(open_windows)} Fenster offen für den Agenten"
    if budget <= 0:
        return [], 0, f"übersprungen: Budget 0, {len(open_windows)} Fenster offen"
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    system = load_prompt(PROMPT_VERSION)
    out: list[EventJudgment] = []
    calls = 0
    for w in open_windows[:budget]:
        calls += 1
        emit(progress, "progress", Stage.events, f"Vision-LLM {calls}/{min(budget, len(open_windows))}: {w.id}")
        j = validate(call_model(client, model, system, w, catalog), w, catalog, progress)
        if j is not None:
            w.judged_by = "vision"
            out.append(j)
    rest = len(open_windows) - calls
    return out, calls, f"ok ({calls} Aufrufe, Budget {budget}" + (f", {rest} Fenster offen)" if rest else ")")
