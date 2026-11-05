"""MCP-Tools gegen den vorhandenen Cache von talking2.mp4 (In-Memory-Client, kein Subprozess).

Der Cache wird in ein temporäres Verzeichnis kopiert (nur JSON), damit decide/export nichts am echten
Projekt ändern. Fehlt talking2.mp4 oder sein Cache, werden die Tests übersprungen.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp import Client

from visualcut.cache import content_hash
from visualcut.mcp_server import server
from visualcut.schema import Stage

VIDEO_NAME = "talking2.mp4"


def _find_video() -> Path | None:
    for d in [Path(__file__).resolve().parents[1], *Path(__file__).resolve().parents[1].parents]:
        v = d / VIDEO_NAME
        if v.is_file() and (d / ".visualcut" / content_hash(v) / "fusion.json").exists():
            return v
    return None


@pytest.fixture(scope="module")
def talking2(tmp_path_factory) -> tuple[Path, Path]:
    video = _find_video()
    if video is None:
        pytest.skip(f"{VIDEO_NAME} mit fertigem Cache nicht gefunden")
    h = content_hash(video)
    src = video.parent / ".visualcut" / h
    root = tmp_path_factory.mktemp("mcp-cache")
    (root / h).mkdir()
    for f in src.glob("*.json"):
        if f.name not in ("decisions.json", "semantic.json"):  # ohne Stufe 3: die Tests erwarten reine Regel-Cuts
            shutil.copy(f, root / h / f.name)
    return video, root


@pytest.fixture
def cache_env(talking2, monkeypatch):
    monkeypatch.setenv("VISUALCUT_CACHE", str(talking2[1]))
    return talking2


async def _call(name: str, **args):
    async with Client(server) as c:
        return await c.call_tool(name, args)


def test_tools_are_registered():
    import asyncio

    async def names():
        async with Client(server) as c:
            return sorted(t.name for t in (await c.list_tools()).tools)

    assert asyncio.run(names()) == ["analyze", "decide", "export", "get_cuts", "get_events", "get_transcript", "get_transcript_path",
                                    "judge_events", "schema", "semantic_instructions", "submit_semantic"]


def test_get_cuts_matches_cli(cache_env):
    import asyncio

    from typer.testing import CliRunner

    from visualcut.cli import app as cli_app

    video, root = cache_env
    r = asyncio.run(_call("get_cuts", path=str(video), reasons=["retake"]))
    assert not r.is_error, r.content[0].text
    data = r.structured_content
    assert data["count"] > 0 and all(c["reason"] == "retake" for c in data["cuts"])
    cli = CliRunner().invoke(cli_app, ["cuts", str(video), "--json", "--reason", "retake", "--cache-dir", str(root)])
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout) == data  # MCP liefert exakt die CLI-Daten


def test_analyze_from_cache_returns_summary_not_content(cache_env, monkeypatch):
    import asyncio

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    video, root = cache_env
    r = asyncio.run(_call("analyze", path=str(video), language="en"))
    assert not r.is_error, r.content[0].text
    s = r.structured_content
    assert Path(s["analysis_path"]).is_file() and s["words"] > 100 and s["cuts"] > 0
    assert "fusion" in s["stages_done"] and "semantic" not in s["stages_done"] and s["llm_model"] is None
    assert len(r.content[0].text) < 2000  # Zusammenfassung, nicht die Analyse


def test_decide_then_export_and_transcript_path(cache_env, tmp_path: Path):
    import asyncio

    video, root = cache_env
    cut_id = asyncio.run(_call("get_cuts", path=str(video))).structured_content["cuts"][0]["id"]
    r = asyncio.run(_call("decide", path=str(video), cut_id=cut_id, status="accepted", note="per MCP"))
    assert not r.is_error and r.structured_content["status"] == "accepted"
    accepted = asyncio.run(_call("get_cuts", path=str(video), status="accepted")).structured_content
    assert [c["id"] for c in accepted["cuts"]] == [cut_id]
    out = tmp_path / "mcp.fcpxml"
    r = asyncio.run(_call("export", path=str(video), format="fcpxml", out=str(out)))
    assert not r.is_error, r.content[0].text
    assert out.is_file() and r.structured_content["cuts_applied"] == 1
    t = asyncio.run(_call("get_transcript_path", path=str(video))).structured_content
    assert Path(t["transcript_path"]).name == f"{Stage.speech.value}.json" and t["words"] > 100 and t["language"] == "en"


def test_errors_are_messages_not_crashes(cache_env, tmp_path: Path):
    import asyncio

    video, _ = cache_env
    r = asyncio.run(_call("get_cuts", path=str(tmp_path / "fehlt.mp4")))
    assert r.is_error and "nicht gefunden" in r.content[0].text
    r = asyncio.run(_call("decide", path=str(video), cut_id="gibtsnicht", status="rejected"))
    assert r.is_error and "Unbekannte Cut-ID" in r.content[0].text
    r = asyncio.run(_call("export", path=str(video), format="avi"))
    assert r.is_error and "Format" in r.content[0].text


def test_schema_tool_matches_cli():
    import asyncio

    from visualcut.schema import json_schema

    r = asyncio.run(_call("schema"))
    assert not r.is_error and r.structured_content == json_schema()
