# MCP-Registrierung für VisualCut

Alle Agenten starten denselben Befehl: `uv run visualcut-mcp` (stdio) mit dem Repo als Arbeitsverzeichnis. So läuft der Server im Projekt-venv inklusive Whisper. Ein Test (`tests/test_mcp_configs.py`) prüft, dass die Snippets hier und `.mcp.json` im Repo-Root nicht auseinanderlaufen.

## Voraussetzung

```
uv sync --extra speech --extra dev
```

Wer den Server außerhalb des Repos braucht, ersetzt in jedem Snippet die Argumente durch `["run", "--project", "<Pfad zum Repo>", "visualcut-mcp"]`. Eine globale Installation (`uv tool install --editable .`) liefert den Befehl `visualcut-mcp` ohne Whisper; sie reicht für Cuts, Entscheidungen und Export auf bereits analysierten Projekten.

Stufe 3 übernimmt der Agent selbst (`semantic_instructions`, `get_transcript`, `submit_semantic`). Alternativ läuft sie über die Claude API, wenn `ANTHROPIC_API_KEY` in der Umgebung des Agenten steht. Optional `VISUALCUT_CACHE` für einen anderen Cache-Ordner als `.visualcut` im Arbeitsverzeichnis.

## Claude Code

`.mcp.json` im Repo-Root wird automatisch gelesen. Außerhalb des Repos:

```
claude mcp add visualcut -- uv run --project <Pfad zum Repo> visualcut-mcp
```

## Codex

Abschnitt aus `codex.toml` in `~/.codex/config.toml` übernehmen. Die Skill-Kopie liegt unter `.codex/skills/visualcut/SKILL.md`.

## OpenCode

Abschnitt `mcp` aus `opencode.json` in die Projekt- oder Benutzerkonfiguration (`opencode.json` bzw. `~/.config/opencode/opencode.json`) übernehmen. OpenCode liest außerdem `AGENTS.md` und `skills/visualcut/SKILL.md`.

## T3 Code

Nutzt Claude Code oder Codex als Backend und erbt deren MCP-Konfiguration. Keine eigene Datei nötig, solange T3 keine eigene Config liest (bei neuen T3-Versionen prüfen).

## Tools

| Tool | Macht |
|---|---|
| `analyze(path, stage?, force?, language?, whisper_model?, llm?, model?)` | Pipeline laufen lassen, Kennzahlen plus Pfad zu `analysis.json` |
| `get_cuts(path, min_confidence?, reasons?, status?)` | Gefilterte Cut-Liste mit Begründungen |
| `decide(path, cut_id, status, note?)` | Cut annehmen, verwerfen, öffnen (`decisions.json`) |
| `export(path, format?, out?, open_as_cut?)` | FCPXML, EDL oder OTIO schreiben, gibt Pfad zurück |
| `get_transcript_path(path)` | Pfad zu `speech.json` plus Kapitel aus Stufe 3 |
| `schema()` | JSON-Schema aller Ausgaben |
