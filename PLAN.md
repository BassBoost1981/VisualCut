# VisualCut: KI-gestützte Schnittpunkt-Analyse für Video

Pipeline-Plan, Stand 2026-11-05. Ziel: Ein lokales Werkzeug, das ein Rohvideo analysiert, versteht, was inhaltlich passiert, und daraus framegenaue Schnittvorschläge erzeugt. Die Ergebnisse landen als Schnittliste in DaVinci Resolve oder werden direkt mit ffmpeg gerendert.

Das Werkzeug ist agentenneutral: Claude Code, Codex, T3 Code und OpenCode steuern es über dasselbe CLI und denselben MCP-Server.

## Stand (2026-11-05, abends)

Phasen 1 bis 3 sind umgesetzt und auf GitHub (`BassBoost1981/VisualCut`, Branch `main`). Der aktuelle Funktionsumfang steht in `AGENTS.md`, das ist die verbindliche Kurzreferenz für Agenten; dieser Plan bleibt die Begründung und der Fahrplan.

Abweichungen vom ursprünglichen Plan, bewusst so entschieden:
- **Stufe 3 hat zwei Wege.** Weg A ohne API-Key: der steuernde Agent ist selbst das LLM, holt das Transkript blockweise und reicht Cuts auf Wort-IDs ein (`visualcut semantic --from`, MCP `submit_semantic`). Weg B: Claude API automatisch in `visualcut analyze`, wenn `ANTHROPIC_API_KEY` gesetzt ist.
- **Zusätzliches Exportformat `markers-edl`:** farbige Timeline-Marker für Resolve, weil der FCPXML-Import Marker nicht zuverlässig mitnimmt.
- **Desktop-App schon jetzt, mit pywebview statt Tauri.** `visualcut-desktop` startet Backend und UI in einem nativen Fenster, `packaging/build.ps1` baut eine eigenständige `VisualCut.exe` (rund 5 GB mit CUDA-Torch). Tauri entfällt.
- **Hardware geklärt:** RTX 4090 mit 24 GB VRAM, Whisper `large-v3` float16 ist Standard.

Phase 4 (Stufe 1b) ist umgesetzt, lokal auf `main`. Abweichungen und Befunde:
- **Tanz-Signal aus dem Unterkörper statt aus der Periodizität.** An einem Tanzvideo und einem Talking-Head-Stream kalibriert: Ganzkörperenergie und Periodizität der Rumpfbahn unterscheiden Tanzen und Gestikulieren nicht, die Bewegung von Hüften, Knien und Knöcheln schon. Die Periodizität fließt nur noch in die Konfidenz.
- **CLAP braucht Sprach-Vergleichsklassen.** Ohne sie hielt CLAP aufgeregtes Sprechen in 63 % der Fenster für Lachen, mit ihnen in 8 %.
- **Ebene C hat zwei Wege wie Stufe 3:** Claude mit Einzelbildern, wenn `ANTHROPIC_API_KEY` gesetzt ist, sonst beurteilt der steuernde Agent die offenen Fenster (`visualcut events --judge`, MCP `judge_events`). Gemini ist nicht eingebaut.
- **Wirkung `cut` blockiert Regel 8 nicht:** Bei einem Schnitt-Kandidaten (Trinkpause, niemand im Bild) darf geschnitten werden. Kandidaten blockieren ebenfalls nicht, nur bestätigte Events.
- **Pose auf der CPU** (etwa 15 ms pro Frame), weil `onnxruntime-gpu` mit dem `onnxruntime` von faster-whisper kollidiert. CLAP, X-CLIP und VideoMAE laufen auf der GPU.
- **Erfolgskriterien:** Das Talking-Head-Video liefert kein Tanz-Event, das Tanzvideo ein bestätigtes ab 11,4 s. Ob das auf ±500 ms stimmt, ist ohne handannotierten Sollwert nicht geprüft. Mit Stufe 3 über den steuernden Agenten (Weg A) wird das Tanz-Event zum Highlight von 10,9 bis 188,2 s (500 ms Vorlauf); ob Claude über die API es von sich aus nennt, ist ohne API-Key nicht geprüft.

Offen: Phase 5 (Verfeinerung). Die Review-Schleife mit Stilprofil und `visualcut diff` existiert noch nicht. Die Desktop-Exe bündelt die Modelle von Stufe 1b noch nicht.

---

## 1. Annahmen

| Punkt | Annahme |
|---|---|
| Material | Talking-Head, Tutorial, Podcast, Vlog. Gesprochenes Wort steht im Vordergrund. |
| Sprache | Deutsch, gelegentlich Englisch. |
| Hardware | Windows 11, Nvidia-GPU, ffmpeg 9, Python 3.13 vorhanden. |
| Schnittziel | Rohschnitt (Pausen, Füllwörter, Versprecher, Retakes, Abschweifungen) und Highlight-Clips. |
| Endkontrolle | Ein Mensch prüft im NLE. Das Tool liefert Vorschläge mit Begründung, keine finale Fassung. |
| Zugriff | Lokal auf diesem PC. Kein Cloud-Upload des Videos, nur Transkript-Text geht an das LLM. |

Wenn eine dieser Annahmen nicht stimmt (z. B. Musikvideos, Gaming-Footage, Mehrkamera), ändert sich vor allem Stufe 3 und 4.

---

## 2. Grundidee: Zwei Ebenen, eine Fusion

```
Rohvideo
   │
   ├─► Technische Ebene (deterministisch, framegenau)
   │     Szenenwechsel, Stille, Schwarzbild, Lautheit, Wort-Timestamps
   │
   ├─► Semantische Ebene (LLM, grob, versteht Inhalt)
   │     Themen, Retakes, Füllwörter, Abschweifungen, Highlights
   │
   └─► Fusion
         LLM sagt WAS raus soll (auf Wort-Ebene),
         Technik sagt WO exakt der Schnitt sitzt (auf Frame-Ebene)
            │
            ▼
      Schnittliste (OTIO/FCPXML/EDL) + Review-Report + optional Render
```

Kernregel: **Das LLM gibt niemals Sekundenwerte aus.** Es referenziert Wort-IDs aus dem Transkript. Die Umrechnung in Zeit macht der Code. Das eliminiert halluzinierte Timestamps komplett.

---

## 3. Die Stufen im Detail

### Stufe 0: Ingest und Normalisierung

- `ffprobe` liest Metadaten (Framerate, Dauer, Audiospuren, variable Framerate?).
- Proxy erzeugen: 720p, konstante Framerate, H.264. Alle Analysen laufen auf dem Proxy, Zeitstempel gelten für das Original.
- Audio extrahieren: 16 kHz Mono WAV für Whisper, 48 kHz für Lautheitsanalyse.
- Content-Hash (SHA-256 der ersten und letzten 10 MB plus Dateigröße) als Cache-Schlüssel. Jede Stufe schreibt ihr Ergebnis nach `.visualcut/<hash>/<stufe>.json`. Wiederholte Läufe überspringen fertige Stufen.

**Verifikation:** Proxy-Dauer stimmt mit Original auf ±1 Frame überein.

### Stufe 1: Technische Analyse

| Signal | Werkzeug | Ausgabe |
|---|---|---|
| Szenenwechsel | PySceneDetect (`ContentDetector` + `AdaptiveDetector`), Fallback `ffmpeg scdet` | Frame-Nummern harter Schnitte |
| Stille | `ffmpeg silencedetect` (Schwelle -35 dB, min. 150 ms) plus RMS-Kurve via `librosa` | Pausenintervalle |
| Schwarzbild / Freeze | `ffmpeg blackdetect`, `freezedetect` | Intervalle |
| Lautheit | `ffmpeg ebur128` | Lautheitsverlauf, Clipping |
| Bewegung | Optical-Flow-Magnitude pro Sekunde (OpenCV) | Ruhige vs. bewegte Phasen |

Alle Ergebnisse sind Listen von Intervallen oder Frame-Punkten. Keine Interpretation, nur Messung.

**Verifikation:** Synthetisches Testvideo (ffmpeg `testsrc` mit eingebauten harten Schnitten und Stille) muss alle Schnitte auf ±1 Frame treffen.

### Stufe 1b: Ereigniserkennung (was passiert im Bild und im Ton)

Stufe 1 misst nur, *dass* sich etwas ändert. Stufe 1b erkennt, *was* passiert: Eine Person fängt an zu tanzen, steht auf, hält ein Produkt in die Kamera, verlässt das Bild, es wird gelacht oder applaudiert, Musik setzt ein.

Drei Verfahren mit unterschiedlichen Stärken, als Kaskade geschaltet. Jedes liefert Events im gleichen Format, die Fusion am Ende kombiniert sie.

**Ebene A: Billige Signale, laufen immer über das ganze Video**

| Signal | Werkzeug | Liefert |
|---|---|---|
| Körperbewegung | RTMPose oder MediaPipe Pose, 5 fps | Gelenkpositionen pro Frame, daraus Bewegungsenergie pro Sekunde, Anzahl Personen im Bild, Person betritt oder verlässt Bild |
| Audio-Ereignisse | CLAP oder YAMNet (AudioSet-Klassen) | Lachen, Applaus, Musik, Türknallen, Klingeln, mit Zeitstempel und Konfidenz |
| Bewegungsmuster | Aus Pose-Daten abgeleitet | Rhythmische Bewegung (Periodizität der Gelenke) als Tanz-Indikator, abrupte Haltungswechsel als Aufstehen/Hinsetzen |

Ebene A kann nicht sagen „tanzt", aber sie sagt „hier bewegt sich jemand 8 Sekunden lang rhythmisch, und es läuft Musik". Das reicht, um Kandidatenfenster zu finden.

**Ebene B: Aktionserkennung, nur auf Kandidatenfenstern**

X-CLIP (Zero-Shot) als Hauptmodell, VideoMAE (Kinetics-400) als zweite Meinung.

- X-CLIP bekommt 2-Sekunden-Clips und eine Liste von Aktionsbeschreibungen als Text. Standardliste: `person dancing`, `person talking to camera`, `person standing up`, `person sitting down`, `person walking`, `person holding object towards camera`, `person pointing at screen`, `person drinking`, `person laughing`, `nothing happening`. Die Liste steht in `events.yaml` und ist pro Projekt erweiterbar, ohne Code zu ändern.
- VideoMAE liefert feste Kinetics-Klassen, davon rund 30 Tanz-Varianten (Salsa, Breakdance, Zumba, Robot-Dance ...). Dient als Bestätigung: Sagt X-CLIP „dancing" und VideoMAE eine beliebige Tanz-Klasse, steigt die Konfidenz.
- Kandidatenfenster kommen aus Ebene A (Bewegungsenergie über Schwelle, Musik erkannt, Personenzahl ändert sich) plus Szenenwechsel aus Stufe 1. Ohne Kandidaten läuft Ebene B zusätzlich grob über das ganze Video mit einem Clip alle 10 Sekunden, damit nichts Stilles verpasst wird (z. B. Produkt in die Kamera halten erzeugt kaum Bewegung).

**Ebene C: Vision-LLM, nur bei Unsicherheit oder für Kontext**

Claude (Bildsequenz, 4 bis 8 Frames pro Fenster) oder Gemini (Video direkt). Wird aufgerufen, wenn:
- Ebene B eine Konfidenz zwischen 0,4 und 0,7 liefert (unklar),
- Ebene A und B sich widersprechen (viel Bewegung, aber „nothing happening"),
- ein Event als Highlight-Kandidat gilt und eine Beschreibung in Prosa braucht („fängt an zu tanzen, bricht nach 10 Sekunden lachend ab").

Ebene C liefert zusätzlich eine Kurzbeschreibung, die ans LLM in Stufe 3 weitergegeben wird. Budget-Grenze pro Video konfigurierbar (Standard: max. 40 Aufrufe), damit die Kosten nicht davonlaufen.

**Fusion der drei Ebenen**

Jedes Verfahren schreibt Events als `{start, end, type, confidence, source}`. Die Kombination:

1. Zeitlich überlappende Events gleichen Typs aus verschiedenen Quellen werden zusammengeführt. Konfidenz wird gewichtet gemittelt: Ebene C zählt doppelt, Ebene A halb.
2. Ein Event braucht mindestens zwei zustimmende Quellen oder eine Ebene-C-Bestätigung, um `confirmed` zu werden. Sonst bleibt es `candidate`.
3. Start und Ende werden aus Ebene A verfeinert (Pose-Daten sind framegenau, X-CLIP arbeitet nur in 2-Sekunden-Fenstern): Das Event beginnt beim ersten Frame, in dem die Bewegungsenergie die Schwelle überschreitet.
4. Zu kurze Events (unter 1 Sekunde) werden verworfen, außer bei Audio-Events wie Türknallen.

Ergebnis ist eine Event-Liste mit Zeitstempeln, Typ, Konfidenz, Quellen und optional Beschreibung. Sie geht in Stufe 3 neben dem Transkript ans LLM, und sie geht in Stufe 4 als Snapping-Signal (Schnitt nicht mitten in ein Event, Highlight-Grenzen an Event-Grenzen ausrichten).

**Verifikation:** Referenzvideo mit handannotierten Events (Tanz beginnt bei 1:12, endet 1:31 usw.). Erkennungsrate pro Typ, Zeitabweichung von Start und Ende unter 500 ms. Zusätzlich ein Negativ-Test: Ruhiges Talking-Head-Video darf keine Tanz-Events liefern.

### Stufe 2: Sprache

- **Transkription:** `faster-whisper` mit `large-v3` auf der GPU. Deutsch erzwungen, VAD-Filter an.
- **Wort-Alignment:** `whisperX` für Wort-Timestamps mit ±20 ms Genauigkeit. Whisper allein ist zu grob.
- **Sprecher-Trennung:** `pyannote` Diarisierung (braucht Hugging-Face-Token, vorhanden). Nur bei mehr als einer Stimme aktiv.
- **Ausgabe:** Wortliste mit `id`, `text`, `start`, `end`, `speaker`, `confidence`.

Regelbasierte Vorarbeit auf der Wortliste (billig, kein LLM):
- Füllwort-Lexikon: ähm, äh, also, halt, quasi, sozusagen, genau (nur als Satzauftakt).
- Retake-Erkennung: Gleiche Wortfolge (fuzzy, ≥ 5 Wörter) zweimal innerhalb von 15 Sekunden. Erste Instanz wird Löschkandidat.
- Lange Pause: Stille > 1,2 s zwischen zwei Wörtern.

**Verifikation:** Referenz-Clip mit handgezähltem Transkript. Wortfehlerrate unter 8 %, Timestamp-Abweichung unter 50 ms.

### Stufe 3: Semantische Analyse (LLM)

Eingabe an das Modell: Transkript als nummerierte Wörter, in Blöcken von ca. 2.000 Wörtern mit 200 Wörtern Überlappung. Dazu die Event-Liste aus Stufe 1b, auf Wort-IDs gemappt („Event `dancing` zwischen Wort 1203 und 1290"), und optional ein Keyframe pro erkannter Szene (JPEG, 512 px) für visuellen Kontext.

Das Modell liefert strukturiertes JSON:

```json
{
  "chapters": [{"title": "...", "start_word": 0, "end_word": 412}],
  "cuts": [
    {
      "start_word": 88, "end_word": 97,
      "reason": "retake",
      "confidence": 0.92,
      "note": "Satz wird ab Wort 98 identisch wiederholt"
    }
  ],
  "highlights": [{"start_word": 1200, "end_word": 1310, "score": 0.85, "hook": "..."}],
  "flags": [{"word": 455, "type": "unclear_audio"}]
}
```

Erlaubte `reason`-Werte: `filler`, `retake`, `tangent`, `long_pause`, `false_start`, `redundant`, `technical`.

Modellwahl: `claude-sonnet-5-5` als Standard (Preis/Leistung), `claude-fable-5-1` als Option für schwieriges Material. Ein 60-Minuten-Video sind etwa 9.000 Wörter, also rund 15.000 Input-Tokens. Kosten pro Lauf im Cent-Bereich.

Validierung nach dem LLM-Aufruf: Jede Wort-ID muss existieren, `start_word ≤ end_word`, keine Überlappung mit bereits regelbasiert erkannten Cuts (sonst zusammenführen). Ungültige Einträge werden verworfen und geloggt, nicht korrigiert.

**Verifikation:** Zwei Referenzvideos mit manuell erstelltem Soll-Schnitt. Precision und Recall der Cut-Vorschläge gegen das Soll, Ziel ≥ 0,8 / ≥ 0,7.

### Stufe 4: Fusion und Snapping

Hier entsteht der eigentliche Mehrwert. Jeder Cut aus Stufe 2 und 3 ist zunächst ein Wortintervall. Daraus wird ein Frame-Intervall:

1. **Wortgrenzen holen:** `start = word[start_word].start`, `end = word[end_word].end`.
2. **In Stille snappen:** Suche die nächste Stille-Insel (Stufe 1) innerhalb ±300 ms vor `start` und nach `end`. Schnitt sitzt in der Mitte der Stille. Gibt es keine, bleibt die Wortgrenze.
3. **Szenenwechsel respektieren:** Liegt ein harter Szenenwechsel innerhalb des Cuts, wird der Cut an der Szene geteilt, nie darüber hinweg gezogen.
4. **Padding:** 80 ms Pre-Roll, 120 ms Post-Roll, damit Atmer nicht abgeschnitten klingen.
5. **Minimum-Längen:** Verbleibende Segmente unter 400 ms werden mit dem Nachbarn verschmolzen oder ebenfalls entfernt.
6. **Konfliktregeln:** `retake` schlägt `filler`. Zwei Cuts mit weniger als 250 ms Abstand werden zu einem.
7. **Bewegungscheck:** Fällt ein Schnitt in eine Phase hoher Bewegung (Stufe 1), wird er um bis zu 200 ms in die ruhigere Richtung verschoben.
8. **Event-Grenzen:** Ein Schnitt darf nicht mitten in ein `confirmed`-Event aus Stufe 1b fallen. Highlight-Clips werden an Event-Start und Event-Ende ausgerichtet, mit 500 ms Vorlauf, damit der Zuschauer sieht, wie das Tanzen anfängt.

Jeder finale Cut behält `reason`, `confidence` und `note`. Cuts mit `confidence < 0.6` werden als `maybe` markiert.

**Verifikation:** Kein Schnitt landet innerhalb eines Wortintervalls. Unit-Test mit konstruierten Wort- und Stillelisten.

### Stufe 5: Ausgabe

| Format | Zweck |
|---|---|
| **OpenTimelineIO (.otio)** | Kanonisches Format, daraus werden alle anderen erzeugt |
| **FCPXML** | Import in DaVinci Resolve, behält Marker und Clipnamen |
| **EDL (CMX 3600)** | Fallback für jedes NLE |
| **Direkt-Render** | ffmpeg `concat` mit Re-Encode, für schnelle Vorschau |
| **Review-Report (HTML)** | Transkript mit farbigen Cuts, Begründungen, Thumbnails, Vorher/Nachher-Dauer |
| **analysis.json** | Vollständiges maschinenlesbares Ergebnis für Agenten |

`maybe`-Cuts werden in Resolve als Marker gesetzt, nicht geschnitten. So sieht der Mensch sofort, wo das Tool unsicher war.

### Stufe 6: Review-Schleife

Nach dem manuellen Schnitt in Resolve kann die finale Timeline zurück exportiert werden. Ein Vergleich (`visualcut diff`) zeigt: Welche Vorschläge wurden angenommen, welche verworfen, welche Schnitte hat der Mensch zusätzlich gesetzt. Daraus entsteht ein Stilprofil (`style.json`) mit Schwellen (Pausenlänge, Füllwort-Toleranz, Aggressivität), das bei künftigen Läufen als Few-Shot-Kontext ans LLM geht.

---

## 4. Agenten-Zugriff: Ein Kern, vier Schnittstellen

Alle vier Coding-Agenten (Claude Code, Codex, T3 Code, OpenCode) sollen die Pipeline nutzen können, ohne dass für jeden eine eigene Integration gebaut wird. Darum gibt es genau einen Kern und dünne Schichten darüber: CLI, MCP-Server, Agenten-Dokumentation und die Web-UI (Abschnitt 5). Alle sprechen dieselben Kernfunktionen an, keine hat Sonderlogik.

### 4.1 Kern: Python-Paket `visualcut`

Reine Bibliothek, keine UI-Logik. Jede Stufe ist eine Funktion mit JSON-Ein- und Ausgabe. Installierbar mit `pip install -e .` oder als `uv tool install`.

### 4.2 Schicht 1: CLI (funktioniert mit jedem Agenten sofort)

Jeder Coding-Agent kann Shell-Befehle ausführen. Das CLI ist darum die universelle Schnittstelle. Regeln:

- Jeder Befehl hat `--json` und gibt dann **ausschließlich** JSON auf stdout aus. Logs gehen auf stderr.
- Exit-Codes sind stabil dokumentiert (0 ok, 2 Eingabefehler, 3 Stufe fehlgeschlagen, 4 Cache ungültig).
- Keine interaktiven Prompts. Alles über Flags.
- Lange Läufe schreiben Fortschritt als JSON-Lines auf stderr, damit ein Agent den Status mitlesen kann.

```
visualcut analyze input.mp4 --json              # alle Stufen, gibt analysis.json zurück
visualcut analyze input.mp4 --stage transcribe  # nur eine Stufe
visualcut cuts input.mp4 --min-confidence 0.7   # Cut-Liste als JSON
visualcut export input.mp4 --format fcpxml --out schnitt.fcpxml
visualcut render input.mp4 --out preview.mp4
visualcut report input.mp4 --out report.html
visualcut diff input.mp4 --final final.fcpxml   # Review-Schleife
visualcut schema                                # JSON-Schema aller Ausgaben
```

### 4.3 Schicht 2: MCP-Server (für Agenten mit MCP-Support)

Claude Code, Codex, OpenCode und T3 Code unterstützen MCP (Model Context Protocol). Der Server `visualcut-mcp` ist ein dünner Wrapper um das CLI, stdio-Transport, Python `mcp`-SDK.

Tools, bewusst wenige und grobkörnig:

| Tool | Macht |
|---|---|
| `analyze_video(path, stages?)` | Läuft die Pipeline, gibt Zusammenfassung plus Pfad zu `analysis.json` zurück |
| `get_cuts(path, min_confidence?, reasons?)` | Gefilterte Cut-Liste |
| `get_transcript(path, start?, end?)` | Transkript-Ausschnitt mit Wort-IDs |
| `export_timeline(path, format, out)` | OTIO/FCPXML/EDL schreiben |
| `render_preview(path, out, cuts?)` | ffmpeg-Render, optional mit eigener Cut-Liste |
| `apply_feedback(path, final_timeline)` | Review-Schleife, aktualisiert Stilprofil |

Große Ergebnisse (volles Transkript, komplette Analyse) werden nie direkt zurückgegeben, sondern als Dateipfad. Der Agent liest dann gezielt nach. Das schützt das Kontextfenster.

Registrierung pro Agent:

- **Claude Code:** `.mcp.json` im Projekt oder `claude mcp add visualcut -- visualcut-mcp`
- **Codex:** `~/.codex/config.toml`, Abschnitt `[mcp_servers.visualcut]`
- **OpenCode:** `opencode.json`, Abschnitt `mcp`
- **T3 Code:** nutzt Claude Code oder Codex als Backend, erbt damit deren MCP-Konfiguration. Zur Sicherheit prüfen, ob T3 eine eigene Config-Datei liest.

Ein Ordner `mcp-configs/` im Repo enthält fertige Snippets für alle vier.

### 4.4 Schicht 3: Skill und Agenten-Dokumentation

Agenten müssen wissen, **wann und wie** sie das Tool einsetzen. Dafür:

- `AGENTS.md` im Repo-Root: Wird von Codex, OpenCode und T3 Code automatisch gelesen. Enthält Kurzbeschreibung, die wichtigsten CLI-Befehle, Beispiel-Workflow, typische Fehler.
- `CLAUDE.md` verweist per einer Zeile auf `AGENTS.md`, damit keine zwei Wahrheiten existieren.
- `skills/visualcut/SKILL.md`: Skill im Anthropic-Format (Frontmatter mit `name` und `description`, dann Anleitung). Funktioniert in Claude Code direkt, OpenCode liest das gleiche Format. Für Codex liegt eine Kopie als `.codex/skills/visualcut/SKILL.md`.
- `visualcut schema` liefert das JSON-Schema, damit ein Agent Ausgaben validieren oder typisierten Code dagegen schreiben kann.

Grundsatz: Die Dokumentation beschreibt den Workflow in Prosa, keine Tool-Aufrufe im Agentenformat. So bleibt sie für alle vier gültig.

---

## 5. Benutzeroberfläche

Resolve bleibt das Werkzeug für den Feinschnitt. Die VisualCut-UI ist das Werkzeug für alles davor: Video reinziehen, Analyse laufen lassen, Vorschläge prüfen, annehmen oder verwerfen, exportieren. Sie ersetzt den HTML-Review-Report aus Stufe 5 durch eine interaktive Oberfläche.

### 5.1 Architektur

```
Browser (React + HeroUI)  ──REST/WebSocket──►  FastAPI (visualcut serve)  ──►  Python-Kern
                                                       ▲
CLI, MCP-Server ───────────────────────────────────────┘  (gleiche Kernfunktionen)
```

- **Backend:** FastAPI im selben Python-Paket, Start mit `visualcut serve`. REST für Projekte, Analyse, Cuts, Export. WebSocket für Fortschritt (dieselben JSON-Lines, die das CLI auf stderr schreibt). Serviert im Produktionsmodus das gebaute Frontend als statische Dateien, ein Befehl startet alles unter `http://localhost:8765`.
- **Frontend:** Vite, React 19, TypeScript, HeroUI, Tailwind 4. Eigener Ordner `ui/`, eigene `package.json`. Im Entwicklungsmodus läuft Vite mit Proxy auf das Backend.
- **Entscheidungen der UI sind Daten, kein Zustand.** Angenommene oder verworfene Cuts landen in `decisions.json` neben `analysis.json`. `visualcut export` und der MCP-Server lesen diese Datei genauso. Ein Agent kann also analysieren, der Mensch prüft in der UI, der Agent exportiert.
- **Später optional:** Tauri-Hülle um das gebaute Frontend für eine echte Desktop-App mit eigenem Fenster. Kein Code-Umbau nötig, weil die UI nur ein Client der API ist.

### 5.2 Screens

Mockups aller fünf Screens liegen unter `design/mockups/` (Dateien, Design-Tokens, Farbcode) und als klickbarer Canvas unter https://claude.ai/artifact/5XXJ6Lf5mFL7bKx4EFhcwi. Freigegeben am 2026-11-05 als Zielbild für Phase 2.

**Start.** Drop-Zone für Videodateien, Liste bereits analysierter Projekte aus dem Cache mit Thumbnail, Dauer, Anzahl Cuts, Datum. Statusleiste mit GPU, VRAM, geladenen Modellen.

**Analyse.** Stepper mit den Stufen 0 bis 5, jede mit Fortschrittsbalken, Dauer und Live-Log. Stufen einzeln anwählbar (nur Transkription neu laufen lassen). Abbrechen jederzeit, fertige Stufen bleiben im Cache.

**Review.** Das Herzstück, drei Bereiche:
- Oben der Videoplayer (HTML-`<video>` auf dem Proxy), Tastatur J/K/L für Rückwärts/Pause/Vorwärts, Leertaste Play.
- Darunter die Timeline mit Spuren: Wellenform, Szenenwechsel, Cuts (farbig nach `reason`), Events aus Stufe 1b, Highlights, Kapitel. Zoom mit Mausrad, Cuts an den Griffen verschiebbar, Snapping auf Wortgrenzen und Stille wird dabei live angezeigt.
- Rechts das Transkript, Wort für Wort, mitlaufend zum Video. Cuts sind inline durchgestrichen, Klick auf ein Wort springt hin, Markieren eines Bereichs erzeugt einen manuellen Cut.

Klick auf einen Cut öffnet ein Panel mit `reason`, Konfidenz, Quelle (Regel, LLM, Event) und `note`. Tasten A für annehmen, R für verwerfen, Pfeiltasten zum nächsten Cut. Filterleiste: nach `reason`, nach Konfidenz, nur `maybe`, nur offen. Oben rechts Vorher/Nachher-Dauer und wie viel Prozent rausgehen.

**Export.** Format (FCPXML, EDL, OTIO, Vorschau-Render), Zielpfad, Checkbox „`maybe` als Marker statt Schnitt". Fortschritt des Renders, danach Button zum Öffnen des Ordners.

**Einstellungen.** Whisper-Modellgröße, Schwellen (Stille, Pausenlänge, Füllwort-Toleranz), `events.yaml` als editierbare Liste, API-Keys für Claude und Gemini (nur lokal gespeichert), Vision-Budget, Stilprofil anzeigen und zurücksetzen.

### 5.3 Komponenten und Bibliotheken

| Baustein | Wahl |
|---|---|
| Komponenten | HeroUI: Button, Card, Table, Tabs, Slider, Chip, Progress, Modal, Tooltip, Select, Switch, Kbd |
| Wellenform | wavesurfer.js mit Regions-Plugin, liefert Wellenform und ziehbare Regionen |
| Timeline-Spuren | Eigene Canvas-Komponente über wavesurfer, weil kein fertiges Paket Szenen, Cuts, Events und Kapitel gemeinsam darstellt |
| Server-State | TanStack Query für REST, eigener WebSocket-Hook für Fortschritt |
| UI-State | Zustand (Auswahl, Zoom, Filter) |
| Virtuelles Transkript | TanStack Virtual, ein 60-Minuten-Video hat 9.000 Wörter |
| Tastenkürzel | react-hotkeys-hook |

Design: Dunkles Theme als Standard (Schnittarbeit, Videovorschau), HeroUI-Theme mit einer Akzentfarbe, `reason`-Farben fest definiert und in Timeline, Transkript und Filter identisch.

### 5.4 Alternative im Blick: Raven

Raven (github.com/oscar-soirey/Raven) ist eine native GUI-Bibliothek in C mit Python-Bindings, Vulkan-Rendering, eingebauter Timeline, Node-Graph, Docking und Glass-Theme. Für ein Schnitt-Tool mit reinem Python-Stack wäre sie attraktiv. Nicht gewählt, Stand November 2026: Projekt ist vier Wochen alt, API laut README instabil, kein dokumentierter Videoplayer, und die Coding-Agenten kennen es nicht.

Wiedervorlage, wenn Raven eine 1.0 hat und Video abspielen kann. Die API-Architektur hält den Weg offen: Eine Raven-UI wäre ein weiterer Client derselben FastAPI, kein Umbau des Kerns.

---

## 6. Repository-Struktur

```
VisualCut/
├── AGENTS.md                  # für Codex, OpenCode, T3
├── CLAUDE.md                  # verweist auf AGENTS.md
├── README.md
├── pyproject.toml             # Paket, CLI-Entry-Points: visualcut, visualcut-mcp
├── .mcp.json                  # Claude Code
├── mcp-configs/
│   ├── codex.toml
│   ├── opencode.json
│   └── README.md
├── skills/visualcut/SKILL.md
├── src/visualcut/
│   ├── ingest.py              # Stufe 0
│   ├── technical.py           # Stufe 1
│   ├── events/                # Stufe 1b
│   │   ├── pose.py            #   Ebene A: Pose, Bewegungsenergie
│   │   ├── audio_tags.py      #   Ebene A: CLAP/YAMNet
│   │   ├── action.py          #   Ebene B: X-CLIP, VideoMAE
│   │   ├── vision_llm.py      #   Ebene C: Claude/Gemini
│   │   └── fuse.py            #   Kombination der drei Ebenen
│   ├── speech.py              # Stufe 2
│   ├── semantic.py            # Stufe 3 (LLM, Prompt, Validierung)
│   ├── fusion.py              # Stufe 4
│   ├── export.py              # Stufe 5
│   ├── feedback.py            # Stufe 6
│   ├── cache.py
│   ├── schema.py              # Pydantic-Modelle, Quelle für `visualcut schema`
│   ├── decisions.py           # decisions.json lesen/schreiben, von UI und Export genutzt
│   ├── cli.py
│   ├── mcp_server.py
│   └── api/                   # FastAPI, `visualcut serve`
│       ├── app.py
│       ├── routes_projects.py
│       ├── routes_analysis.py
│       ├── routes_cuts.py
│       ├── routes_export.py
│       └── ws_progress.py
├── ui/                        # React + HeroUI, eigene package.json
│   ├── src/
│   │   ├── pages/             # Start, Analyse, Review, Export, Einstellungen
│   │   ├── components/
│   │   │   ├── timeline/      # Canvas-Spuren über wavesurfer
│   │   │   ├── transcript/    # virtualisiertes Wort-Transkript
│   │   │   └── player/
│   │   ├── api/               # typisierte Client-Funktionen, aus `visualcut schema` generiert
│   │   └── store/
│   ├── package.json
│   └── vite.config.ts
├── prompts/
│   ├── semantic_v1.md         # Versionierter LLM-Prompt
│   └── vision_event_v1.md     # Prompt für Ebene C
├── events.yaml                # Aktionsliste für X-CLIP, pro Projekt erweiterbar
├── tests/
│   ├── fixtures/              # synthetische Testvideos, Referenz-Transkripte
│   ├── test_technical.py
│   ├── test_events.py
│   ├── test_speech.py
│   ├── test_fusion.py
│   └── test_export.py
└── .visualcut/                     # Cache, in .gitignore
```

---

## 7. Technologie-Entscheidungen

| Bereich | Wahl | Warum |
|---|---|---|
| Sprache | Python 3.13 | Vorhanden, gesamtes ML-Ökosystem |
| Paketmanager | `uv` | Schnell, lockfile, `uv tool install` für globales CLI |
| Transkription | faster-whisper large-v3 + whisperX | GPU-schnell, Wort-Alignment |
| Diarisierung | pyannote 3.x | Standard, HF-Token vorhanden |
| Szenen | PySceneDetect | Ausgereift, Python-nativ |
| Pose | RTMPose (via rtmlib, ONNX) | Schnell auf GPU, kein PyTorch-Zwang, MediaPipe als CPU-Fallback |
| Audio-Tagging | CLAP (laion) | Zero-Shot über Text, gleiche Erweiterbarkeit wie X-CLIP |
| Aktionserkennung | X-CLIP (Hugging Face) + VideoMAE | Zero-Shot über Textliste, Kinetics-Klassen als Bestätigung |
| Vision-LLM | Claude (Frames) oder Gemini (Video) | Nur für unklare Fälle, Budget-begrenzt |
| Audio-Analyse | ffmpeg-Filter + librosa | Kein zusätzliches Framework nötig |
| LLM | Claude API, Structured Output mit JSON-Schema | Zuverlässiges JSON, Vision für Keyframes |
| Timeline | OpenTimelineIO | Ein Format, alle Exporte ableitbar |
| Datenmodelle | Pydantic v2 | Validierung, JSON-Schema-Export |
| CLI | Typer | Wenig Boilerplate, gute Hilfe-Texte |
| MCP | offizielles `mcp` Python-SDK | stdio, kein Server-Betrieb nötig |
| API | FastAPI + uvicorn | Pydantic-Modelle direkt wiederverwendbar, WebSocket eingebaut |
| Frontend | Vite, React 19, TypeScript | Standard, Agenten kennen es blind |
| UI-Komponenten | HeroUI + Tailwind 4 | Vollständiger Satz, dunkles Theme, Tastatur-Zugänglichkeit eingebaut |
| Wellenform | wavesurfer.js | Ausgereift, Regions-Plugin für ziehbare Cuts |
| Desktop-Hülle | pywebview + PyInstaller (umgesetzt) | Bleibt im Python-Prozess, kein Rust-Toolchain, WebView2 ist auf Windows 11 vorhanden; Tauri verworfen |

Bewusst **nicht** gewählt: Electron (zu schwer für eine Hülle), Next.js (kein SSR nötig, Vite reicht), Raven (siehe 5.4).

---

## 8. Umsetzung in Phasen

Jede Phase endet mit einem Zustand, der für sich allein nützlich ist.

### Phase 1: Kern und Rohschnitt

Stufen 0, 1 (nur Stille + Szenen), 2 (ohne Diarisierung), regelbasierte Cuts, Stufe 4 (Snapping), `decisions.json`, FCPXML-Export, CLI mit `--json`. Dazu das FastAPI-Grundgerüst mit Projekt-, Analyse- und Cut-Endpunkten und dem Fortschritts-WebSocket, noch ohne Frontend.

Erfolg: Ein 10-Minuten-Testvideo läuft durch, der FCPXML-Import in Resolve funktioniert, Pausen und Füllwörter sind sinnvoll markiert. Die API liefert dieselben Daten wie das CLI.

### Phase 2: Web-UI

Vite-Projekt mit HeroUI, Screens Start, Analyse, Review und Export. Player, wavesurfer-Wellenform, Cut-Spur, Transkript mit Mitlauf, Annehmen/Verwerfen mit Tastatur, Export aus der UI. Einstellungen nur das Nötigste.

Erfolg: Ein Video wird komplett in der UI analysiert, geprüft und als FCPXML exportiert, ohne das CLI anzufassen. Verworfene Cuts fehlen im Export.

### Phase 3: Semantik und Agenten-Zugang

Stufe 3 (LLM mit Wort-ID-Referenzierung), Validierung, MCP-Server, `AGENTS.md`, `SKILL.md`, MCP-Configs für alle vier Agenten. In der UI: Begründungen und Konfidenz im Cut-Panel, Kapitel-Spur, Filter nach `reason`.

Erfolg: Claude Code und Codex können per MCP ein Video analysieren und die Cut-Liste erklären. Precision ≥ 0,8 auf den Referenzvideos.

### Phase 4: Ereigniserkennung

Stufe 1b komplett: Ebene A (Pose, Audio-Tagging), Ebene B (X-CLIP, VideoMAE), Ebene C (Vision-LLM mit Budget), Fusion der Ebenen, `events.yaml`, Event-Grenzen im Snapping, Events als Eingabe für Stufe 3. In der UI: Event-Spur, `events.yaml`-Editor in den Einstellungen.

Erfolg: Im Referenzvideo wird der Tanz-Beginn auf ±500 ms erkannt, das Talking-Head-Video liefert null Falschmeldungen, und das LLM nennt das Tanz-Event als Highlight.

### Phase 5: Verfeinerung

Diarisierung, Keyframes ans LLM, Highlight-Clips, Bewegungscheck, Review-Schleife mit Stilprofil, `visualcut diff`, manuelle Cuts per Transkript-Markierung, optional Tauri-Hülle.

Erfolg: Nach drei Feedback-Runden sinkt die Zahl der manuell verworfenen Cuts messbar.

#### Umsetzungsplan Phase 5 (Stand 2026-11-06)

Reihenfolge nach Nutzen pro Aufwand. Jeder Baustein ist für sich nützlich und hat eigene Tests.

1. **Manuelle Cuts per Transkript-Markierung.** Im Review Wörter markieren (Klick, Shift-Klick), Grund wählen, als Cut mit `source=manual` speichern. Persistenz in `manual.json` im Cache-Ordner (getrennt von `decisions.json`, das nur Status hält); ein neuer manueller Cut ist sofort `accepted`. Die Fusion nimmt sie wie Regel- und LLM-Cuts auf und snappt sie gleich; bei Überlappung führt der manuelle Cut, und Regel 8 streicht ihn nicht (der Mensch hat es so gewollt). Löschen in der UI. CLI `visualcut mark`, API `POST`/`DELETE /projects/{hash}/manual`, `get_cuts` im MCP liefert sie mit. Voraussetzung für die Review-Schleife, weil zusätzliche Schnitte des Menschen dort ohnehin als `manual` auftauchen.
2. **Review-Schleife: `visualcut diff` und `style.json`.** Finale Resolve-Timeline (FCPXML bzw. EDL) zurücklesen, gegen die Vorschläge abgleichen: angenommen, verworfen, zusätzlich geschnitten (als manuelle Cuts übernehmbar). Daraus pro Projekt und global ein Stilprofil mit Schwellen (Pausenlänge, Füllwort-Toleranz, Aggressivität pro Grund) und ein paar Beispielen, das in den Regeln und als Few-Shot-Kontext in `semantic_v3.md` wirkt. Das Erfolgskriterium von Phase 5 hängt hieran, messbar über die Verwerfungsquote je Runde.
3. **Highlight-Clips als eigene Exporte.** Pro Highlight eine eigene Datei (ffmpeg-Render) bzw. eine eigene Timeline im FCPXML. CLI `visualcut export --format clips`, Knopf im Export-Screen. Klein, weil Highlights mit Sekunden schon in `analysis.json` stehen.
4. **Sprechertrennung mit pyannote.** Neues Extra `diarize`, `speaker` pro Wort in `speech.json`, Sprecher-Spur in der UI, Sprecher als Kontext für Stufe 3. Braucht ein Hugging-Face-Token für das Gated-Modell und neue Abhängigkeiten, darum weiter hinten.
5. **Kleinere Punkte aus dem Plan:** Keyframes ans LLM (Stufe 3 sieht ein Bild pro Kapitel), Bewegungscheck (Regel 7 in Stufe 4 steht noch aus).
6. **Optional: Tauri-Hülle.** Vorerst nicht, die pywebview-Desktop-App deckt Pfad-Drop und natives Fenster schon ab (siehe Stand oben).

---

## 9. Risiken und Gegenmaßnahmen

| Risiko | Gegenmaßnahme |
|---|---|
| Whisper-Timestamps driften bei langen Dateien | whisperX-Alignment, Verarbeitung in 10-Minuten-Chunks mit Überlappung |
| LLM erfindet Zeiten oder Wörter | Nur Wort-IDs erlaubt, harte Validierung, ungültige Einträge verwerfen |
| Schnitt mitten im Wort | Snapping-Regel 1 und 2, Unit-Test erzwingt es |
| Weiche Übergänge werden nicht als Szene erkannt | AdaptiveDetector zusätzlich, Schwelle pro Projekt einstellbar |
| GPU-Speicher reicht nicht für large-v3 | Fallback auf `medium` mit int8, automatisch bei OOM |
| Gestikulieren beim Reden wird als Tanzen erkannt | Periodizitäts-Check in Ebene A, Musik als Zusatzsignal, zwei Quellen nötig für `confirmed` |
| Vision-LLM-Kosten laufen davon | Hartes Budget pro Video, Ebene C nur bei Unsicherheit, Zähler im Report sichtbar |
| Drei Modelle gleichzeitig sprengen den VRAM | Stufen laufen sequentiell, Modelle werden nach jeder Stufe entladen, ONNX statt PyTorch wo möglich |
| Rechenzeit explodiert bei langen Videos | Ebene B nur auf Kandidatenfenstern plus grobem 10-Sekunden-Raster, Ebene A auf 5 fps statt voller Framerate |
| Agent überflutet sein Kontextfenster | MCP gibt Pfade statt Inhalte zurück, CLI hat `--summary` |
| Vier Agenten, vier Config-Formate driften | Eine Quelle (`mcp-configs/`), ein Test prüft, dass alle den gleichen Befehl starten |
| Prompt-Änderung verschlechtert Ergebnisse unbemerkt | Prompts versioniert, Referenzvideos als Regressionstest |
| UI und CLI driften auseinander (UI zeigt etwas, das Export ignoriert) | Beide lesen `decisions.json` über dasselbe Modul, ein Integrationstest exportiert nach UI-Entscheidung |
| Timeline wird bei langen Videos träge | Canvas statt DOM, nur sichtbarer Ausschnitt gezeichnet, Transkript virtualisiert |
| Zwei Toolchains (Python, Node) erschweren Setup | `visualcut serve` liefert gebautes Frontend mit, Node nur für UI-Entwicklung nötig |
| Browser-Player kann Originalcodec nicht abspielen | Player nutzt immer den H.264-Proxy aus Stufe 0 |

---

## 10. Offene Fragen

Diese Punkte beeinflussen Details, nicht die Architektur. Standardannahme in Klammern.

1. Welches NLE wird primär genutzt? (DaVinci Resolve)
2. Mehrkamera-Material relevant? (Nein, erst Phase 4 falls doch)
3. Darf das Transkript an die Claude API? (Ja, Video bleibt lokal)
4. Welche GPU genau, wie viel VRAM? (Bestimmt Whisper-Modellgröße)
5. Gibt es ein oder zwei typische Videos als Referenzmaterial für die Tests?
6. Welche Ereignisse sind neben Tanzen wichtig? (Standardliste in `events.yaml`, siehe Stufe 1b)
7. Gemini für Ebene C erlaubt, oder nur Claude? (Beides vorgesehen, Claude als Standard)
8. Tauri-Hülle gewünscht oder reicht der Browser? (Browser zuerst, Tauri in Phase 5)
