"""MCP-Server `visualcut-mcp` (stdio, offizielles `mcp`-SDK, PLAN.md Abschnitt 4.3).

Dünne Schicht über `pipeline`, `decisions` und `export`: dieselben Kernfunktionen wie CLI und API,
keine Sonderlogik. Große Ergebnisse (Analyse, Transkript) kommen als Dateipfad zurück, nie als Inhalt.
Fortschritt und Logs gehen auf stderr, stdout gehört dem Protokoll.
"""

from __future__ import annotations

import functools
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from . import __version__, decisions as decisions_mod, export as export_mod, pipeline
from .cache import stderr_progress
from .ingest import StageError
from .schema import CutStatus, LLMChapter, LLMCut, LLMFlag, LLMHighlight, SemanticSubmission, Stage, json_schema
from .semantic import DEFAULT_MODEL, load_prompt

INSTRUCTIONS = (
    "VisualCut analysiert Rohvideo lokal und liefert framegenaue Schnittvorschläge. Ablauf: analyze(path) "
    "(dauert bei langen Videos Minuten, Cache unter .visualcut/<hash>/), dann get_cuts(path) zum Erklären "
    "und Filtern, decide(path, cut_id, status) zum Annehmen oder Verwerfen, export(path, format) für die "
    "Schnittliste. Große Daten kommen als Pfad zurück: analysis.json (alles) und speech.json (Transkript "
    "mit Wort-IDs). Cuts referenzieren Wort-IDs; Sekunden und Frames berechnet der Code, nie das LLM."
)

server = MCPServer("visualcut", instructions=INSTRUCTIONS, version=__version__)


def tool(fn):
    """`@server.tool()` plus Fehlerübersetzung: dieselben Fehlerklassen wie die CLI-Exit-Codes, als Text an den Agenten."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except FileNotFoundError as e:
            raise ToolError(f"Datei nicht gefunden: {e}") from e
        except (ValidationError, json.JSONDecodeError) as e:
            raise ToolError(f"Cache ungültig, analyze(force=True) oder .visualcut löschen: {e}") from e
        except (StageError, ValueError) as e:
            raise ToolError(str(e)) from e

    return server.tool()(wrapper)


def _video(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


@tool
def analyze(
    path: str, stage: Stage = Stage.fusion, force: bool = False, language: str = "de",
    whisper_model: str = "large-v3", llm: bool = True, model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Pipeline laufen lassen (ingest, technical, speech, semantic, fusion) und Kennzahlen plus den Pfad zu
    analysis.json zurückgeben. Fertige Stufen kommen aus dem Cache, force=True rechnet neu. Stufe semantic
    braucht ANTHROPIC_API_KEY, ohne Key wird sie übersprungen; llm=False schaltet sie ab."""
    video = _video(path)
    analysis = pipeline.run_analysis(
        video, stage, force, stderr_progress, None, whisper_model, language, llm=llm, llm_model=model,
    )
    cache = pipeline.cache_for(video)
    cache.path("analysis.json").write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
    return pipeline.summary(analysis, cache)


@tool
def get_cuts(
    path: str, min_confidence: float = 0.0, reasons: list[str] | None = None, status: CutStatus | None = None,
) -> dict[str, Any]:
    """Gefilterte Cut-Liste aus dem Cache: Wort-IDs, Sekunden, Frames, reason, confidence, source (rule/llm),
    note (Begründung) und status aus decisions.json. reasons z. B. ["retake", "tangent"]."""
    _, analysis = pipeline.require_analysis(_video(path))
    sel = pipeline.select_cuts(analysis.cuts, min_confidence, status, reasons)
    return {"content_hash": analysis.media.content_hash, "fps": analysis.media.fps, "count": len(sel),
            "cuts": [c.model_dump(mode="json") for c in sel]}


@tool
def decide(path: str, cut_id: str, status: CutStatus, note: str = "") -> dict[str, Any]:
    """Einen Cut annehmen (accepted), verwerfen (rejected) oder wieder öffnen (open). Schreibt decisions.json,
    das Export, CLI und UI lesen."""
    cache, analysis = pipeline.require_analysis(_video(path))
    if cut_id not in {c.id for c in analysis.cuts}:
        raise ValueError(f"Unbekannte Cut-ID {cut_id}")
    d = decisions_mod.set_status(cache, cut_id, status, note)
    return {"cut_id": cut_id, "status": status.value, "decisions_path": str(cache.path(decisions_mod.FILENAME)),
            "decided": len(d.items)}


@tool
def export(path: str, format: str = "fcpxml", out: str | None = None, open_as_cut: bool = False) -> dict[str, Any]:
    """Schnittliste schreiben (fcpxml für DaVinci Resolve, edl, otio). Angenommene Cuts werden geschnitten,
    offene als Marker gesetzt (open_as_cut=True: auch geschnitten), verworfene ignoriert. Gibt den Pfad zurück."""
    if format not in ("fcpxml", "edl", "otio"):
        raise ValueError(f"Unbekanntes Format {format}")
    video = _video(path)
    cache, analysis = pipeline.require_analysis(video)
    target = Path(out) if out else cache.path(f"{video.stem}.{format}")
    tl = export_mod.build_timeline(analysis.media, analysis.cuts, include_open=open_as_cut)
    export_mod.write(tl, target, format)
    to_cut, to_mark = decisions_mod.for_export(analysis.cuts, open_as_cut)
    return {"path": str(target), "format": format, "cuts_applied": len(to_cut), "markers": len(to_mark),
            "clips": len(list(tl.tracks[0]))}


@tool
def get_transcript_path(path: str) -> dict[str, Any]:
    """Pfad zu speech.json (Wortliste mit id, text, start, end) plus Kennzahlen. Das Transkript selbst wird
    nicht zurückgegeben, lies gezielt in der Datei nach."""
    cache = pipeline.cache_for(_video(path))
    analysis = pipeline.load_analysis(cache)
    if analysis is None or analysis.speech is None:
        raise ValueError("Kein Transkript im Cache, zuerst: analyze(path, stage='speech')")
    sem = analysis.semantic
    return {
        "transcript_path": str(cache.stage_file(Stage.speech)), "words": len(analysis.speech.words),
        "language": analysis.speech.language, "whisper_model": analysis.speech.model,
        "semantic_path": str(cache.stage_file(Stage.semantic)) if sem else None,
        "chapters": [ch.model_dump() for ch in sem.chapters] if sem else [],
    }


@tool
def semantic_instructions() -> str:
    """Anleitung für Stufe 3 (prompts/semantic_v1.md): Regeln, erlaubte reason-Werte, Ausgabeformat. Vor
    submit_semantic einmal lesen und befolgen."""
    return load_prompt()


@tool
def get_transcript(path: str, start_word: int = 0, max_words: int = 2000) -> dict[str, Any]:
    """Transkript als `ID TEXT`-Zeilen ab start_word, höchstens max_words Wörter (Standard 2000, wie ein
    API-Block). Blockweise durchgehen: next_word ist die nächste ID oder null am Ende. Das ist die Eingabe
    für submit_semantic; verwende ausschließlich diese IDs."""
    cache = pipeline.cache_for(_video(path))
    analysis = pipeline.load_analysis(cache)
    if analysis is None or analysis.speech is None:
        raise ValueError("Kein Transkript im Cache, zuerst: analyze(path, stage='speech')")
    words = analysis.speech.words
    text, first, last = pipeline.transcript_lines(analysis.speech, start_word, start_word + max(1, max_words) - 1)
    nxt = next((w.id for w in words if w.id > last), None) if text else None
    return {"language": analysis.speech.language, "total_words": len(words), "first_word": first, "last_word": last,
            "next_word": nxt, "lines": text}


@tool
def submit_semantic(
    path: str, cuts: list[LLMCut] | None = None, chapters: list[LLMChapter] | None = None,
    highlights: list[LLMHighlight] | None = None, flags: list[LLMFlag] | None = None,
    source: str = "agent", append: bool = False,
) -> dict[str, Any]:
    """Stufe 3 einreichen: Cuts (start_word, end_word, reason, confidence, note), Kapitel, Highlights, Flags,
    alles nur mit Wort-IDs aus get_transcript. Ungültige IDs werden verworfen und gezählt (rejected), nicht
    korrigiert. Schreibt semantic.json und rechnet die Fusion (Snapping auf Frames) neu. append=True vereinigt
    mit einer früheren Einreichung, sonst wird sie ersetzt. Gibt die Kennzahlen wie analyze zurück."""
    sub = SemanticSubmission(source=source, cuts=cuts or [], chapters=chapters or [], highlights=highlights or [],
                             flags=flags or [])
    return pipeline.submit_semantic(_video(path), sub, append, stderr_progress)


@tool
def schema() -> dict[str, Any]:
    """JSON-Schema aller Ausgaben (Analysis, Decisions, ProgressEvent, Cut), identisch mit `visualcut schema`."""
    return json_schema()


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
