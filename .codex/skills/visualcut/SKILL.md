---
name: visualcut
description: Rohvideo (Talking-Head, Tutorial, Podcast) lokal analysieren und framegenaue Schnittvorschläge für DaVinci Resolve erzeugen, erklären, annehmen oder verwerfen und als FCPXML/EDL exportieren. Nutzen, wenn jemand ein Video schneiden, Füllwörter, Retakes oder Pausen finden, Kapitel oder Highlights eines Videos kennen oder eine Schnittliste für Resolve haben will.
---

# VisualCut

Lokales Werkzeug: Video bleibt auf dem Rechner. Die semantische Stufe (Abschweifungen, Fehlstarts, Redundanzen, Kapitel) übernimmst du selbst auf Wort-IDs; ein API-Key ist nicht nötig. Ergebnis sind Cuts mit Wort-IDs, Sekunden, Frames, Grund (`reason`), Konfidenz und Begründung (`note`). Ein Mensch prüft das Ergebnis im NLE, du lieferst Vorschläge und Erklärungen.

## Zugang

Zwei gleichwertige Wege, beide rufen dieselben Kernfunktionen:

- **MCP-Server `visualcut`** (wenn registriert): Tools `analyze`, `get_cuts`, `decide`, `export`, `get_transcript_path`, `semantic_instructions`, `get_transcript`, `submit_semantic`, `schema`.
- **CLI** `visualcut <befehl> --json`: dann steht ausschließlich JSON auf stdout, Fortschritt als JSON-Lines auf stderr. Exit-Codes: 0 ok, 2 Eingabefehler, 3 Stufe fehlgeschlagen, 4 Cache ungültig.

Große Daten kommen immer als Pfad: `analysis.json` (alles) und `speech.json` (Transkript mit Wort-IDs) liegen unter `.visualcut/<hash>/`. Lies dort gezielt nach, statt alles in den Kontext zu laden.

## Workflow

1. **Analysieren:** `analyze(path)` bzw. `visualcut analyze video.mp4 --json --summary`. Läuft ingest, technical (Stille, Szenen), speech (Whisper-Transkript), semantic (Claude, nur mit `ANTHROPIC_API_KEY`) und fusion (Snapping auf Frames). Dauert bei langen Videos Minuten; fertige Stufen kommen aus dem Cache, `force=True` rechnet neu. Sprache mit `language="en"` setzen, wenn das Video nicht deutsch ist. Ohne API-Key läuft alles, nur ohne LLM-Cuts (`stage_skipped`).
2. **Stufe 3 selbst machen:** Lies `semantic_instructions()` bzw. `visualcut semantic --instructions` einmal und befolge die Regeln dort. Hole das Transkript blockweise mit `get_transcript(path, start_word=0, max_words=2000)` bzw. `visualcut transcript video.mp4 --json --from-word 0 --to-word 1999` (`next_word` bzw. `last_word` sagt, wo es weitergeht). Reiche Cuts, Kapitel, Highlights und Flags mit `submit_semantic(path, cuts=[{start_word, end_word, reason, confidence, note}], chapters=[...], source="agent:<dein-name>")` bzw. `visualcut semantic video.mp4 --from cuts.json --source agent:<dein-name>` ein. Bei mehreren Blöcken ab dem zweiten `append=True`. Verwende nur IDs aus dem Transkript; die Antwort nennt in `rejected`, wie viele Einträge verworfen wurden. Danach sind die Fusion und `get_cuts` aktuell.
3. **Cuts erklären:** `get_cuts(path, min_confidence=0.6)` bzw. `visualcut cuts video.mp4 --json --min-confidence 0.6`. Jeder Cut hat `reason` (filler, retake, tangent, long_pause, false_start, redundant, technical), `source` (rule oder llm), `confidence`, `note` und `maybe` (Konfidenz unter 0,6). Fasse für den Nutzer zusammen: Wie viele Cuts, wie viel Zeit fällt weg, welche sind unsicher. Mit `reasons=["retake","tangent"]` filtern.
4. **Entscheiden:** `decide(path, cut_id, "accepted" | "rejected" | "open", note)` bzw. `visualcut decide video.mp4 <id> accepted`. Schreibt `decisions.json`; Export, CLI und UI lesen dieselbe Datei. Entscheide nur, was der Nutzer bestätigt hat, oder erkläre deine Empfehlung mit der `note` des Cuts.
5. **Exportieren:** `export(path, "fcpxml")` bzw. `visualcut export video.mp4 --format fcpxml --out schnitt.fcpxml`. Angenommene Cuts werden geschnitten, offene als Marker gesetzt, verworfene ignoriert. `open_as_cut=True` schneidet auch offene. EDL und OTIO gibt es ebenfalls; `visualcut render` baut eine ffmpeg-Vorschau. Resolve übernimmt Marker aus FCPXML nicht: dafür zusätzlich `export(path, "markers-edl")` erzeugen und dem Nutzer sagen, dass er sie in Resolve über Timeline > Import > Timeline Markers from EDL auf die importierte Timeline legt (Marker kommen farbig nach Grund).
6. **Transkript nachlesen:** `get_transcript_path(path)` liefert den Pfad zu `speech.json` (Wörter mit `id`, `text`, `start`, `end`) und die Kapitel aus Stufe 3. Wenn der Nutzer nach einer Stelle fragt, suche dort nach dem Text und nenne Wort-IDs und Sekunden.

## Regeln

- Nenne nie Zeiten, die du selbst geschätzt hast. Sekunden und Frames stehen im Cut (`start`, `end`, `start_frame`, `end_frame`), Wort-IDs im Transkript.
- Bei `maybe=true` oder `confidence < 0.6` ist der Cut ein Vorschlag, kein Befehl. Sag das dem Nutzer.
- Alternativ läuft Stufe 3 über die Claude API, wenn `ANTHROPIC_API_KEY` gesetzt ist (Cent-Bereich pro Lauf, `model="claude-fable-5-1"` für schwieriges Material). `llm=False` bzw. `--no-llm` schaltet das ab. Deine eigene Einreichung ersetzt das API-Ergebnis.
- Typische Fehler: `Keine fertige Analyse im Cache` heißt zuerst `analyze`. `Cache ungültig` heißt `force=True` oder `.visualcut/<hash>` löschen. `ffmpeg fehlt` heißt ffmpeg/ffprobe auf den PATH.
- Das JSON-Schema aller Ausgaben liefert `schema()` bzw. `visualcut schema`.
