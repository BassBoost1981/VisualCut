# UI-Mockups

Stand 2026-11-05. Fünf Screens im dunklen HeroUI-Look, freigegeben als Zielbild für Phase 2 (siehe PLAN.md, Abschnitt 5).

Live-Canvas (klickbar, mit verlinkter Navigation): https://claude.ai/artifact/5XXJ6Lf5mFL7bKx4EFhcwi

| Datei | Screen |
|---|---|
| `Start.dc.html` | Drop-Zone, Systemstatus, Projektliste |
| `Analyse.dc.html` | Stufen-Stepper, Live-Log, Ressourcen |
| `Main.dc.html` | Review: Player, Timeline mit sieben Spuren, Cut-Panel, Transkript |
| `Export.dc.html` | Formatwahl, Optionen, Zusammenfassung, Resolve-Anleitung |
| `Einstellungen.dc.html` | Modelle, Schwellen, Ereignisliste, API-Keys, Agenten-Zugang, Stilprofil |
| `canvas.json` | Anordnung der Artboards auf dem Canvas |

## Format

Die Dateien sind Design-Canvas-Artboards (`.dc.html`). Jede ist eine vollständige HTML-Seite mit Inline-Styles, die auch direkt im Browser öffnet. Nur die Audio-Wellenform in `Main.dc.html` braucht die Canvas-Laufzeit (`support.js`), weil sie aus einer Schleife gerendert wird; alles andere ist statisches Markup.

Sie sind Vorlage, nicht Code. Die React-Komponenten in `ui/` entstehen neu, mit HeroUI-Komponenten statt Inline-Styles.

## Design-Tokens

| Token | Wert |
|---|---|
| Grund | `#09090b` |
| Panel | `#18181b`, Panel dunkel `#0f0f12` |
| Rahmen | `#27272a`, Rahmen hell `#3f3f46` |
| Text | `#ECEDEE`, gedämpft `#A1A1AA`, schwach `#71717A` |
| Primär | `#006FEE` (Button), `#338EF7` (Akzent auf dunkel) |
| Schrift | Inter (UI), JetBrains Mono (Timecodes, Log, Pfade) |
| Radius | 10 px Controls, 12 px Buttons, 16 px Karten, 999 px Chips |

Farben der Cut-Gründe, überall identisch (Timeline, Transkript, Filter, Export):

| Grund | Farbe |
|---|---|
| Füllwort | `#F5A524` |
| Retake | `#F31260` |
| Pause | `#7EE7FC` |
| Abschweifung | `#C4B5FD` |
| Event | `#17C964` |
| Highlight | `#FFD60A` |

Offene Cuts (`maybe`) sind halbtransparent mit gestricheltem Rand.
