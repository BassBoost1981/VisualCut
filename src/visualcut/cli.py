"""Typer-CLI. Mit --json steht ausschließlich JSON auf stdout, Logs und Fortschritt auf stderr.

Exit-Codes: 0 ok, 2 Eingabefehler, 3 Stufe fehlgeschlagen, 4 Cache ungültig.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from . import __version__, decisions as decisions_mod, export as export_mod, pipeline
from .cache import stderr_progress
from .ingest import StageError
from .schema import CutReason, CutStatus, EventJudgments, SemanticSubmission, Stage, json_schema
from .semantic import DEFAULT_MODEL, load_prompt

EXIT_OK, EXIT_INPUT, EXIT_STAGE, EXIT_CACHE = 0, 2, 3, 4

for _stream in (sys.stdout, sys.stderr):  # Windows-Konsole: UTF-8 statt cp1252
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(
    name="visualcut", add_completion=False, no_args_is_help=True,
    help="Framegenaue Schnittvorschläge für Rohvideo. Alle Befehle unterstützen --json.",
)

JsonFlag = Annotated[bool, typer.Option("--json", help="Nur JSON auf stdout, Logs auf stderr")]
VideoArg = Annotated[Path, typer.Argument(help="Eingabevideo", exists=False)]
CacheOpt = Annotated[Path | None, typer.Option("--cache-dir", help="Cache-Wurzel (Standard .visualcut oder $VISUALCUT_CACHE)")]


def _out(obj, as_json: bool, human: str | None = None) -> None:
    if as_json:
        data = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    else:
        typer.echo(human if human is not None else (obj.model_dump_json(indent=2) if hasattr(obj, "model_dump_json") else json.dumps(obj, ensure_ascii=False, indent=2)))


def _fail(code: int, message: str, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps({"error": message, "exit_code": code}, ensure_ascii=False) + "\n")
    typer.echo(f"Fehler: {message}", err=True)
    raise typer.Exit(code)


def _guard(fn, as_json: bool):
    try:
        return fn()
    except FileNotFoundError as e:
        _fail(EXIT_INPUT, f"Datei nicht gefunden: {e}", as_json)
    except (ValidationError, json.JSONDecodeError) as e:
        _fail(EXIT_CACHE, f"Cache ungültig, --force oder .visualcut löschen: {e}", as_json)
    except StageError as e:
        _fail(EXIT_STAGE, str(e), as_json)
    except ValueError as e:
        _fail(EXIT_INPUT, str(e), as_json)


@app.callback()
def _main(version: Annotated[bool, typer.Option("--version", is_eager=True)] = False) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command()
def analyze(
    video: VideoArg,
    json_: JsonFlag = False,
    stage: Annotated[Stage, typer.Option("--stage", help="Bis zu dieser Stufe rechnen")] = Stage.fusion,
    force: Annotated[bool, typer.Option("--force", help="Cache ignorieren und neu rechnen")] = False,
    whisper_model: Annotated[str, typer.Option("--whisper-model")] = "large-v3",
    language: Annotated[str, typer.Option("--language")] = "de",
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Stufe 3 (Claude) überspringen, nur Regel-Cuts")] = False,
    model: Annotated[str, typer.Option("--model", help="Claude-Modell für Stufe 3 und Ebene C von Stufe 1b")] = DEFAULT_MODEL,
    no_events: Annotated[bool, typer.Option("--no-events", help="Stufe 1b (Ereigniserkennung) überspringen")] = False,
    no_vision: Annotated[bool, typer.Option("--no-vision", help="Stufe 1b ohne Vision-LLM (Ebene C)")] = False,
    vision_budget: Annotated[int | None, typer.Option("--vision-budget", help="Max. Vision-LLM-Aufrufe (Standard aus events.yaml, 40)")] = None,
    cache_dir: CacheOpt = None,
    summary: Annotated[bool, typer.Option("--summary", help="Nur Kennzahlen und Pfad statt der vollen Analyse")] = False,
) -> None:
    """Alle Stufen laufen lassen (oder bis --stage): ingest, technical, events, speech, semantic, fusion.
    Gibt analysis.json zurück.

    Stufe 3 braucht ANTHROPIC_API_KEY; ohne Key wird sie übersprungen (stage_skipped), nicht abgebrochen.
    Stufe 1b braucht das Extra `events` (uv sync --extra events); ohne wird sie übersprungen.
    """

    def go():
        analysis = pipeline.run_analysis(
            video, stage, force, stderr_progress, cache_dir, whisper_model, language, llm=not no_llm, llm_model=model,
            events=not no_events, vision=not no_vision, vision_budget=vision_budget,
        )
        cache = pipeline.cache_for(video, cache_dir)
        out_path = cache.path("analysis.json")
        out_path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        if summary or not json_:
            info = pipeline.summary(analysis, cache)
            _out(info, json_, "\n".join(f"{k}: {v}" for k, v in info.items()))
        else:
            _out(analysis, True)

    _guard(go, json_)


@app.command()
def cuts(
    video: VideoArg,
    json_: JsonFlag = False,
    min_confidence: Annotated[float, typer.Option("--min-confidence")] = 0.0,
    status: Annotated[CutStatus | None, typer.Option("--status", help="Nur Cuts mit diesem Status")] = None,
    reason: Annotated[list[str] | None, typer.Option("--reason", help="Nur diese Gründe (mehrfach möglich)")] = None,
    cache_dir: CacheOpt = None,
) -> None:
    """Cut-Liste aus dem Cache, mit Status aus decisions.json."""

    def go():
        _, analysis = pipeline.require_analysis(video, cache_dir)
        sel = pipeline.select_cuts(analysis.cuts, min_confidence, status, reason)
        data = {"content_hash": analysis.media.content_hash, "fps": analysis.media.fps, "count": len(sel),
                "cuts": [c.model_dump(mode="json") for c in sel]}
        lines = [f"{c.id:>24}  {c.start:8.3f}-{c.end:8.3f}  {c.reason.value:<10} {c.confidence:.2f}  {c.source.value:<5} {c.status.value:<8} {c.note}" for c in sel]
        _out(data, json_, "\n".join(lines) or "Keine Cuts")

    _guard(go, json_)


@app.command()
def decide(
    video: VideoArg,
    cut_id: Annotated[str, typer.Argument()],
    status: Annotated[CutStatus, typer.Argument()],
    note: Annotated[str, typer.Option("--note")] = "",
    json_: JsonFlag = False,
    cache_dir: CacheOpt = None,
) -> None:
    """Einen Cut annehmen, verwerfen oder wieder öffnen (schreibt decisions.json)."""

    def go():
        cache, analysis = pipeline.require_analysis(video, cache_dir)
        if cut_id not in {c.id for c in analysis.cuts}:
            raise ValueError(f"Unbekannte Cut-ID {cut_id}")
        d = decisions_mod.set_status(cache, cut_id, status, note)
        _out(d, json_, f"{cut_id}: {status.value}")

    _guard(go, json_)


@app.command()
def mark(
    video: VideoArg,
    start_word: Annotated[int, typer.Argument(help="Erste Wort-ID (aus visualcut transcript)")],
    end_word: Annotated[int, typer.Argument(help="Letzte Wort-ID, einschließlich")],
    reason: Annotated[CutReason, typer.Option("--reason")] = CutReason.redundant,
    note: Annotated[str, typer.Option("--note")] = "",
    json_: JsonFlag = False,
    cache_dir: CacheOpt = None,
) -> None:
    """Wortspanne als manuellen Cut speichern (manual.json, sofort angenommen) und die Fusion neu rechnen."""

    def go():
        cache = pipeline.cache_for(video, cache_dir)
        cut, analysis = pipeline.mark(cache, start_word, end_word, reason, note, stderr_progress if json_ else None)
        fused = [c for c in analysis.cuts if c.id == cut.id or c.id.startswith(cut.id + ".")]
        _out({"cut": cut.model_dump(mode="json"), "fused": [c.model_dump(mode="json") for c in fused],
              "cuts": len(analysis.cuts)}, json_,
             f"{cut.id}: Wörter {start_word}-{end_word} ({reason.value}), " + (
                 ", ".join(f"{c.start:.3f}-{c.end:.3f}" for c in fused) or "nach der Fusion leer"))

    _guard(go, json_)


@app.command()
def unmark(
    video: VideoArg,
    cut_id: Annotated[str, typer.Argument(help="ID des manuellen Cuts (manual-<start>-<end>)")],
    json_: JsonFlag = False,
    cache_dir: CacheOpt = None,
) -> None:
    """Manuellen Cut löschen und die Fusion neu rechnen."""

    def go():
        cache = pipeline.cache_for(video, cache_dir)
        cut, analysis = pipeline.unmark(cache, cut_id, stderr_progress if json_ else None)
        _out({"removed": cut.id, "cuts": len(analysis.cuts)}, json_, f"{cut.id} gelöscht")

    _guard(go, json_)


@app.command()
def export(
    video: VideoArg,
    format: Annotated[str, typer.Option("--format", help="fcpxml, edl, otio oder markers-edl (Resolve: Timeline-Marker mit Farben)")] = "fcpxml",
    out: Annotated[Path | None, typer.Option("--out")] = None,
    open_as_cut: Annotated[bool, typer.Option("--open-as-cut", help="Offene Cuts schneiden statt als Marker setzen")] = False,
    json_: JsonFlag = False,
    cache_dir: CacheOpt = None,
) -> None:
    """Schnittliste schreiben. Angenommene Cuts werden geschnitten, offene als Marker gesetzt, verworfene ignoriert."""

    def go():
        if format not in export_mod.FORMATS:
            raise ValueError(f"Unbekanntes Format {format}")
        cache, analysis = pipeline.require_analysis(video, cache_dir)
        target = out or cache.path(f"{video.stem}.{format.replace('markers-edl', 'markers.edl')}")
        tl = export_mod.build_timeline(analysis.media, analysis.cuts, include_open=open_as_cut, events=analysis.events)
        export_mod.write(tl, target, format)
        to_cut, to_mark = decisions_mod.for_export(analysis.cuts, open_as_cut)
        info = {"path": str(target), "format": format, "cuts_applied": len(to_cut), "markers": len(to_mark),
                "event_markers": export_mod.count_event_markers(tl), "clips": len(list(tl.tracks[0]))}
        _out(info, json_, f"{target} ({info['clips']} Clips, {info['cuts_applied']} Cuts, {info['markers']} Marker, "
                          f"{info['event_markers']} Event-Marker)")

    _guard(go, json_)


@app.command()
def render(
    video: VideoArg,
    out: Annotated[Path, typer.Option("--out")] = Path("preview.mp4"),
    open_as_cut: Annotated[bool, typer.Option("--open-as-cut")] = False,
    original: Annotated[bool, typer.Option("--original", help="Aus dem Original statt dem Proxy rendern")] = False,
    json_: JsonFlag = False,
    cache_dir: CacheOpt = None,
) -> None:
    """Vorschau per ffmpeg rendern (erhaltene Segmente aneinandergehängt)."""

    def go():
        _, analysis = pipeline.require_analysis(video, cache_dir)
        src = analysis.media.path if original else None
        export_mod.render_preview(analysis.media, analysis.cuts, out, include_open=open_as_cut, source=src)
        _out({"path": str(out)}, json_, str(out))

    _guard(go, json_)


@app.command()
def transcript(
    video: VideoArg,
    json_: JsonFlag = False,
    from_word: Annotated[int, typer.Option("--from-word", help="Erste Wort-ID")] = 0,
    to_word: Annotated[int | None, typer.Option("--to-word", help="Letzte Wort-ID (einschließlich)")] = None,
    cache_dir: CacheOpt = None,
) -> None:
    """Transkript als `ID TEXT`-Zeilen, das Eingabeformat für Stufe 3 (siehe `visualcut semantic --instructions`)."""

    def go():
        cache = pipeline.cache_for(video, cache_dir)
        analysis = pipeline.load_analysis(cache)
        if analysis is None or analysis.speech is None:
            raise StageError(f"Kein Transkript im Cache, zuerst: visualcut analyze {video} --stage speech")
        text, first, last = pipeline.transcript_lines(analysis.speech, from_word, to_word)
        data = {"content_hash": cache.hash, "language": analysis.speech.language, "total_words": len(analysis.speech.words),
                "first_word": first, "last_word": last, "lines": text,
                "events": pipeline.transcript_events(analysis, first, last)}
        _out(data, json_, text)

    _guard(go, json_)


@app.command()
def semantic(
    video: Annotated[Path | None, typer.Argument(help="Eingabevideo")] = None,
    from_file: Annotated[Path | None, typer.Option("--from", help="JSON mit cuts/chapters/highlights/flags auf Wort-IDs")] = None,
    source: Annotated[str | None, typer.Option("--source", help="Absender, z. B. agent:claude-code")] = None,
    append: Annotated[bool, typer.Option("--append", help="Mit vorhandener Stufe 3 vereinigen statt ersetzen")] = False,
    instructions: Annotated[bool, typer.Option("--instructions", help="Anleitung für den Agenten ausgeben (prompts/semantic_v2.md)")] = False,
    json_: JsonFlag = False,
    cache_dir: CacheOpt = None,
) -> None:
    """Stufe 3 ohne API-Key: der steuernde Agent liefert die semantischen Cuts selbst (nur Wort-IDs).
    Validiert, schreibt semantic.json und rechnet die Fusion neu."""

    def go():
        if instructions:
            text = load_prompt()
            _out({"instructions": text}, json_, text)
            return
        if video is None or from_file is None:
            raise ValueError("Video und --from <datei.json> angeben, oder --instructions")
        if not from_file.exists():
            raise FileNotFoundError(from_file)
        sub = SemanticSubmission.model_validate_json(from_file.read_text(encoding="utf-8"))
        if source:
            sub.source = source
        info = pipeline.submit_semantic(video, sub, append, stderr_progress, cache_dir)
        _out(info, json_, f"{info['llm_cuts']} Stufe-3-Cuts, {info['rejected']} verworfen, {info['cuts']} Cuts gesamt")

    _guard(go, json_)


@app.command()
def events(
    video: VideoArg,
    json_: JsonFlag = False,
    force: Annotated[bool, typer.Option("--force", help="Stufe 1b neu rechnen")] = False,
    pending: Annotated[bool, typer.Option("--pending", help="Offene Fenster für Ebene C mit Bildpfaden ausgeben")] = False,
    judge: Annotated[Path | None, typer.Option("--judge", help="JSON mit Urteilen zu offenen Fenstern (EventJudgments)")] = None,
    source: Annotated[str | None, typer.Option("--source", help="Absender der Urteile, z. B. agent:claude-code")] = None,
    no_vision: Annotated[bool, typer.Option("--no-vision", help="Ohne Vision-LLM (Ebene C)")] = False,
    budget: Annotated[int | None, typer.Option("--budget", help="Max. Vision-LLM-Aufrufe")] = None,
    cache_dir: CacheOpt = None,
) -> None:
    """Stufe 1b: Ereignisse erkennen (Pose, CLAP, X-CLIP, VideoMAE, Vision-LLM) bzw. aus dem Cache zeigen.
    Mit Transkript im Cache kommen die Events auch als Wort-ID-Spannen. --judge reicht Urteile des Agenten ein
    (Ebene C ohne API-Key, Anleitung: prompts/vision_event_v1.md), danach wird Stufe 4 neu gerechnet."""

    def go():
        if judge is not None:
            if not judge.exists():
                raise FileNotFoundError(judge)
            sub = EventJudgments.model_validate_json(judge.read_text(encoding="utf-8"))
            if source:
                sub.source = source
            info = pipeline.submit_event_judgments(video, sub, stderr_progress, cache_dir)
            _out(info, json_, f"{info['count']} Events ({info['confirmed']} bestätigt), {info['rejected']} Urteile verworfen")
            return
        cache, analysis = pipeline.run_events(video, force, not no_vision, budget, stderr_progress, cache_dir)
        info = pipeline.events_info(cache, analysis, pending=pending)
        lines = [f"{e['id']:>28}  {e['start']:8.2f}-{e['end']:8.2f}  {e['status']:<9} {e['confidence']:.2f}  "
                 f"{','.join(e['sources'])}" for e in info["events"]]
        if pending:
            lines += [f"offen {w['id']}: {w['start']:.1f}-{w['end']:.1f} {w['candidates']} ({w['reason']})" for w in info["windows"]]
        _out(info, json_, "\n".join(lines) or "Keine Events")

    _guard(go, json_)


@app.command()
def schema(json_: JsonFlag = True) -> None:
    """JSON-Schema aller Ausgaben (Analysis, Decisions, ProgressEvent, Cut)."""
    _out(json_schema(), True)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
    cache_dir: CacheOpt = None,
) -> None:
    """FastAPI-Server starten."""
    import os

    import uvicorn

    if cache_dir:
        os.environ["VISUALCUT_CACHE"] = str(cache_dir.resolve())
    uvicorn.run("visualcut.api.app:app", host=host, port=port, log_level="info")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
