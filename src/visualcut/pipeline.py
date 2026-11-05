"""Orchestrierung der Stufen. CLI, API und MCP rufen nur diese Funktionen."""

from __future__ import annotations

from pathlib import Path

from . import decisions as decisions_mod
from .cache import ProgressFn, ProjectCache, emit
from .fusion import align_highlights, fuse
from .ingest import ingest
from .ingest import StageError
from .schema import (
    STAGE_ORDER, Analysis, Cut, CutStatus, Event, EventJudgments, EventsResult, EventStatus, FusionResult, MediaInfo,
    SemanticResult, SemanticSubmission, SpeechResult, Stage, TechnicalResult,
)
from .semantic import DEFAULT_MODEL, analyze_semantic, fingerprint, format_block, merge_with_rules, submit
from .speech import PRIMARY_MODEL, rule_cuts, transcribe
from .technical import analyze_technical


def run_analysis(
    video: Path,
    upto: Stage = Stage.fusion,
    force: bool = False,
    progress: ProgressFn | None = None,
    cache_root: Path | None = None,
    whisper_model: str = PRIMARY_MODEL,
    language: str = "de",
    llm: bool = True,
    llm_model: str = DEFAULT_MODEL,
    events: bool = True,
    vision: bool = True,
    vision_budget: int | None = None,
) -> Analysis:
    if not video.exists():
        raise FileNotFoundError(video)
    cache = ProjectCache.for_video(video, cache_root)
    media = ingest(video, cache, progress, force)
    analysis = Analysis(media=media, stages_done=[Stage.ingest])
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.technical):
        return analysis
    analysis.technical = analyze_technical(media, cache, progress, force)
    analysis.stages_done.append(Stage.technical)
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.events):
        return analysis
    from .events import detect_events

    ev = detect_events(media, analysis.technical, cache, progress, force, enabled=events, vision=vision,
                       budget=vision_budget, vision_model=llm_model)
    if ev is not None:  # None: übersprungen (--no-events oder Extra fehlt), kein Abbruch
        analysis.events = ev.events
        analysis.stages_done.append(Stage.events)
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.speech):
        return analysis
    analysis.speech = transcribe(media, cache, progress, force, model_size=whisper_model, language=language)
    analysis.stages_done.append(Stage.speech)
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.semantic):
        return analysis
    analysis.semantic = analyze_semantic(analysis.speech, cache, progress, force, model=llm_model, enabled=llm,
                                         events=analysis.events)
    if analysis.semantic is not None:  # None: übersprungen (kein Key oder --no-llm), kein Abbruch
        analysis.stages_done.append(Stage.semantic)
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.fusion):
        return analysis
    fused = run_fusion(cache, media, analysis.technical, analysis.speech, analysis.semantic, progress, force,
                       events=analysis.events)
    analysis.cuts, analysis.highlights = fused.cuts, fused.highlights
    analysis.stages_done.append(Stage.fusion)
    analysis.cuts = decisions_mod.apply(analysis.cuts, decisions_mod.load(cache))
    return analysis


def events_fingerprint(events: list[Event]) -> str | None:
    """Kennung der Events, die die Fusion beeinflussen (Regel 8), damit sie nach neuen Urteilen neu rechnet."""
    if not events:
        return None
    import hashlib

    h = hashlib.sha1()
    for e in sorted(events, key=lambda e: (e.start, e.id)):
        h.update(f"{e.id}:{e.start}:{e.end}:{e.status.value}:{e.effect.value}".encode())
    return h.hexdigest()[:16]


def run_fusion(
    cache: ProjectCache, media: MediaInfo, technical: TechnicalResult, speech: SpeechResult,
    semantic: SemanticResult | None = None, progress: ProgressFn | None = None, force: bool = False,
    events: list[Event] | None = None,
) -> FusionResult:
    stage = Stage.fusion
    llm_model = semantic.model if semantic is not None else None
    fp = fingerprint(semantic)
    efp = events_fingerprint(events or [])
    if cache.has(stage) and not force:
        cached = cache.load(stage, FusionResult)
        if cached.llm_model == llm_model and cached.semantic_fingerprint == fp and cached.events_fingerprint == efp:
            emit(progress, "stage_skipped", stage, "Cache vorhanden")
            return cached
        emit(progress, "log", stage, "LLM-Cuts oder Events haben sich geändert, Fusion wird neu gerechnet")
    emit(progress, "stage_start", stage)
    rules = rule_cuts(speech.words, speech.language)
    raw = merge_with_rules(semantic.cuts, rules) if semantic is not None else rules
    emit(progress, "progress", stage,
         f"{len(rules)} Regel-Kandidaten, {len(semantic.cuts) if semantic else 0} LLM-Kandidaten", 30)
    # Nur harte Szenenwechsel (ContentDetector) zählen in der Fusion. Reine AdaptiveDetector-Treffer
    # waren in Tests auf Einzelaufnahmen durchweg Licht- und Bewegungsflackern.
    hard_scenes = [s for s in technical.scenes if "content" in s.detector]
    cuts = fuse(raw, speech.words, technical.silences, hard_scenes, media.fps, media.duration, events=events)
    highlights = align_highlights(semantic.highlights, speech.words, events, media.fps, media.duration) if semantic else []
    result = FusionResult(cuts=cuts, highlights=highlights, fps=media.fps, llm_model=llm_model,
                          semantic_fingerprint=fp, events_fingerprint=efp)
    cache.save(stage, result)
    emit(progress, "stage_done", stage, f"{len(cuts)} Cuts")
    return result


def load_analysis(cache: ProjectCache) -> Analysis | None:
    """Analyse aus dem Cache zusammensetzen, ohne etwas neu zu berechnen."""
    if not cache.has(Stage.ingest):
        return None
    from .ingest import rebase

    a = Analysis(media=rebase(cache.load(Stage.ingest, MediaInfo), cache), stages_done=[Stage.ingest])
    if cache.has(Stage.technical):
        a.technical = cache.load(Stage.technical, TechnicalResult)
        a.stages_done.append(Stage.technical)
    if cache.has(Stage.events):
        a.events = cache.load(Stage.events, EventsResult).events
        a.stages_done.append(Stage.events)
    if cache.has(Stage.speech):
        a.speech = cache.load(Stage.speech, SpeechResult)
        a.stages_done.append(Stage.speech)
    if cache.has(Stage.semantic):
        a.semantic = cache.load(Stage.semantic, SemanticResult)
        a.stages_done.append(Stage.semantic)
    if cache.has(Stage.fusion):
        fused = cache.load(Stage.fusion, FusionResult)
        a.cuts = decisions_mod.apply(fused.cuts, decisions_mod.load(cache))
        a.highlights = fused.highlights
        a.stages_done.append(Stage.fusion)
    return a


def cache_for(video: Path, cache_root: Path | None = None) -> ProjectCache:
    if not video.exists():
        raise FileNotFoundError(video)
    return ProjectCache.for_video(video, cache_root)


def require_analysis(video: Path, cache_root: Path | None = None) -> tuple[ProjectCache, Analysis]:
    """Cache plus fertige Analyse (bis Fusion), sonst StageError. CLI, API und MCP nutzen dies."""
    cache = cache_for(video, cache_root)
    analysis = load_analysis(cache)
    if analysis is None or Stage.fusion not in analysis.stages_done:
        raise StageError(f"Keine fertige Analyse im Cache, zuerst: visualcut analyze {video}")
    return cache, analysis


def select_cuts(
    cuts: list[Cut], min_confidence: float = 0.0, status: CutStatus | None = None, reasons: list[str] | None = None,
) -> list[Cut]:
    """Filter, den `visualcut cuts`, `GET /cuts` und das MCP-Tool `get_cuts` gemeinsam nutzen."""
    wanted = set(reasons) if reasons else None
    return [
        c for c in cuts
        if c.confidence >= min_confidence and (status is None or c.status == status)
        and (wanted is None or c.reason.value in wanted)
    ]


def summary(analysis: Analysis, cache: ProjectCache) -> dict:
    """Kennzahlen plus Pfade statt der vollen Analyse (CLI --summary, MCP analyze)."""
    sem = analysis.semantic
    return {
        "analysis_path": str(cache.path("analysis.json")), "content_hash": cache.hash,
        "duration": analysis.media.duration, "fps": analysis.media.fps,
        "stages_done": [s.value for s in analysis.stages_done],
        "words": len(analysis.speech.words) if analysis.speech else 0,
        "silences": len(analysis.technical.silences) if analysis.technical else 0,
        "scenes": len(analysis.technical.scenes) if analysis.technical else 0,
        "cuts": len(analysis.cuts),
        "llm_cuts": len(sem.cuts) if sem else 0,
        "chapters": len(sem.chapters) if sem else 0,
        "llm_model": sem.model if sem else None,
        "whisper_model": analysis.speech.model if analysis.speech else None,
        "events": len(analysis.events),
        "events_confirmed": sum(e.status == EventStatus.confirmed for e in analysis.events),
        "highlights": len(analysis.highlights),
    }


def transcript_lines(speech: SpeechResult, start_word: int = 0, end_word: int | None = None) -> tuple[str, int, int]:
    """Transkript als `ID TEXT`-Zeilen (das Format aus prompts/semantic_v2.md) für einen Ausschnitt.
    Gibt (Text, erste ID, letzte ID) zurück."""
    words = [w for w in speech.words if w.id >= start_word and (end_word is None or w.id <= end_word)]
    if not words:
        return "", start_word, start_word
    return format_block(words), words[0].id, words[-1].id


def submit_semantic(
    video: Path, submission: SemanticSubmission, append: bool = False,
    progress: ProgressFn | None = None, cache_root: Path | None = None,
) -> dict:
    """Stufe 3 aus einer Agenten-Einreichung schreiben und die Fusion neu rechnen. Gibt die Kennzahlen zurück."""
    cache = cache_for(video, cache_root)
    analysis = load_analysis(cache)
    if analysis is None or analysis.speech is None or analysis.technical is None:
        raise StageError(f"Kein Transkript im Cache, zuerst: visualcut analyze {video} --stage speech")
    semantic = submit(cache, analysis.speech, submission, progress, append)
    run_fusion(cache, analysis.media, analysis.technical, analysis.speech, semantic, progress, events=analysis.events)
    refreshed = load_analysis(cache)
    assert refreshed is not None
    cache.path("analysis.json").write_text(refreshed.model_dump_json(indent=2), encoding="utf-8")
    info = summary(refreshed, cache)
    info["rejected"] = semantic.rejected
    return info


def events_info(cache: ProjectCache, analysis: Analysis, pending: bool = False) -> dict:
    """Events mit Wort-ID-Spannen (für Stufe 3), Ebenen-Status und offene Fenster für Ebene C.
    `visualcut events --json`, MCP `get_events` und `GET /projects/{hash}/events` liefern dieses Objekt."""
    from .events.words import events_on_words

    if not cache.has(Stage.events):
        raise StageError(f"Keine Ereigniserkennung im Cache, zuerst: visualcut events {analysis.media.path}")
    result = cache.load(Stage.events, EventsResult)
    words = analysis.speech.words if analysis.speech else []
    mapped = {m["id"]: m for m in events_on_words(result.events, words)}
    open_windows = [w for w in result.windows if w.judged_by is None]
    info = {
        "content_hash": cache.hash, "events_path": str(cache.stage_file(Stage.events)),
        "count": len(result.events),
        "confirmed": sum(e.status == EventStatus.confirmed for e in result.events),
        "events": [{**e.model_dump(mode="json"), **({k: mapped[e.id][k] for k in ("start_word", "end_word", "spoken")}
                                                       if e.id in mapped else {})} for e in result.events],
        "layers": result.layers, "vision_calls": result.vision_calls, "vision_budget": result.vision_budget,
        "open_windows": len(open_windows),
    }
    if pending:
        from .events.vision_llm import PROMPT_VERSION
        from .semantic import prompt_path

        info["windows"] = [w.model_dump(mode="json") for w in open_windows]
        info["instructions_path"] = str(prompt_path(PROMPT_VERSION))
    return info


def run_events(video: Path, force: bool = False, vision: bool = True, vision_budget: int | None = None,
               progress: ProgressFn | None = None, cache_root: Path | None = None) -> tuple[ProjectCache, Analysis]:
    """Stufe 0, 1 und 1b (aus dem Cache, wo vorhanden). Ist schon fusioniert, rechnet Stufe 4 mit den Events neu."""
    analysis = run_analysis(video, Stage.events, force, progress, cache_root, vision=vision, vision_budget=vision_budget)
    cache = cache_for(video, cache_root)
    if Stage.events not in analysis.stages_done:
        raise StageError("Ereigniserkennung übersprungen: Extra fehlt (uv sync --extra events)")
    _refuse_after_events(cache, progress)
    full = load_analysis(cache)
    assert full is not None
    return cache, full


def _refuse_after_events(cache: ProjectCache, progress: ProgressFn | None) -> None:
    a = load_analysis(cache)
    if a is None or a.speech is None or a.technical is None or Stage.fusion not in a.stages_done:
        return
    run_fusion(cache, a.media, a.technical, a.speech, a.semantic, progress, events=a.events)
    refreshed = load_analysis(cache)
    assert refreshed is not None
    cache.path("analysis.json").write_text(refreshed.model_dump_json(indent=2), encoding="utf-8")


def submit_event_judgments(video: Path, submission: EventJudgments, progress: ProgressFn | None = None,
                           cache_root: Path | None = None) -> dict:
    """Ebene C vom steuernden Agenten übernehmen, Events neu fusionieren, Stufe 4 neu rechnen."""
    from .events import apply_judgments

    cache = cache_for(video, cache_root)
    _, rejected = apply_judgments(cache, submission, progress)
    _refuse_after_events(cache, progress)
    analysis = load_analysis(cache)
    assert analysis is not None
    info = events_info(cache, analysis)
    info["rejected"] = rejected
    return info


def transcript_events(analysis: Analysis, first_word: int, last_word: int) -> list[dict]:
    """Events, die einen Transkript-Ausschnitt berühren, als Wort-ID-Spannen (Weg A von Stufe 3)."""
    from .events.words import events_on_words

    if analysis.speech is None or not analysis.events:
        return []
    return events_on_words(analysis.events, analysis.speech.words, first_word, last_word)
