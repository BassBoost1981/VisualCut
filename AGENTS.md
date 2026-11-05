# VisualCut

Lokales Werkzeug, das Rohvideo (Talking-Head, Tutorial, Podcast) analysiert und framegenaue Schnittvorschläge für DaVinci Resolve erzeugt. Zwei Ebenen: eine technische (Szenenwechsel, Stille, Wort-Timestamps) und eine semantische (Regeln, später LLM auf Wort-IDs). Die Fusion snappt Wortintervalle auf exakte Frames in der nächsten Stille. Vollständiger Plan: `PLAN.md`.

## Setup

```
uv sync --extra speech --extra dev
```

Benötigt `ffmpeg`/`ffprobe` auf dem PATH und eine Nvidia-GPU für Whisper (CPU-Fallback funktioniert, ist aber langsam).

## CLI

Alle Befehle unterstützen `--json`: dann steht ausschließlich JSON auf stdout, Logs und Fortschritt (JSON-Lines) auf stderr. Keine interaktiven Prompts.

```
visualcut analyze input.mp4 --json              # alle Stufen, gibt analysis.json zurück
visualcut analyze input.mp4 --stage technical   # nur bis zu einer Stufe (ingest, technical, speech, fusion)
visualcut cuts input.mp4 --json --min-confidence 0.7
visualcut decide input.mp4 <cut-id> accepted|rejected|open --note "..."
visualcut export input.mp4 --format fcpxml --out schnitt.fcpxml
visualcut export input.mp4 --format edl --out schnitt.edl
visualcut render input.mp4 --out preview.mp4   # ffmpeg-Vorschau ohne die angenommenen Cuts (--open-as-cut: auch offene)
visualcut schema                               # JSON-Schema aller Ausgaben
visualcut serve                                # FastAPI auf http://localhost:8765
```

Exit-Codes: 0 ok, 2 Eingabefehler, 3 Stufe fehlgeschlagen, 4 Cache ungültig.

## Daten

- Cache: `.visualcut/<content-hash>/` im Arbeitsverzeichnis (überschreibbar mit `VISUALCUT_CACHE`). Pro Stufe eine JSON-Datei (`ingest.json`, `technical.json`, `speech.json`, `fusion.json`). Fertige Stufen werden übersprungen, `--force` erzwingt Neuberechnung.
- `decisions.json` im selben Ordner: angenommen/verworfen pro Cut. Export, CLI und API lesen dieselbe Datei über `visualcut.decisions`.
- Status eines Cuts: `open`, `accepted`, `rejected`. Offene Cuts werden beim Export als Marker gesetzt (Option `--open-as-cut`, um sie zu schneiden), verworfene fehlen.

## API (`visualcut serve`, Port 8765)

`GET /projects`, `GET /projects/{hash}`, `POST /analyze` (Job), `GET /jobs/{id}`, `WS /ws/progress/{id}`,
`GET /projects/{hash}/cuts`, `PUT /projects/{hash}/decisions/{cut_id}`, `POST /projects/{hash}/export`, `POST /projects/{hash}/render`.
OpenAPI unter `/docs`. `GET /cuts` liefert exakt das JSON von `visualcut cuts --json` (Test erzwingt es).

## Umgebung (Stand 2026-11-05)

RTX 4090 mit 24 GB VRAM, darum Whisper `large-v3` float16 als Standard. ffmpeg 9 (kein `-vsync`, stattdessen `-fps_mode`).
PyAV 19 ist mit faster-whisper 1.2 inkompatibel (`metadata_errors`), deshalb lädt `speech.py` das WAV selbst als Array.
Sprach-Fixture `tests/fixtures/speech_de.mp4` entsteht per Windows-TTS (`make_speech_fixture.py`), nicht im Repo.

## Regeln für Änderungen

- Datenmodelle nur in `src/visualcut/schema.py` (Pydantic v2). `visualcut schema` muss danach weiter laufen.
- Die Kernfunktionen (`ingest`, `technical`, `speech`, `fusion`, `export`) sind reine Bibliothek. CLI und API rufen dieselben Funktionen auf, keine Sonderlogik.
- Ein LLM gibt niemals Sekundenwerte aus, nur Wort-IDs.
- Tests: `uv run pytest`. Das synthetische Fixture wird per ffmpeg erzeugt, kein echtes Video nötig.
