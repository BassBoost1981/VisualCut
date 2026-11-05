"""Events auf Wort-IDs abbilden, damit Stufe 3 (Claude oder der steuernde Agent) sie neben dem Transkript sieht.
Das LLM bekommt nur Wort-IDs, keine Sekunden."""

from __future__ import annotations

from ..schema import Event, Word


def word_span(ev: Event, words: list[Word]) -> tuple[int, int, bool] | None:
    """(erste ID, letzte ID, gesprochen). Ohne Wörter im Event: das Wort davor und danach, gesprochen=False."""
    if not words:
        return None
    inside = [w for w in words if w.end > ev.start and w.start < ev.end]
    if inside:
        return inside[0].id, inside[-1].id, True
    before = [w for w in words if w.end <= ev.start]
    after = [w for w in words if w.start >= ev.end]
    a = before[-1].id if before else words[0].id
    b = after[0].id if after else words[-1].id
    return a, b, False


def events_on_words(events: list[Event], words: list[Word], first_word: int | None = None,
                    last_word: int | None = None) -> list[dict]:
    """Events als Wort-ID-Spannen, optional nur die, die einen Transkript-Ausschnitt berühren."""
    out = []
    for ev in events:
        span = word_span(ev, words)
        if span is None:
            continue
        a, b, spoken = span
        if first_word is not None and b < first_word:
            continue
        if last_word is not None and a > last_word:
            continue
        out.append({
            "id": ev.id, "type": ev.type, "label": ev.label, "status": ev.status.value, "effect": ev.effect.value,
            "confidence": ev.confidence, "start_word": a, "end_word": b, "spoken": spoken,
            "description": ev.description,
        })
    return out


def format_events(items: list[dict]) -> str:
    """Eine Zeile pro Event für den Prompt, nur IDs."""
    lines = []
    for e in items:
        where = f"Wort {e['start_word']} bis {e['end_word']}" if e["spoken"] else \
            f"ohne Sprache, zwischen Wort {e['start_word']} und {e['end_word']}"
        desc = f": {e['description']}" if e.get("description") else ""
        lines.append(f"{e['id']} {e['type']} ({e['label']}), {where}, {e['status']}, Konfidenz {e['confidence']:.2f}, "
                     f"Wirkung {e['effect']}{desc}")
    return "\n".join(lines)
