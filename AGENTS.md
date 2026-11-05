# VisualCut

Lokales Werkzeug, das Rohvideo (Talking-Head, Tutorial, Podcast) analysiert und framegenaue Schnittvorschläge für DaVinci Resolve erzeugt. Zwei Ebenen: eine technische (Szenenwechsel, Stille, Wort-Timestamps, dazu Ereignisse im Bild und Ton wie Tanzen oder Lachen) und eine semantische (Regeln plus Claude auf Wort-IDs). Die Fusion snappt Wortintervalle auf exakte Frames in der nächsten Stille. Vollständiger Plan: `PLAN.md`. Workflow für Agenten: `skills/visualcut/SKILL.md`.

## Setup

```
uv sync --extra speech --extra dev                  # Kern, Whisper, Tests
uv sync --extra speech --extra events --extra dev   # dazu Stufe 1b (rtmlib, MediaPipe, transformers für CLAP/X-CLIP/VideoMAE)
```

`uv sync` entfernt Extras, die nicht genannt sind: wer die Desktop-App baut, nimmt `--extra desktop` mit dazu. Ohne das Extra `events` läuft alles, Stufe 1b meldet dann `stage_skipped`. Die Modelle (RTMPose rund 30 MB, CLAP, X-CLIP, VideoMAE je einige Hundert MB) lädt der erste Lauf aus dem Netz; die Desktop-Exe bündelt sie noch nicht.

Benötigt `ffmpeg`/`ffprobe` auf dem PATH und eine Nvidia-GPU für Whisper (CPU-Fallback funktioniert, ist aber langsam). Für Stufe 3 (Claude) `ANTHROPIC_API_KEY` setzen; ohne Key läuft alles, nur ohne LLM-Cuts.

## CLI

Alle Befehle unterstützen `--json`: dann steht ausschließlich JSON auf stdout, Logs und Fortschritt (JSON-Lines) auf stderr. Keine interaktiven Prompts.

```
visualcut analyze input.mp4 --json              # alle Stufen, gibt analysis.json zurück
visualcut analyze input.mp4 --stage technical   # nur bis zu einer Stufe (ingest, technical, events, speech, semantic, fusion)
visualcut analyze input.mp4 --no-events         # Stufe 1b überspringen; --no-vision nur ohne Vision-LLM, --vision-budget 10
visualcut analyze input.mp4 --no-llm            # Stufe 3 überspringen; --model claude-fable-5-1 für schwieriges Material
visualcut cuts input.mp4 --json --min-confidence 0.7 --reason retake --reason tangent
visualcut events input.mp4 --json               # Stufe 1b rechnen bzw. aus dem Cache; mit Transkript auch als Wort-ID-Spannen
visualcut events input.mp4 --json --pending     # dazu die offenen Fenster für Ebene C mit Pfaden zu den Einzelbildern
visualcut events input.mp4 --judge urteile.json --source agent:claude-code   # Ebene C ohne API-Key: Urteile des Agenten
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
- `events.json` (Stufe 1b): finale Events, Rohdetektionen pro Quelle, offene Fenster für Ebene C, Urteile, Bewegungsenergie bei 5 fps. Einzelbilder der Fenster unter `event_frames/`. `events.yaml` im Repo-Root ist die Ereignisliste; eine `events.yaml` im Cache-Ordner eines Projekts hat Vorrang, `VISUALCUT_EVENTS` zeigt auf eine andere globale Datei. Ändern sich Prompts, rechnet Stufe 1b beim nächsten Lauf neu; Anzeigename und Wirkung wirken ohne Neuberechnung.
- `analysis.json` enthält `events` (nur die finalen) und `highlights` mit Sekunden (nach der Fusion an Events ausgerichtet). `fusion.json` merkt sich einen Fingerabdruck der Events und rechnet neu, wenn sie sich ändern.

## Stufe 1b: Ereigniserkennung (`events/`)

Erkennt, *was* im Bild und im Ton passiert. Drei Ebenen, Modelle nacheinander geladen und entladen (VRAM). stdout ist während der Modellarbeit auf stderr umgeleitet, weil rtmlib sonst Ladehinweise in das JSON bzw. das MCP-Protokoll druckt.

- **Ebene A, über das ganze Video.** `pose.py`: RTMPose (rtmlib, ONNX, YOLOX-tiny einmal pro Sekunde, Boxen dazwischen aus den Gelenken, höchstens 2 Personen) bei 5 fps, MediaPipe Pose als CPU-Fallback. Daraus Ganzkörper-, Rumpf- und Unterkörperenergie (Verschiebung in Personenhöhen pro Sekunde), Personenzahl und Periodizität. Kandidaten: `dancing` (Unterkörper sichtbar und in Bewegung, mindestens 3 s), `empty_frame` (niemand im Bild, 2 s), `standing_up`/`sitting_down` (Rumpfmitte springt um 12 % der Bildhöhe). `audio_tags.py`: CLAP Zero-Shot (`laion/clap-htsat-unfused`) auf 2-s-Fenstern, mit festen Sprach-Vergleichsklassen; ohne sie hält CLAP aufgeregtes Sprechen für Lachen.
- **Ebene B, auf Kandidatenfenstern plus Raster.** `action.py`: X-CLIP (`microsoft/xclip-base-patch32`) auf 2-s-Clips mit 8 Frames aus den Fenstern von Ebene A, den Audio-Events und den Szenenwechseln, dazu ein Clip alle 10 s. VideoMAE (`MCG-NJU/videomae-base-finetuned-kinetics`) prüft Clips nach, deren Typ eine `kinetics`-Liste hat (Summe der passenden Kinetics-Klassen ab 0,15).
- **Ebene C, nur bei Unsicherheit.** `vision_llm.py`: X-CLIP zwischen 0,4 und 0,7 oder ein Widerspruch (Unterkörper in Bewegung, X-CLIP sagt Hintergrund) ergibt ein Fenster mit 6 Einzelbildern (512 px). Claude antwortet per Structured Output (`LLMEventJudgment`: Typ aus `events.yaml` oder `none`, Konfidenz, Beschreibung, nie Zeitangaben), unsicherste Fenster zuerst, hartes Budget `vision_budget` (Standard 40). Eine zweite Runde holt aus dem Restbudget Beschreibungen für bestätigte Highlight-Events. Prompt `prompts/vision_event_v1.md`. Ohne `ANTHROPIC_API_KEY` bleiben die Fenster offen, und der steuernde Agent beurteilt sie (Weg A wie in Stufe 3): `visualcut events --pending` bzw. MCP `get_events`, Bilder ansehen, `visualcut events --judge` bzw. `judge_events`. Unbekannte Fenster oder Typen werden verworfen und gezählt.

`fuse.py` kombiniert nach den vier Regeln aus PLAN.md: überlappende Detektionen gleichen Typs vereinen (Konfidenz gewichtet gemittelt, pro Quelle erst gemittelt, Ebene C doppelt, A halb); `confirmed` ab zwei Quellen oder mit Ebene C, sonst `candidate`; Grenzen von Typen mit `motion: true` aus der Pose-Energie verfeinern (erstes bzw. letztes Sample über der Schwelle, Suche ±2 s); unter 1 s verwerfen außer reine Audio-Events. Ein Urteil `none` streicht Kandidaten im Fenster. Die Fusion ist eine reine Funktion von `events.json` und `events.yaml`; Urteile und Katalogänderungen brauchen keine Modelle.

`events.yaml`: pro Eintrag `type` (Schlüssel), `label` (Anzeige), `prompt` (X-CLIP), `audio_prompt` (CLAP), `kinetics`, `effect` (`highlight`, `marker`, `cut`), `background` (nur Vergleichsklasse) und `motion`. Standardliste: Tanzen, Aufstehen, Hinsetzen, Gehen, etwas in die Kamera zeigen, auf den Bildschirm zeigen, Trinken, Lachen, Applaus, Musik, niemand im Bild, dazu die Vergleichsklassen „spricht in die Kamera" und „nichts passiert".

Weitergabe:
- **Stufe 3:** bekommt die Events pro Block als Wort-ID-Spannen, bei Weg B im Prompt `semantic_v2.md` unter `## Ereignisse`, bei Weg A im Feld `events` von `get_transcript` bzw. `visualcut transcript`. Ohne Sprache im Event zählen das Wort davor und das danach, mit `spoken=false`.
- **Stufe 4, Regel 8:** Ein Cut, der ganz in einem bestätigten Event liegt, entfällt. Ragt er hinein, endet er am Event-Start bzw. beginnt am Event-Ende, aus angeschnittenen Wörtern herausgeschoben. Events mit Wirkung `cut` und Kandidaten blockieren nicht. Highlights aus Stufe 3, die ein bestätigtes Event berühren, umfassen das ganze Event und beginnen 500 ms vor ihm.
- **Export:** bestätigte Events als grüne Marker (FCPXML und `markers-edl`), Kandidaten nicht.

Kalibrierung (2026-11-05, Tanzvideo und Twitch-Talking-Head): Ganzkörper- und Rumpfenergie trennen Tanzen und Gestikulieren nicht, die Unterkörperenergie schon (Schwelle 0,08, Unterkörper in 50 % der Samples sichtbar).
- **Tanzvideo:** `dancing` bestätigt ab 11,4 s (pose, xclip, videomae).
- **Talking Head:** kein Tanz-Kandidat, zwei bestätigte Lach-Events (clap, xclip).
- **Laufzeit:** rund 1 bis 2 min für 3,5 min Video. Die Pose läuft auf der CPU mit etwa 15 ms pro Frame; onnxruntime-gpu würde mit dem `onnxruntime` von faster-whisper kollidieren.

## Stufe 3: Semantik (`semantic.py`), zwei Wege

**Weg A, ohne API-Key (Standard für Agenten):** Der Agent, der VisualCut steuert, ist selbst das LLM. Ablauf: `visualcut semantic --instructions` (bzw. MCP `semantic_instructions()`) lesen, `visualcut transcript video.mp4 --json` (bzw. `get_transcript(path, start_word, max_words)`) blockweise holen, Cuts/Kapitel/Highlights/Flags auf Wort-IDs zusammenstellen und per `visualcut semantic video.mp4 --from cuts.json --source agent:<name>` (bzw. `submit_semantic(path, cuts=..., ...)`) einreichen. Dateiformat: `SemanticSubmission` (siehe `visualcut schema`), alle Listen optional. `--append` vereinigt mit einer früheren Einreichung, sonst wird sie ersetzt. Validierung und Fusion sind dieselben wie bei Weg B; `rejected` in der Antwort zählt verworfene Einträge.

**Weg B, Claude API:** läuft automatisch in `visualcut analyze`, wenn `ANTHROPIC_API_KEY` gesetzt ist.


Das Transkript geht als nummerierte Wörter (`ID TEXT` pro Zeile) in Blöcken von 2000 Wörtern mit 200 Wörtern Überlappung an die Claude API (Anthropic SDK, Structured Output mit dem Schema `LLMResponse`). Prompt: `prompts/semantic_v2.md` (v2: Events aus Stufe 1b als Kontext), versioniert; eine Änderung bekommt eine neue Datei `semantic_v3.md`. Standardmodell `claude-sonnet-5-5`, Option `claude-fable-5-1`.

Das Modell liefert `chapters`, `cuts`, `highlights`, `flags`, alles nur mit Wort-IDs. Validierung in `semantic.validate`: jede ID muss im Block existieren, `start_word <= end_word`, `confidence`/`score` in [0, 1]. Ungültiges wird verworfen und als `log`-Event gemeldet, nie korrigiert. LLM-Cuts bekommen `source=llm` und die ID `llm-<start>-<end>`. Die Fusion vereint überlappende Regel- und LLM-Cuts (`semantic.merge_with_rules`, stärkerer Grund gewinnt wie in `fusion.REASON_PRIORITY`) und snappt dann wie bisher.

Ohne `ANTHROPIC_API_KEY` oder mit `--no-llm` wird die Stufe als `stage_skipped` gemeldet, nicht abgebrochen. Ein API-Fehler ist Exit-Code 3.

## API (`visualcut serve`, Port 8765)

`GET /projects`, `GET /projects/{hash}`, `POST /analyze` (Job, Felder `llm`, `llm_model`, `events`, `vision`), `GET /jobs/{id}`, `WS /ws/progress/{id}`,
`GET /projects/{hash}/cuts?reason=retake`, `PUT /projects/{hash}/decisions/{cut_id}`, `POST /projects/{hash}/export`, `POST /projects/{hash}/render`.
`GET /projects/{hash}/files/{proxy|audio}` streamt Proxy-MP4 und WAV aus dem Cache (Range-Requests für den Player).
`GET /projects/{hash}/events?pending=true` (dasselbe JSON wie `visualcut events --json`), `POST /projects/{hash}/events/judgments` (`EventJudgments`),
`GET`/`PUT /events/catalog` lesen und schreiben die globale `events.yaml` (der Kommentarkopf bleibt erhalten).
OpenAPI unter `/docs`. `GET /cuts` liefert exakt das JSON von `visualcut cuts --json` (Test erzwingt es).

## Web-UI (`ui/`, Phase 2)

Vite, React 19, TypeScript, HeroUI 3, Tailwind 4, TanStack Query/Virtual, Zustand, wavesurfer.js, react-hotkeys-hook.
Screens: Start (Pfad eintragen, Projektliste), Analyse (Stepper + Live-Log aus `/ws/progress/{id}`), Review (Player auf dem
Proxy, Wellenform mit Cut-Regionen, Transkript mit Mitlauf, Tasten J/K/L, Leertaste, A annehmen, R verwerfen, O öffnen,
↑/↓ Cut wechseln, Event-Spur unter der Wellenform: bestätigt grün `#17C964`, Kandidaten gestrichelt, Klick springt 0,5 s davor),
Export, Einstellungen (Whisper-Modell, Sprache, Stufe im localStorage; Editor für `events.yaml` mit Vision-Budget über die API).
Der Analyse-Stepper zeigt die Stufen 0, 1, 1b, 2, 3 und 4.

```
cd ui && npm install
npm run dev        # Vite auf http://localhost:5173, Proxy auf das Backend (visualcut serve muss auf 8765 laufen)
npm run build      # schreibt ui/dist; `visualcut serve` liefert es danach unter http://localhost:8765 aus
npm run test       # Vitest (API-Client, Event-Hilfen)
npm run types      # src/api/schema.json + types.ts aus `visualcut schema` neu erzeugen (nach Änderungen an schema.py)
```

Routen sind Hash-Routen (`#/review/<hash>`), darum braucht das statische Ausliefern keinen SPA-Fallback. Die Farben der
Cut-Gründe stehen in `ui/src/lib/reasons.ts` und müssen mit `design/mockups/README.md` übereinstimmen.
`VISUALCUT_UI_DIST` überschreibt den Pfad zum gebauten Frontend.

## Desktop-App (`desktop.py`, `packaging/`)

`visualcut-desktop` (bzw. `uv run python -m visualcut.desktop`) startet das Backend im selben Prozess und zeigt die UI in einem nativen Fenster (pywebview, WebView2). Im Fenster gibt es einen Knopf „Datei wählen" mit Windows-Dateidialog, und Drag-and-drop liefert den vollen Pfad.

Eigenständige Exe, USB-portabel: `packaging\build.ps1` (UI bauen, Icon, PyInstaller, `bundle_models.py`) schreibt `dist\VisualCut\` mit `VisualCut.exe`, Python, CUDA-Torch, ffmpeg, UI, NLTK-Daten und den Modellen (Whisper large-v3 und medium, Alignment de/en), rund 10 GB. Der Ordner ist in sich geschlossen: Cache, Log, Fensterprofil und Modelle liegen in `dist\VisualCut\data\`, nichts wird außerhalb geschrieben, und mit mitgelieferten Modellen läuft die Exe offline (`HF_HUB_OFFLINE`). Gespeicherte Cache-Pfade werden beim Laden auf den aktuellen Ort umgebogen, ein anderer Laufwerksbuchstabe am USB-Stick ist also kein Problem; der Pfad zum Originalvideo wird bei der nächsten Analyse aktualisiert. Achtung: Ein Neubau mit PyInstaller löscht `dist\VisualCut` samt `data\`. Alignment für andere Sprachen als de/en lädt whisperX bei Bedarf aus dem Netz. Voraussetzung auf dem Zielrechner: Windows 10/11, Nvidia-Treiber für CUDA 12.8 (sonst CPU, langsam), WebView2 (bei Windows 11 vorhanden).

## MCP-Server (`visualcut-mcp`, stdio)

Dünne Schicht über denselben Kernfunktionen, offizielles `mcp`-SDK. Tools: `analyze`, `get_cuts`, `decide`, `export`, `get_events`, `judge_events`, `get_transcript_path`, `semantic_instructions`, `get_transcript`, `submit_semantic`, `schema`. Große Ergebnisse kommen als Pfad (`analysis.json`, `speech.json`), nie als Inhalt. Fehler kommen als Text mit `is_error`.

Registrierung: `.mcp.json` im Repo-Root (Claude Code), Snippets für Codex und OpenCode in `mcp-configs/`, T3 Code erbt von Claude Code oder Codex. Alle Configs starten `uv run visualcut-mcp` mit dem Repo als Arbeitsverzeichnis, also im Projekt-venv mit Whisper (`uv sync --extra speech`). Details in `mcp-configs/README.md`. Ein Test prüft, dass alle Configs denselben Befehl starten.

## Beispiel-Workflow (Agent)

1. `analyze(path="talking2.mp4", language="en")` bzw. `visualcut analyze talking2.mp4 --json --summary --language en`. Ergebnis: Kennzahlen plus `analysis_path`.
2. Offene Ereignis-Fenster beurteilen (optional): `get_events(path)`, die Einzelbilder in `windows[].frames` ansehen, `judge_events(path, judgments=[...])`.
3. Stufe 3 selbst übernehmen: `semantic_instructions()`, dann `get_transcript(path)` blockweise, dann `submit_semantic(path, cuts=[...], chapters=[...])`. Nur IDs aus dem Transkript, keine Sekunden.
4. `get_cuts(path, min_confidence=0.6)` und dem Nutzer erklären: Anzahl, Gründe, entfernte Zeit, unsichere Cuts (`maybe`). Für eine konkrete Stelle in `speech.json` (Pfad aus `get_transcript_path`) nachlesen.
5. Nach Rückfrage `decide(path, cut_id, "accepted")` bzw. `"rejected"`.
6. `export(path, format="fcpxml")`, Pfad an den Nutzer, Import in Resolve.

## Umgebung (Stand 2026-11-05)

RTX 4090 mit 24 GB VRAM, darum Whisper `large-v3` float16 als Standard. ffmpeg 9 (kein `-vsync`, stattdessen `-fps_mode`).
PyAV 19 ist mit faster-whisper 1.2 inkompatibel (`metadata_errors`), deshalb lädt `speech.py` das WAV selbst als Array.
Sprach-Fixture `tests/fixtures/speech_de.mp4` entsteht per Windows-TTS (`make_speech_fixture.py`), nicht im Repo.

## Regeln für Änderungen

- Datenmodelle nur in `src/visualcut/schema.py` (Pydantic v2). `visualcut schema` muss danach weiter laufen, danach `cd ui && npm run types`.
- Die Kernfunktionen (`ingest`, `technical`, `speech`, `semantic`, `fusion`, `export`) sind reine Bibliothek. CLI, API, UI und MCP rufen dieselben Funktionen auf (`pipeline.require_analysis`, `pipeline.select_cuts`, `pipeline.summary`), keine Sonderlogik.
- Ein LLM gibt niemals Sekundenwerte aus, nur Wort-IDs. Ungültige IDs werden verworfen und geloggt, nicht korrigiert.
- Tests: `uv run pytest` und `cd ui && npm run test`. Das synthetische Fixture wird per ffmpeg erzeugt, kein echtes Video nötig. Die MCP-Tests laufen gegen den Cache von `talking2.mp4` (geskippt, wenn er fehlt), der Integrationstest mit echter Claude-API nur mit `ANTHROPIC_API_KEY`. LLM-Antworten werden in Tests konstruiert (`FakeClient` in `tests/test_semantic.py`, `FakeVision` in `tests/test_events.py`). Tests mit echten Modellgewichten (Marker `models`, Negativtest: das synthetische Video liefert kein `dancing`) laufen nur mit dem Extra `events`; das Fixture `analyzed` legt eine leere Stufe 1b an, damit die übrigen Tests keine Modelle laden.
- `skills/visualcut/SKILL.md` und `.codex/skills/visualcut/SKILL.md` müssen identisch bleiben (Test).
