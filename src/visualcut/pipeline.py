"""Orchestrierung der Stufen. CLI, API und MCP rufen nur diese Funktionen."""

from __future__ import annotations

from pathlib import Path

from . import decisions as decisions_mod
from .cache import ProgressFn, ProjectCache, emit
from .fusion import fuse
from .ingest import ingest
from .ingest import StageError
from .schema import (
    STAGE_ORDER, Analysis, Cut, CutStatus, FusionResult, MediaInfo, SemanticResult, SemanticSubmission, SpeechResult, Stage,
    TechnicalResult,
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
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.speech):
        return analysis
    analysis.speech = transcribe(media, cache, progress, force, model_size=whisper_model, language=language)
    analysis.stages_done.append(Stage.speech)
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.semantic):
        return analysis
    analysis.semantic = analyze_semantic(analysis.speech, cache, progress, force, model=llm_model, enabled=llm)
    if analysis.semantic is not None:  # None: übersprungen (kein Key oder --no-llm), kein Abbruch
        analysis.stages_done.append(Stage.semantic)
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.fusion):
        return analysis
    analysis.cuts = run_fusion(cache, media, analysis.technical, analysis.speech, analysis.semantic, progress, force).cuts
    analysis.stages_done.append(Stage.fusion)
    analysis.cuts = decisions_mod.apply(analysis.cuts, decisions_mod.load(cache))
    return analysis


def run_fusion(
    cache: ProjectCache, media: MediaInfo, technical: TechnicalResult, speech: SpeechResult,
    semantic: SemanticResult | None = None, progress: ProgressFn | None = None, force: bool = False,
) -> FusionResult:
    stage = Stage.fusion
    llm_model = semantic.model if semantic is not None else None
    fp = fingerprint(semantic)
    if cache.has(stage) and not force:
        cached = cache.load(stage, FusionResult)
        if cached.llm_model == llm_model and cached.semantic_fingerprint == fp:
            emit(progress, "stage_skipped", stage, "Cache vorhanden")
            return cached
        emit(progress, "log", stage, "LLM-Cuts haben sich geändert, Fusion wird neu gerechnet")
    emit(progress, "stage_start", stage)
    rules = rule_cuts(speech.words, speech.language)
    raw = merge_with_rules(semantic.cuts, rules) if semantic is not None else rules
    emit(progress, "progress", stage,
         f"{len(rules)} Regel-Kandidaten, {len(semantic.cuts) if semantic else 0} LLM-Kandidaten", 30)
    # Nur harte Szenenwechsel (ContentDetector) zählen in der Fusion. Reine AdaptiveDetector-Treffer
    # waren in Tests auf Einzelaufnahmen durchweg Licht- und Bewegungsflackern.
    hard_scenes = [s for s in technical.scenes if "content" in s.detector]
    cuts = fuse(raw, speech.words, technical.silences, hard_scenes, media.fps, media.duration)
    result = FusionResult(cuts=cuts, fps=media.fps, llm_model=llm_model, semantic_fingerprint=fp)
    cache.save(stage, result)
    emit(progress, "stage_done", stage, f"{len(cuts)} Cuts")
    return result


def load_analysis(cache: ProjectCache) -> Analysis | None:
    """Analyse aus dem Cache zusammensetzen, ohne etwas neu zu berechnen."""
    if not cache.has(Stage.ingest):
        return None
    a = Analysis(media=cache.load(Stage.ingest, MediaInfo), stages_done=[Stage.ingest])
    if cache.has(Stage.technical):
        a.technical = cache.load(Stage.technical, TechnicalResult)
        a.stages_done.append(Stage.technical)
    if cache.has(Stage.speech):
        a.speech = cache.load(Stage.speech, SpeechResult)
        a.stages_done.append(Stage.speech)
    if cache.has(Stage.semantic):
        a.semantic = cache.load(Stage.semantic, SemanticResult)
        a.stages_done.append(Stage.semantic)
    if cache.has(Stage.fusion):
        a.cuts = decisions_mod.apply(cache.load(Stage.fusion, FusionResult).cuts, decisions_mod.load(cache))
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
    }


def transcript_lines(speech: SpeechResult, start_word: int = 0, end_word: int | None = None) -> tuple[str, int, int]:
    """Transkript als `ID TEXT`-Zeilen (das Format aus prompts/semantic_v1.md) für einen Ausschnitt.
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
    run_fusion(cache, analysis.media, analysis.technical, analysis.speech, semantic, progress)
    refreshed = load_analysis(cache)
    assert refreshed is not None
    cache.path("analysis.json").write_text(refreshed.model_dump_json(indent=2), encoding="utf-8")
    info = summary(refreshed, cache)
    info["rejected"] = semantic.rejected
    return info
