---
name: visualcut
description: Rohvideo (Talking-Head, Tutorial, Podcast) lokal analysieren und framegenaue Schnittvorschläge für DaVinci Resolve erzeugen, erklären, annehmen oder verwerfen und als FCPXML/EDL exportieren. Nutzen, wenn jemand ein Video schneiden, Füllwörter, Retakes oder Pausen finden, Kapitel oder Highlights eines Videos kennen oder eine Schnittliste für Resolve haben will.
---

# VisualCut

Lokales Werkzeug: Video bleibt auf dem Rechner, nur der Transkript-Text geht optional an die Claude API (Stufe 3). Ergebnis sind Cuts mit Wort-IDs, Sekunden, Frames, Grund (`reason`), Konfidenz und Begründung (`note`). Ein Mensch prüft das Ergebnis im NLE, du lieferst Vorschläge und Erklärungen.

## Zugang

Zwei gleichwertige Wege, beide rufen dieselben Kernfunktionen:

- **MCP-Server `visualcut`** (wenn registriert): Tools `analyze`, `get_cuts`, `decide`, `export`, `get_transcript_path`, `schema`.
- **CLI** `visualcut <befehl> --json`: dann steht ausschließlich JSON auf stdout, Fortschritt als JSON-Lines auf stderr. Exit-Codes: 0 ok, 2 Eingabefehler, 3 Stufe fehlgeschlagen, 4 Cache ungültig.

Große Daten kommen immer als Pfad: `analysis.json` (alles) und `speech.json` (Transkript mit Wort-IDs) liegen unter `.visualcut/<hash>/`. Lies dort gezielt nach, statt alles in den Kontext zu laden.

## Workflow

1. **Analysieren:** `analyze(path)` bzw. `visualcut analyze video.mp4 --json --summary`. Läuft ingest, technical (Stille, Szenen), speech (Whisper-Transkript), semantic (Claude, nur mit `ANTHROPIC_API_KEY`) und fusion (Snapping auf Frames). Dauert bei langen Videos Minuten; fertige Stufen kommen aus dem Cache, `force=True` rechnet neu. Sprache mit `language="en"` setzen, wenn das Video nicht deutsch ist. Ohne API-Key läuft alles, nur ohne LLM-Cuts (`stage_skipped`).
2. **Cuts erklären:** `get_cuts(path, min_confidence=0.6)` bzw. `visualcut cuts video.mp4 --json --min-confidence 0.6`. Jeder Cut hat `reason` (filler, retake, tangent, long_pause, false_start, redundant, technical), `source` (rule oder llm), `confidence`, `note` und `maybe` (Konfidenz unter 0,6). Fasse für den Nutzer zusammen: Wie viele Cuts, wie viel Zeit fällt weg, welche sind unsicher. Mit `reasons=["retake","tangent"]` filtern.
3. **Entscheiden:** `decide(path, cut_id, "accepted" | "rejected" | "open", note)` bzw. `visualcut decide video.mp4 <id> accepted`. Schreibt `decisions.json`; Export, CLI und UI lesen dieselbe Datei. Entscheide nur, was der Nutzer bestätigt hat, oder erkläre deine Empfehlung mit der `note` des Cuts.
4. **Exportieren:** `export(path, "fcpxml")` bzw. `visualcut export video.mp4 --format fcpxml --out schnitt.fcpxml`. Angenommene Cuts werden geschnitten, offene als Marker gesetzt, verworfene ignoriert. `open_as_cut=True` schneidet auch offene. EDL und OTIO gibt es ebenfalls; `visualcut render` baut eine ffmpeg-Vorschau.
5. **Transkript nachlesen:** `get_transcript_path(path)` liefert den Pfad zu `speech.json` (Wörter mit `id`, `text`, `start`, `end`) und die Kapitel aus Stufe 3. Wenn der Nutzer nach einer Stelle fragt, suche dort nach dem Text und nenne Wort-IDs und Sekunden.

## Regeln

- Nenne nie Zeiten, die du selbst geschätzt hast. Sekunden und Frames stehen im Cut (`start`, `end`, `start_frame`, `end_frame`), Wort-IDs im Transkript.
- Bei `maybe=true` oder `confidence < 0.6` ist der Cut ein Vorschlag, kein Befehl. Sag das dem Nutzer.
- Stufe 3 kostet Geld (Cent-Bereich pro Lauf). Standardmodell `claude-sonnet-5-5`, bei schwierigem Material `model="claude-fable-5-1"`. `llm=False` bzw. `--no-llm` schaltet sie ab.
- Typische Fehler: `Keine fertige Analyse im Cache` heißt zuerst `analyze`. `Cache ungültig` heißt `force=True` oder `.visualcut/<hash>` löschen. `ffmpeg fehlt` heißt ffmpeg/ffprobe auf den PATH.
- Das JSON-Schema aller Ausgaben liefert `schema()` bzw. `visualcut schema`.
