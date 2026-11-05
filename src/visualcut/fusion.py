"""Stufe 4: Wortintervalle auf Frames snappen (PLAN.md Abschnitt 3, Stufe 4, Regeln 1 bis 6).

Interpretation der Padding-Regel: Der Cut schrumpft nach innen (80 ms Pre-Roll am Anfang,
120 ms Post-Roll am Ende), damit vom umgebenden, erhaltenen Material nichts abgeschnitten wird.
Invariante: Keine Schnittgrenze liegt innerhalb eines erhaltenen Wortes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schema import Cut, CutReason, CutStatus, SceneChange, SilenceInterval, Word

SNAP_WINDOW = 0.300
PRE_ROLL = 0.080
POST_ROLL = 0.120
MIN_SEGMENT = 0.400
MERGE_DISTANCE = 0.250
MAYBE_BELOW = 0.6


def replace(cut: Cut, **changes) -> Cut:
    return cut.model_copy(update=changes)

REASON_PRIORITY = {
    CutReason.retake: 5, CutReason.false_start: 4, CutReason.redundant: 3, CutReason.tangent: 3,
    CutReason.long_pause: 2, CutReason.technical: 2, CutReason.filler: 1,
}


@dataclass
class _Span:
    cut: Cut
    start: float
    end: float


def _word_bounds(cut: Cut, by_id: dict[int, Word]) -> tuple[float, float]:
    a, b = by_id[cut.start_word], by_id[cut.end_word]
    if cut.reason == CutReason.long_pause and cut.start_word != cut.end_word:
        return a.end, b.start  # die Lücke, nicht die Wörter
    return a.start, b.end


def snap_start(t: float, silences: list[SilenceInterval]) -> float:
    """Nächste Stille, die innerhalb von ±300 ms vor t endet oder t enthält. Schnitt in die Mitte."""
    best = None
    for s in silences:
        if s.start <= t <= s.end or (t - SNAP_WINDOW) <= s.end <= t:
            d = 0.0 if s.start <= t <= s.end else t - s.end
            if best is None or d < best[0]:
                best = (d, s)
    return best[1].mid if best else t


def snap_end(t: float, silences: list[SilenceInterval]) -> float:
    best = None
    for s in silences:
        if s.start <= t <= s.end or t <= s.start <= (t + SNAP_WINDOW):
            d = 0.0 if s.start <= t <= s.end else s.start - t
            if best is None or d < best[0]:
                best = (d, s)
    return best[1].mid if best else t


def _split_at_scenes(span: _Span, scenes: list[SceneChange]) -> list[_Span]:
    inside = sorted(s.time for s in scenes if span.start < s.time < span.end)
    if not inside:
        return [span]
    out: list[_Span] = []
    cur = span.start
    for k, t in enumerate(inside):
        out.append(_Span(replace(span.cut, id=f"{span.cut.id}.{k}"), cur, t))
        cur = t
    out.append(_Span(replace(span.cut, id=f"{span.cut.id}.{len(inside)}"), cur, span.end))
    return out


def _pad(span: _Span) -> _Span:
    s, e = span.start + PRE_ROLL, span.end - POST_ROLL
    if e - s < 0.05:  # zu kurz für Padding, Grenzen behalten
        return span
    return _Span(span.cut, s, e)


def _clamp_to_kept_words(span: _Span, words: list[Word], removed_ids: set[int]) -> _Span:
    """Grenzen dürfen nicht in einem erhaltenen Wort liegen: an die Wortgrenze schieben."""
    s, e = span.start, span.end
    for w in words:
        if w.id in removed_ids or w.end <= w.start:
            continue
        if w.start < s < w.end:
            s = w.end if (w.end - s) < (s - w.start) and w.end <= e else w.start
        if w.start < e < w.end:
            e = w.start if (e - w.start) < (w.end - e) and w.start >= s else w.end
    if e < s:
        s, e = span.start, span.end
    return _Span(span.cut, s, e)


def _merge(a: _Span, b: _Span) -> _Span:
    pa, pb = REASON_PRIORITY.get(a.cut.reason, 0), REASON_PRIORITY.get(b.cut.reason, 0)
    lead = a if (pa, a.cut.confidence) >= (pb, b.cut.confidence) else b
    other = b if lead is a else a
    cut = replace(
        lead.cut,
        start_word=min(a.cut.start_word, b.cut.start_word),
        end_word=max(a.cut.end_word, b.cut.end_word),
        confidence=max(a.cut.confidence, b.cut.confidence),
        note=(lead.cut.note + (f" | zusammengeführt mit {other.cut.id}: {other.cut.note}" if other.cut.note else "")).strip(" |"),
    )
    return _Span(cut, min(a.start, b.start), max(a.end, b.end))


def _merge_close(spans: list[_Span], duration: float, scenes: list[SceneChange]) -> list[_Span]:
    spans = sorted(spans, key=lambda s: (s.start, s.end))
    scene_times = [s.time for s in scenes]
    out: list[_Span] = []
    for sp in spans:
        gap_has_scene = out and any(out[-1].end <= t <= sp.start for t in scene_times)
        if out and sp.start - out[-1].end < MIN_SEGMENT and not gap_has_scene:
            # überlappend, < 250 ms oder Restsegment < 400 ms, aber nie über einen Szenenwechsel hinweg
            out[-1] = _merge(out[-1], sp)
        else:
            out.append(sp)
    if out and 0 < out[0].start < MIN_SEGMENT:
        out[0] = _Span(out[0].cut, 0.0, out[0].end)
    if out and duration > 0 and 0 < duration - out[-1].end < MIN_SEGMENT:
        out[-1] = _Span(out[-1].cut, out[-1].start, duration)
    return out


def fuse(
    cuts: list[Cut], words: list[Word], silences: list[SilenceInterval], scenes: list[SceneChange],
    fps: float, duration: float = 0.0,
) -> list[Cut]:
    by_id = {w.id: w for w in words}
    removed_ids: set[int] = set()
    spans: list[_Span] = []
    for cut in cuts:
        if cut.start_word not in by_id or cut.end_word not in by_id:
            continue  # ungültige Wort-ID: verwerfen, nicht korrigieren
        s, e = _word_bounds(cut, by_id)                      # Regel 1
        if cut.reason != CutReason.long_pause or cut.start_word == cut.end_word:
            removed_ids.update(range(cut.start_word, cut.end_word + 1))
        s, e = snap_start(s, silences), snap_end(e, silences)  # Regel 2
        if e <= s:
            continue
        spans.append(_Span(cut, s, e))

    spans = [p for sp in spans for p in _split_at_scenes(sp, scenes)]  # Regel 3
    spans = [_pad(sp) for sp in spans]                                  # Regel 4
    spans = [_clamp_to_kept_words(sp, words, removed_ids) for sp in spans]
    spans = _merge_close(spans, duration, scenes)                       # Regel 5 und 6
    spans = [_clamp_to_kept_words(sp, words, removed_ids) for sp in spans]

    result: list[Cut] = []
    for sp in spans:
        sf, ef = round(sp.start * fps), round(sp.end * fps)
        if ef <= sf:
            continue
        result.append(replace(
            sp.cut, start=sf / fps, end=ef / fps, start_frame=sf, end_frame=ef,
            maybe=sp.cut.confidence < MAYBE_BELOW, status=sp.cut.status or CutStatus.open,
        ))
    return result

