"""Orchestrierung der Stufen. CLI, API und MCP rufen nur diese Funktionen."""

from __future__ import annotations

from pathlib import Path

from . import decisions as decisions_mod
from .cache import ProgressFn, ProjectCache, emit
from .fusion import fuse
from .ingest import ingest
from .schema import STAGE_ORDER, Analysis, FusionResult, MediaInfo, SpeechResult, Stage, TechnicalResult
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
    if STAGE_ORDER.index(upto) < STAGE_ORDER.index(Stage.fusion):
        return analysis
    analysis.cuts = run_fusion(cache, media, analysis.technical, analysis.speech, progress, force).cuts
    analysis.stages_done.append(Stage.fusion)
    analysis.cuts = decisions_mod.apply(analysis.cuts, decisions_mod.load(cache))
    return analysis


def run_fusion(
    cache: ProjectCache, media: MediaInfo, technical: TechnicalResult, speech: SpeechResult,
    progress: ProgressFn | None = None, force: bool = False,
) -> FusionResult:
    stage = Stage.fusion
    if cache.has(stage) and not force:
        emit(progress, "stage_skipped", stage, "Cache vorhanden")
        return cache.load(stage, FusionResult)
    emit(progress, "stage_start", stage)
    raw = rule_cuts(speech.words)
    emit(progress, "progress", stage, f"{len(raw)} Regel-Kandidaten", 30)
    cuts = fuse(raw, speech.words, technical.silences, technical.scenes, media.fps, media.duration)
    result = FusionResult(cuts=cuts, fps=media.fps)
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
    if cache.has(Stage.fusion):
        a.cuts = decisions_mod.apply(cache.load(Stage.fusion, FusionResult).cuts, decisions_mod.load(cache))
        a.stages_done.append(Stage.fusion)
    return a


def cache_for(video: Path, cache_root: Path | None = None) -> ProjectCache:
    if not video.exists():
        raise FileNotFoundError(video)
    return ProjectCache.for_video(video, cache_root)
