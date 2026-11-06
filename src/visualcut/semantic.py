"""Stufe 3: semantische Analyse per Claude (PLAN.md Abschnitt 3, Stufe 3).

Das Transkript geht als nummerierte Wörter in Blöcken an die Claude API (Structured Output mit dem
JSON-Schema aus `schema.LLMResponse`). Das Modell liefert ausschließlich Wort-IDs, nie Sekunden.
Jede Antwort wird hart validiert: unbekannte IDs, vertauschte Grenzen und Werte außerhalb des
Bereichs werden verworfen und geloggt, nicht korrigiert. Die Zusammenführung mit den Regel-Cuts
(`merge_with_rules`) macht die Fusion, damit `semantic.json` reine, nachvollziehbare LLM-Ausgabe bleibt.
"""

from __future__ import annotations

import os
from pathlib import Path

from .cache import ProgressFn, ProjectCache, emit
from .fusion import REASON_PRIORITY
from .ingest import StageError
from .schema import (
    Chapter, Cut, CutReason, CutSource, Event, Flag, Highlight, LLMResponse, SemanticResult, SemanticSubmission, SpeechResult, Stage,
    Word,
)

DEFAULT_MODEL = "claude-sonnet-5-5"
STRONG_MODEL = "claude-fable-5-1"
PROMPT_VERSION = "semantic_v2"  # v2: Ereignisse aus Stufe 1b als Kontext
BLOCK_WORDS = 2000
OVERLAP_WORDS = 200
MAX_OUTPUT_TOKENS = 16000
API_KEY_ENV = "ANTHROPIC_API_KEY"


def prompt_path(version: str = PROMPT_VERSION) -> Path:
    """`prompts/<version>.md` im Repo (Entwicklung) oder im Paket (Wheel)."""
    pkg = Path(__file__).resolve().parent
    for candidate in (pkg.parents[1] / "prompts" / f"{version}.md", pkg / "prompts" / f"{version}.md"):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Prompt {version}.md nicht gefunden")


def load_prompt(version: str = PROMPT_VERSION) -> str:
    return prompt_path(version).read_text(encoding="utf-8")


# ---------------------------------------------------------------- Blöcke


def blocks(words: list[Word], size: int = BLOCK_WORDS, overlap: int = OVERLAP_WORDS) -> list[list[Word]]:
    """Blöcke von `size` Wörtern, jeder beginnt `overlap` Wörter vor dem Ende des vorigen."""
    if not words:
        return []
    step = max(1, size - overlap)
    out: list[list[Word]] = []
    start = 0
    while True:
        out.append(words[start : start + size])
        if start + size >= len(words):
            return out
        start += step


def format_block(block: list[Word]) -> str:
    return "\n".join(f"{w.id} {w.text}" for w in block)


# ---------------------------------------------------------------- Validierung


def validate(resp: LLMResponse, block: list[Word], log: ProgressFn | None = None) -> SemanticResult:
    """Harte Validierung einer Modellantwort gegen die Wort-IDs des Blocks. Ungültiges wird verworfen und geloggt."""
    ids = {w.id for w in block}
    rejected = 0

    def reject(what: str, detail: str) -> None:
        nonlocal rejected
        rejected += 1
        emit(log, "log", Stage.semantic, f"verworfen ({what}): {detail}")

    def span_ok(what: str, a: int, b: int, extra: str = "") -> bool:
        if a not in ids or b not in ids:
            reject(what, f"unbekannte Wort-ID {a}..{b}{extra}")
            return False
        if b < a:
            reject(what, f"end_word {b} < start_word {a}{extra}")
            return False
        return True

    cuts: list[Cut] = []
    for c in resp.cuts:
        if not span_ok("cut", c.start_word, c.end_word, f" ({c.reason}: {c.note})"):
            continue
        if not 0.0 <= c.confidence <= 1.0:
            reject("cut", f"confidence {c.confidence} außerhalb [0,1] ({c.start_word}..{c.end_word})")
            continue
        cuts.append(Cut(
            id=f"llm-{c.start_word}-{c.end_word}", start_word=c.start_word, end_word=c.end_word, reason=c.reason,
            confidence=round(c.confidence, 3), source=CutSource.llm, note=c.note.strip(),
        ))

    chapters = [
        Chapter(title=ch.title.strip() or "Abschnitt", start_word=ch.start_word, end_word=ch.end_word)
        for ch in resp.chapters if span_ok("chapter", ch.start_word, ch.end_word, f" ({ch.title})")
    ]
    highlights: list[Highlight] = []
    for h in resp.highlights:
        if not span_ok("highlight", h.start_word, h.end_word):
            continue
        if not 0.0 <= h.score <= 1.0:
            reject("highlight", f"score {h.score} außerhalb [0,1]")
            continue
        highlights.append(Highlight(start_word=h.start_word, end_word=h.end_word, score=round(h.score, 3), hook=h.hook.strip()))
    flags: list[Flag] = []
    for f in resp.flags:
        if f.word not in ids:
            reject("flag", f"unbekannte Wort-ID {f.word}")
            continue
        flags.append(Flag(word=f.word, type=f.type.strip() or "unclear"))
    return SemanticResult(chapters=chapters, cuts=cuts, highlights=highlights, flags=flags, rejected=rejected)


# ---------------------------------------------------------------- Zusammenführen


def _removed_range(c: Cut) -> tuple[int, int]:
    """Wörter, die der Cut wirklich entfernt. Ein Pausen-Cut zwischen zwei Wörtern entfernt keines, er
    berührt seine Nachbarwörter nur; sonst würde er beim Zusammenführen ein behaltenes Wort mitnehmen."""
    if c.reason == CutReason.long_pause and c.start_word != c.end_word:
        return c.start_word + 1, c.end_word - 1
    return c.start_word, c.end_word


def _overlaps(a: Cut, b: Cut) -> bool:
    (a0, a1), (b0, b1) = _removed_range(a), _removed_range(b)
    return a0 <= a1 and b0 <= b1 and a0 <= b1 and b0 <= a1


def _merge(a: Cut, b: Cut) -> Cut:
    """Vereinigung zweier überlappender Cuts; Grund, Konfidenz, Quelle und ID vom führenden Cut."""
    pa, pb = REASON_PRIORITY.get(a.reason, 0), REASON_PRIORITY.get(b.reason, 0)
    lead, other = (a, b) if (pa, a.confidence) >= (pb, b.confidence) else (b, a)
    tail = f"zusammengeführt mit {other.id}" + (f": {other.note}" if other.note and other.note != lead.note else "")
    note = f"{lead.note} | {tail}".strip(" |")
    return lead.model_copy(update={
        "start_word": min(a.start_word, b.start_word), "end_word": max(a.end_word, b.end_word), "note": note,
    })


def merge_overlapping(cuts: list[Cut]) -> list[Cut]:
    """Überlappende Wortintervalle zu einem Cut vereinen (Blocküberlappung, Regel gegen LLM)."""
    out: list[Cut] = []
    for c in sorted(cuts, key=lambda c: (c.start_word, c.end_word)):
        if out and _overlaps(out[-1], c):
            out[-1] = _merge(out[-1], c)
        else:
            out.append(c)
    return out


def merge_with_rules(llm_cuts: list[Cut], rule_cuts: list[Cut]) -> list[Cut]:
    """Regel- und LLM-Cuts zusammen: Überlappungen werden vereint, der Rest bleibt wie er ist."""
    return merge_overlapping(list(rule_cuts) + list(llm_cuts))


def _dedupe_spans(items: list) -> list:
    """Erster Eintrag gewinnt, Folgeeinträge, die in ihn hineinragen, fallen weg (Blocküberlappung)."""
    out: list = []
    for it in sorted(items, key=lambda x: (x.start_word, x.end_word)):
        if out and it.start_word <= out[-1].end_word:
            continue
        out.append(it)
    return out


def combine(results: list[SemanticResult]) -> SemanticResult:
    cuts = merge_overlapping([c for r in results for c in r.cuts])
    chapters = _dedupe_spans([ch for r in results for ch in r.chapters])
    highlights = _dedupe_spans([h for r in results for h in r.highlights])
    seen: set[tuple[int, str]] = set()
    flags: list[Flag] = []
    for f in (f for r in results for f in r.flags):
        if (f.word, f.type) not in seen:
            seen.add((f.word, f.type))
            flags.append(f)
    return SemanticResult(
        chapters=chapters, cuts=cuts, highlights=highlights, flags=flags, blocks=len(results),
        rejected=sum(r.rejected for r in results),
    )


def fingerprint(result: SemanticResult | None) -> str | None:
    """Kennung der Stufe-3-Cuts, damit die Fusion nach jeder Einreichung neu rechnet."""
    if result is None:
        return None
    import hashlib

    h = hashlib.sha1(result.model.encode())
    for c in sorted(result.cuts, key=lambda c: (c.start_word, c.end_word, c.reason.value)):
        h.update(f"{c.start_word}:{c.end_word}:{c.reason.value}:{c.confidence}".encode())
    for hl in sorted(result.highlights, key=lambda x: (x.start_word, x.end_word)):  # die Fusion richtet sie aus
        h.update(f"h{hl.start_word}:{hl.end_word}:{hl.score}".encode())
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- Einreichung durch den steuernden Agenten


def submit(
    cache: ProjectCache, speech: SpeechResult, submission: SemanticSubmission,
    progress: ProgressFn | None = None, append: bool = False,
) -> SemanticResult:
    """Stufe 3 ohne API: der Agent, der VisualCut steuert, liefert Cuts, Kapitel, Highlights und Flags
    auf Wort-IDs. Gleiche Validierung wie bei der Claude-Antwort. `append` vereinigt mit dem Vorhandenen,
    sonst wird semantic.json ersetzt."""
    stage = Stage.semantic
    emit(progress, "stage_start", stage, f"Einreichung von {submission.source}")
    result = validate(submission.as_response(), speech.words, progress)
    if append and cache.has(stage):
        previous = cache.load(stage, SemanticResult)
        result = combine([previous, result])
    result.model, result.prompt_version, result.blocks = submission.source, PROMPT_VERSION, 1
    cache.save(stage, result)
    emit(progress, "stage_done", stage,
         f"{len(result.cuts)} Cuts, {len(result.chapters)} Kapitel, {len(result.highlights)} Highlights, "
         f"{result.rejected} verworfen")
    return result


# ---------------------------------------------------------------- Claude-Aufruf


def has_api_key() -> bool:
    return bool(os.environ.get(API_KEY_ENV))


def block_content(block: list[Word], words: list[Word], events: list[Event] | None) -> str:
    """Nummerierte Wörter, danach die Events, die den Block berühren (nur Wort-IDs, keine Sekunden)."""
    from .events.words import events_on_words, format_events

    text = format_block(block)
    items = events_on_words(events or [], words, block[0].id, block[-1].id) if block else []
    if items:
        text += "\n\n## Ereignisse\n" + format_events(items)
    return text


def call_model(client, model: str, system: str, block: list[Word], content: str | None = None) -> LLMResponse:
    """Ein Block an Claude, Antwort als validiertes `LLMResponse` (Structured Output)."""
    import anthropic

    try:
        response = client.messages.parse(
            model=model, max_tokens=MAX_OUTPUT_TOKENS, system=system,
            messages=[{"role": "user", "content": content if content is not None else format_block(block)}],
            output_format=LLMResponse,
        )
    except anthropic.APIStatusError as e:
        raise StageError(f"Claude API {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise StageError(f"Claude API nicht erreichbar: {e}") from e
    if response.stop_reason == "refusal":
        detail = getattr(response.stop_details, "explanation", "") or ""
        raise StageError(f"Claude hat den Block abgelehnt ({detail or 'refusal'})")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise StageError(f"Antwort unvollständig (stop_reason={response.stop_reason})")
    return response.parsed_output


def analyze_semantic(
    speech: SpeechResult, cache: ProjectCache, progress: ProgressFn | None = None, force: bool = False,
    model: str = DEFAULT_MODEL, enabled: bool = True, client=None, events: list[Event] | None = None,
) -> SemanticResult | None:
    """Stufe 3. Gibt None zurück, wenn die Stufe übersprungen wurde (kein Key oder --no-llm)."""
    stage = Stage.semantic
    if cache.has(stage) and not force:
        emit(progress, "stage_skipped", stage, "Cache vorhanden")
        return cache.load(stage, SemanticResult)
    if not enabled:
        emit(progress, "stage_skipped", stage, "LLM deaktiviert (--no-llm)")
        return None
    if client is None and not has_api_key():
        emit(progress, "stage_skipped", stage, f"{API_KEY_ENV} nicht gesetzt, nur Regel-Cuts")
        return None
    emit(progress, "stage_start", stage)
    system = load_prompt()
    if not speech.words:
        result = SemanticResult(model=model, prompt_version=PROMPT_VERSION)
        cache.save(stage, result)
        emit(progress, "stage_done", stage, "Leeres Transkript, nichts zu analysieren")
        return result
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    parts = blocks(speech.words)
    results: list[SemanticResult] = []
    for i, block in enumerate(parts):
        emit(progress, "progress", stage, f"Block {i + 1}/{len(parts)} ({block[0].id}..{block[-1].id}) an {model}",
             100 * i / len(parts))
        content = block_content(block, speech.words, events)
        results.append(validate(call_model(client, model, system, block, content), block, progress))
    result = combine(results)
    result.model, result.prompt_version = model, PROMPT_VERSION
    cache.save(stage, result)
    emit(progress, "stage_done", stage,
         f"{len(result.cuts)} LLM-Cuts, {len(result.chapters)} Kapitel, {len(result.highlights)} Highlights, "
         f"{result.rejected} verworfen")
    return result
