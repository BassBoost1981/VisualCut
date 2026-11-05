"""Fusion der drei Ebenen (PLAN.md, Stufe 1b, "Fusion der drei Ebenen"):

1. Zeitlich überlappende Detektionen gleichen Typs werden zusammengeführt. Konfidenz: gewichtetes Mittel über
   die Quellen (pro Quelle gemittelt), Ebene C zählt doppelt, Ebene A halb, Ebene B einfach.
2. `confirmed` braucht mindestens zwei Quellen oder eine Ebene-C-Bestätigung, sonst `candidate`.
3. Start und Ende kommen aus Ebene A, wenn der Typ `motion: true` hat: erstes Sample über der Schwelle.
4. Events unter 1 Sekunde werden verworfen, außer reine Audio-Events.

Ein Ebene-C-Urteil `none` ist ein Veto: Kandidaten der fraglichen Typen in diesem Fenster entfallen.
Reine Funktion von EventsResult und Katalog, damit Urteile und Katalogänderungen ohne Modelle neu fusioniert werden.
"""

from __future__ import annotations

import numpy as np

from ..schema import Event, EventCatalog, EventsResult, EventStatus
from . import pose

LAYER = {"pose": "A", "clap": "A", "xclip": "B", "videomae": "B", "vision": "C"}
WEIGHT = {"A": 0.5, "B": 1.0, "C": 2.0}
AUDIO_SOURCES = {"clap"}
MERGE_GAP = 0.5
MIN_DURATION = 1.0
REFINE_SEARCH = 2.0


def layer(source: str) -> str:
    return "C" if source.startswith("agent") else LAYER.get(source, "B")


def judgment_detections(result: EventsResult) -> tuple[list[Event], list[tuple[float, float, set[str]]]]:
    """Urteile (Claude oder Agent) als Detektionen der Ebene C, `none` als Veto-Fenster."""
    windows = {w.id: w for w in result.windows}
    dets: list[Event] = []
    vetoes: list[tuple[float, float, set[str]]] = []
    for j in result.judgments:
        w = windows.get(j.window_id)
        if w is None:
            continue
        if j.type == "none":
            vetoes.append((w.start, w.end, set(w.candidates)))
            continue
        dets.append(Event(id=f"c-{j.type}-{w.start:.1f}", type=j.type, start=w.start, end=w.end,
                          confidence=j.confidence, sources=[w.judged_by or "vision"], description=j.description or None))
    return dets, vetoes


def _cluster(dets: list[Event]) -> list[list[Event]]:
    out: list[list[Event]] = []
    end = -1e9
    for d in sorted(dets, key=lambda d: (d.start, d.end)):
        if out and d.start <= end + MERGE_GAP:
            out[-1].append(d)
            end = max(end, d.end)
        else:
            out.append([d])
            end = d.end
    return out


def _confidence(members: list[Event]) -> float:
    per_source: dict[str, list[float]] = {}
    for m in members:
        for s in m.sources:
            per_source.setdefault(s, []).append(m.confidence)
    num = sum(WEIGHT[layer(s)] * float(np.mean(v)) for s, v in per_source.items())
    den = sum(WEIGHT[layer(s)] for s in per_source)
    return num / den if den else 0.0


def refine(start: float, end: float, motion: list[float], lower: list[float], fps: float) -> tuple[float, float]:
    """Regel 3: Grenzen auf das erste bzw. letzte Sample über der Schwelle, Suche ±2 s um die grobe Grenze.
    Unterkörperenergie, wo der Unterkörper sichtbar ist, sonst Ganzkörperenergie."""
    if not motion:
        return start, end
    a, b = int(start * fps), min(len(motion), int(np.ceil(end * fps)))
    low = np.asarray(lower[:len(motion)] if lower else [], dtype=float)
    use_lower = len(low) == len(motion) and b > a and float((low[a:b] > 0).mean()) >= pose.LOWER_VISIBLE
    sig = pose.smooth(low if use_lower else np.asarray(motion, dtype=float), max(1, int(fps / 2)))
    thr = pose.LOWER_THRESHOLD if use_lower else pose.MOTION_THRESHOLD
    above = sig >= thr
    n, r = len(sig), int(REFINE_SEARCH * fps)

    def first_above(i: int) -> int | None:
        i = min(max(i, 0), n - 1)
        if above[i]:  # rückwärts bis zum Beginn der Bewegung
            j = i
            while j - 1 >= max(0, i - r) and above[j - 1]:
                j -= 1
            return j
        for j in range(i, min(n, i + r + 1)):  # vorwärts bis zum ersten Sample darüber
            if above[j]:
                return j
        return None

    def last_above(i: int) -> int | None:
        i = min(max(i, 0), n - 1)
        if above[i]:
            j = i
            while j + 1 < min(n, i + r + 1) and above[j + 1]:
                j += 1
            return j
        for j in range(i, max(-1, i - r - 1), -1):
            if above[j]:
                return j
        return None

    s_idx, e_idx = first_above(a), last_above(b - 1)
    ns = s_idx / fps if s_idx is not None else start
    ne = (e_idx + 1) / fps if e_idx is not None else end
    return (ns, ne) if ne > ns else (start, end)


def fuse_events(result: EventsResult, catalog: EventCatalog) -> list[Event]:
    defs = {d.type: d for d in catalog.events}
    c_dets, vetoes = judgment_detections(result)
    dets = [d for d in result.detections + c_dets if d.type in defs and not defs[d.type].background]
    by_type: dict[str, list[Event]] = {}
    for d in dets:
        by_type.setdefault(d.type, []).append(d)
    out: list[Event] = []
    for t, items in by_type.items():
        d = defs[t]
        for members in _cluster(items):                                         # Regel 1
            sources = sorted({s for m in members for s in m.sources})
            has_c = any(layer(s) == "C" for s in sources)
            start, end = min(m.start for m in members), max(m.end for m in members)
            if not has_c and any(t in cand and min(end, ve) - max(start, vs) > 0.5 * (end - start)
                                 for vs, ve, cand in vetoes):
                continue                                                         # Veto aus Ebene C
            confirmed = len(sources) >= 2 or has_c                               # Regel 2
            if d.motion and "pose" in sources:                                  # Regel 3
                start, end = refine(start, end, result.motion, result.motion_lower, result.motion_fps)
            audio_only = all(s in AUDIO_SOURCES for s in sources)
            if end - start < MIN_DURATION and not audio_only:                    # Regel 4
                continue
            desc = next((m.description for m in members if m.description), None)
            out.append(Event(
                id=f"ev-{t}-{start:.1f}", type=t, label=d.label, start=round(start, 3), end=round(end, 3),
                confidence=round(_confidence(members), 3), sources=sources,
                status=EventStatus.confirmed if confirmed else EventStatus.candidate, effect=d.effect, description=desc,
            ))
    out.sort(key=lambda e: (e.start, e.type))
    seen: dict[str, int] = {}
    for e in out:  # IDs eindeutig halten
        if e.id in seen:
            seen[e.id] += 1
            e.id = f"{e.id}.{seen[e.id]}"
        else:
            seen[e.id] = 0
    return out
