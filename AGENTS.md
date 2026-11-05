# VisualCut

Lokales Werkzeug, das Rohvideo (Talking-Head, Tutorial, Podcast) analysiert und framegenaue Schnittvorschläge für DaVinci Resolve erzeugt. Zwei Ebenen: eine technische (Szenenwechsel, Stille, Wort-Timestamps) und eine semantische (Regeln plus Claude auf Wort-IDs). Die Fusion snappt Wortintervalle auf exakte Frames in der nächsten Stille. Vollständiger Plan: `PLAN.md`. Workflow für Agenten: `skills/visualcut/SKILL.md`.

## Setup

```
uv sync --extra speech --extra dev
```

Benötigt `ffmpeg`/`ffprobe` auf dem PATH und eine Nvidia-GPU für Whisper (CPU-Fallback funktioniert, ist aber langsam). Für Stufe 3 (Claude) `ANTHROPIC_API_KEY` setzen; ohne Key läuft alles, nur ohne LLM-Cuts.

## CLI

Alle Befehle unterstützen `--json`: dann steht ausschließlich JSON auf stdout, Logs und Fortschritt (JSON-Lines) auf stderr. Keine interaktiven Prompts.

```
visualcut analyze input.mp4 --json              # alle Stufen, gibt analysis.json zurück
visualcut analyze input.mp4 --stage technical   # nur bis zu einer Stufe (ingest, technical, speech, semantic, fusion)
visualcut analyze input.mp4 --no-llm            # Stufe 3 überspringen; --model claude-fable-5-1 für schwieriges Material
visualcut cuts input.mp4 --json --min-confidence 0.7 --reason retake --reason tangent
visualcut decide input.mp4 <cut-id> accepted|rejected|open --note "..."
visualcut export input.mp4 --format fcpxml --out schnitt.fcpxml
visualcut export input.mp4 --format edl --out schnitt.edl
visualcut export input.mp4 --format markers-edl --out marker.edl   # Resolve: Timeline > Import > Timeline Markers from EDL (mit Farben)
visualcut render input.mp4 --out preview.mp4   # ffmpeg-Vorschau ohne die angenommenen Cuts (--open-as-cut: auch offene)
visualcut schema                               # JSON-Schema aller Ausgaben
visualcut serve                                # FastAPI auf http://localhost:8765
```

Exit-Codes: 0 ok, 2 Eingabefehler, 3 Stufe fehlgeschlagen, 4 Cache ungültig.

## Daten

- Cache: `.visualcut/<content-hash>/` im Arbeitsverzeichnis (überschreibbar mit `VISUALCUT_CACHE`). Pro Stufe eine JSON-Datei (`ingest.json`, `technical.json`, `speech.json`, `semantic.json`, `fusion.json`). Fertige Stufen werden übersprungen, `--force` erzwingt Neuberechnung. Kommt `semantic.json` neu dazu, rechnet die Fusion automatisch neu (`fusion.json` merkt sich das LLM-Modell).
- `decisions.json` im selben Ordner: angenommen/verworfen pro Cut. Export, CLI, API und MCP lesen dieselbe Datei über `visualcut.decisions`.
- Status eines Cuts: `open`, `accepted`, `rejected`. Offene Cuts werden beim Export als Marker gesetzt (Option `--open-as-cut`, um sie zu schneiden), verworfene fehlen.
- Jeder Cut hat `source` (`rule` oder `llm`), `reason`, `confidence`, `note` (Begründung) und `maybe` (Konfidenz unter 0,6).

## Stufe 3: Semantik (`semantic.py`), zwei Wege

**Weg A, ohne API-Key (Standard für Agenten):** Der Agent, der VisualCut steuert, ist selbst das LLM. Ablauf: `visualcut semantic --instructions` (bzw. MCP `semantic_instructions()`) lesen, `visualcut transcript video.mp4 --json` (bzw. `get_transcript(path, start_word, max_words)`) blockweise holen, Cuts/Kapitel/Highlights/Flags auf Wort-IDs zusammenstellen und per `visualcut semantic video.mp4 --from cuts.json --source agent:<name>` (bzw. `submit_semantic(path, cuts=..., ...)`) einreichen. Dateiformat: `SemanticSubmission` (siehe `visualcut schema`), alle Listen optional. `--append` vereinigt mit einer früheren Einreichung, sonst wird sie ersetzt. Validierung und Fusion sind dieselben wie bei Weg B; `rejected` in der Antwort zählt verworfene Einträge.

**Weg B, Claude API:** läuft automatisch in `visualcut analyze`, wenn `ANTHROPIC_API_KEY` gesetzt ist.


Das Transkript geht als nummerierte Wörter (`ID TEXT` pro Zeile) in Blöcken von 2000 Wörtern mit 200 Wörtern Überlappung an die Claude API (Anthropic SDK, Structured Output mit dem Schema `LLMResponse`). Prompt: `prompts/semantic_v1.md`, versioniert; eine Änderung bekommt eine neue Datei `semantic_v2.md`. Standardmodell `claude-sonnet-5-5`, Option `claude-fable-5-1`.

Das Modell liefert `chapters`, `cuts`, `highlights`, `flags`, alles nur mit Wort-IDs. Validierung in `semantic.validate`: jede ID muss im Block existieren, `start_word <= end_word`, `confidence`/`score` in [0, 1]. Ungültiges wird verworfen und als `log`-Event gemeldet, nie korrigiert. LLM-Cuts bekommen `source=llm` und die ID `llm-<start>-<end>`. Die Fusion vereint überlappende Regel- und LLM-Cuts (`semantic.merge_with_rules`, stärkerer Grund gewinnt wie in `fusion.REASON_PRIORITY`) und snappt dann wie bisher.

Ohne `ANTHROPIC_API_KEY` oder mit `--no-llm` wird die Stufe als `stage_skipped` gemeldet, nicht abgebrochen. Ein API-Fehler ist Exit-Code 3.

## API (`visualcut serve`, Port 8765)

`GET /projects`, `GET /projects/{hash}`, `POST /analyze` (Job, Felder `llm`, `llm_model`), `GET /jobs/{id}`, `WS /ws/progress/{id}`,
`GET /projects/{hash}/cuts?reason=retake`, `PUT /projects/{hash}/decisions/{cut_id}`, `POST /projects/{hash}/export`, `POST /projects/{hash}/render`.
`GET /projects/{hash}/files/{proxy|audio}` streamt Proxy-MP4 und WAV aus dem Cache (Range-Requests für den Player).
OpenAPI unter `/docs`. `GET /cuts` liefert exakt das JSON von `visualcut cuts --json` (Test erzwingt es).

## Web-UI (`ui/`, Phase 2)

Vite, React 19, TypeScript, HeroUI 3, Tailwind 4, TanStack Query/Virtual, Zustand, wavesurfer.js, react-hotkeys-hook.
Screens: Start (Pfad eintragen, Projektliste), Analyse (Stepper + Live-Log aus `/ws/progress/{id}`), Review (Player auf dem
Proxy, Wellenform mit Cut-Regionen, Transkript mit Mitlauf, Tasten J/K/L, Leertaste, A annehmen, R verwerfen, O öffnen,
↑/↓ Cut wechseln), Export, Einstellungen (Whisper-Modell, Sprache, Stufe; liegen im localStorage).

```
cd ui && npm install
npm run dev        # Vite auf http://localhost:5173, Proxy auf das Backend (visualcut serve muss auf 8765 laufen)
npm run build      # schreibt ui/dist; `visualcut serve` liefert es danach unter http://localhost:8765 aus
npm run test       # Vitest (API-Client)
npm run types      # src/api/schema.json + types.ts aus `visualcut schema` neu erzeugen (nach Änderungen an schema.py)
```

Routen sind Hash-Routen (`#/review/<hash>`), darum braucht das statische Ausliefern keinen SPA-Fallback. Die Farben der
Cut-Gründe stehen in `ui/src/lib/reasons.ts` und müssen mit `design/mockups/README.md` übereinstimmen.
`VISUALCUT_UI_DIST` überschreibt den Pfad zum gebauten Frontend.

## MCP-Server (`visualcut-mcp`, stdio)

Dünne Schicht über denselben Kernfunktionen, offizielles `mcp`-SDK. Tools: `analyze`, `get_cuts`, `decide`, `export`, `get_transcript_path`, `semantic_instructions`, `get_transcript`, `submit_semantic`, `schema`. Große Ergebnisse kommen als Pfad (`analysis.json`, `speech.json`), nie als Inhalt. Fehler kommen als Text mit `is_error`.

Registrierung: `.mcp.json` im Repo-Root (Claude Code), Snippets für Codex und OpenCode in `mcp-configs/`, T3 Code erbt von Claude Code oder Codex. Voraussetzung ist `visualcut-mcp` auf dem PATH (`uv tool install --editable .`), Details in `mcp-configs/README.md`. Ein Test prüft, dass alle Configs denselben Befehl starten.

## Beispiel-Workflow (Agent)

1. `analyze(path="talking2.mp4", language="en")` bzw. `visualcut analyze talking2.mp4 --json --summary --language en`. Ergebnis: Kennzahlen plus `analysis_path`.
2. Stufe 3 selbst übernehmen: `semantic_instructions()`, dann `get_transcript(path)` blockweise, dann `submit_semantic(path, cuts=[...], chapters=[...])`. Nur IDs aus dem Transkript, keine Sekunden.
3. `get_cuts(path, min_confidence=0.6)` und dem Nutzer erklären: Anzahl, Gründe, entfernte Zeit, unsichere Cuts (`maybe`). Für eine konkrete Stelle in `speech.json` (Pfad aus `get_transcript_path`) nachlesen.
4. Nach Rückfrage `decide(path, cut_id, "accepted")` bzw. `"rejected"`.
5. `export(path, format="fcpxml")`, Pfad an den Nutzer, Import in Resolve.

## Umgebung (Stand 2026-11-05)

RTX 4090 mit 24 GB VRAM, darum Whisper `large-v3` float16 als Standard. ffmpeg 9 (kein `-vsync`, stattdessen `-fps_mode`).
PyAV 19 ist mit faster-whisper 1.2 inkompatibel (`metadata_errors`), deshalb lädt `speech.py` das WAV selbst als Array.
Sprach-Fixture `tests/fixtures/speech_de.mp4` entsteht per Windows-TTS (`make_speech_fixture.py`), nicht im Repo.

## Regeln für Änderungen

- Datenmodelle nur in `src/visualcut/schema.py` (Pydantic v2). `visualcut schema` muss danach weiter laufen, danach `cd ui && npm run types`.
- Die Kernfunktionen (`ingest`, `technical`, `speech`, `semantic`, `fusion`, `export`) sind reine Bibliothek. CLI, API, UI und MCP rufen dieselben Funktionen auf (`pipeline.require_analysis`, `pipeline.select_cuts`, `pipeline.summary`), keine Sonderlogik.
- Ein LLM gibt niemals Sekundenwerte aus, nur Wort-IDs. Ungültige IDs werden verworfen und geloggt, nicht korrigiert.
- Tests: `uv run pytest` und `cd ui && npm run test`. Das synthetische Fixture wird per ffmpeg erzeugt, kein echtes Video nötig. Die MCP-Tests laufen gegen den Cache von `talking2.mp4` (geskippt, wenn er fehlt), der Integrationstest mit echter Claude-API nur mit `ANTHROPIC_API_KEY`. LLM-Antworten werden in Tests konstruiert (`FakeClient` in `tests/test_semantic.py`).
- `skills/visualcut/SKILL.md` und `.codex/skills/visualcut/SKILL.md` müssen identisch bleiben (Test).
