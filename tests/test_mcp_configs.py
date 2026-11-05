"""Alle MCP-Configs starten denselben Befehl; die Skill-Kopie für Codex ist identisch."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ["uv", "run", "visualcut-mcp"]


def test_all_configs_start_visualcut_mcp():
    claude = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["visualcut"]
    codex = tomllib.loads((ROOT / "mcp-configs" / "codex.toml").read_text(encoding="utf-8"))["mcp_servers"]["visualcut"]
    opencode = json.loads((ROOT / "mcp-configs" / "opencode.json").read_text(encoding="utf-8"))["mcp"]["visualcut"]
    commands = {
        "claude": [claude["command"], *claude.get("args", [])],
        "codex": [codex["command"], *codex.get("args", [])],
        "opencode": list(opencode["command"]),
    }
    assert all(cmd == EXPECTED for cmd in commands.values()), commands
    assert opencode["type"] == "local"


def test_entry_point_exists_and_runs_stdio():
    import tomllib as t

    scripts = t.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts["visualcut-mcp"] == "visualcut.mcp_server:main"


def test_codex_skill_is_a_copy():
    a = (ROOT / "skills" / "visualcut" / "SKILL.md").read_text(encoding="utf-8")
    b = (ROOT / ".codex" / "skills" / "visualcut" / "SKILL.md").read_text(encoding="utf-8")
    assert a == b
    assert a.startswith("---\nname: visualcut\ndescription:")
