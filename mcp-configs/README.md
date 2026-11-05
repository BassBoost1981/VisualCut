# MCP-Registrierung für VisualCut

Alle Agenten starten denselben Befehl: `visualcut-mcp` (stdio). Ein Test (`tests/test_mcp_configs.py`) prüft, dass die Snippets hier und `.mcp.json` im Repo-Root nicht auseinanderlaufen.

## Voraussetzung: `visualcut-mcp` auf dem PATH

```
uv tool install --editable . --with-extra speech    # global, auch außerhalb des Repos
```

Alternativ reicht `uv sync` plus das aktivierte `.venv` (`.venv\Scripts` bzw. `.venv/bin` auf dem PATH). Wer den Befehl nicht global haben will, ersetzt in jedem Snippet `visualcut-mcp` durch `uv` mit den Argumenten `["run", "--project", "<Pfad zum Repo>", "visualcut-mcp"]`.

Stufe 3 (Claude) braucht `ANTHROPIC_API_KEY` in der Umgebung des Agenten. Ohne Key läuft alles, nur ohne LLM-Cuts. Optional `VISUALCUT_CACHE` für einen anderen Cache-Ordner als `.visualcut` im Arbeitsverzeichnis.

## Claude Code

`.mcp.json` im Repo-Root wird automatisch gelesen. Außerhalb des Repos:

```
claude mcp add visualcut -- visualcut-mcp
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
