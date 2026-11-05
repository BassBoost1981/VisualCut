"""Stufe 3 ohne API: Einreichung durch den steuernden Agenten (CLI, Pipeline, MCP)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp import Client
from typer.testing import CliRunner

from visualcut import pipeline
from visualcut.cache import ProjectCache
from visualcut.cli import app as cli_app
from visualcut.mcp_server import server
from visualcut.schema import CutSource, LLMCut, MediaInfo, SemanticResult, SemanticSubmission, Stage

runner = CliRunner()


def _video(analyzed: ProjectCache) -> Path:
    return Path(analyzed.load(Stage.ingest, MediaInfo).path)


def _reset(analyzed: ProjectCache) -> None:
    analyzed.stage_file(Stage.semantic).unlink(missing_ok=True)


def test_submit_adds_llm_cuts_and_refuses_invalid_ids(analyzed: ProjectCache):
    _reset(analyzed)
    video, root = _video(analyzed), analyzed.dir.parent
    sub = SemanticSubmission(source="agent:test", cuts=[
        LLMCut(start_word=0, end_word=3, reason="tangent", confidence=0.8, note="Begrüßung"),
        LLMCut(start_word=5000, end_word=5001, reason="filler", confidence=0.9, note="ungültig"),
        LLMCut(start_word=10, end_word=8, reason="filler", confidence=0.9, note="vertauscht"),
    ])
    info = pipeline.submit_semantic(video, sub, cache_root=root)
    assert info["llm_cuts"] == 1 and info["rejected"] == 2 and info["llm_model"] == "agent:test"
    _, analysis = pipeline.require_analysis(video, root)
    llm = [c for c in analysis.cuts if c.source == CutSource.llm]
    # das angrenzende Füllwort (Wort 4) wird in der Fusion mit dem LLM-Cut vereinigt
    assert len(llm) == 1 and llm[0].start_word == 0 and llm[0].end_word >= 3 and llm[0].start is not None
    _reset(analyzed)


def test_resubmit_replaces_and_append_merges(analyzed: ProjectCache):
    _reset(analyzed)
    video, root = _video(analyzed), analyzed.dir.parent
    first = SemanticSubmission(cuts=[LLMCut(start_word=0, end_word=1, reason="tangent", confidence=0.7, note="a")])
    second = SemanticSubmission(cuts=[LLMCut(start_word=12, end_word=13, reason="redundant", confidence=0.7, note="b")])
    pipeline.submit_semantic(video, first, cache_root=root)
    assert pipeline.submit_semantic(video, second, cache_root=root)["llm_cuts"] == 1  # ersetzt
    assert pipeline.submit_semantic(video, first, append=True, cache_root=root)["llm_cuts"] == 2  # vereinigt
    sem = analyzed.load(Stage.semantic, SemanticResult)
    assert sorted((c.start_word, c.end_word) for c in sem.cuts) == [(0, 1), (12, 13)]
    _reset(analyzed)


def test_cli_transcript_and_semantic_from_file(analyzed: ProjectCache, tmp_path: Path):
    _reset(analyzed)
    video, root = _video(analyzed), analyzed.dir.parent
    r = runner.invoke(cli_app, ["transcript", str(video), "--json", "--from-word", "2", "--to-word", "4", "--cache-dir", str(root)])
    assert r.exit_code == 0, r.output
    t = json.loads(r.stdout)
    assert t["first_word"] == 2 and t["last_word"] == 4 and t["lines"].splitlines()[0].startswith("2 ")
    f = tmp_path / "sub.json"
    f.write_text(json.dumps({"cuts": [{"start_word": 2, "end_word": 4, "reason": "tangent", "confidence": 0.8, "note": "x"}]}), encoding="utf-8")
    r = runner.invoke(cli_app, ["semantic", str(video), "--from", str(f), "--source", "agent:cli", "--json", "--cache-dir", str(root)])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["llm_cuts"] == 1
    r = runner.invoke(cli_app, ["semantic", "--instructions"])
    assert r.exit_code == 0 and "Wort-IDs" in r.stdout
    _reset(analyzed)


def test_mcp_transcript_and_submit(analyzed: ProjectCache, monkeypatch):
    _reset(analyzed)
    video = _video(analyzed)
    monkeypatch.setenv("VISUALCUT_CACHE", str(analyzed.dir.parent))

    async def go():
        async with Client(server) as c:
            names = sorted(t.name for t in (await c.list_tools()).tools)
            t = await c.call_tool("get_transcript", {"path": str(video), "start_word": 0, "max_words": 5})
            s = await c.call_tool("submit_semantic", {
                "path": str(video), "source": "agent:mcp",
                "cuts": [{"start_word": 1, "end_word": 2, "reason": "tangent", "confidence": 0.9, "note": "n"}],
                "chapters": [{"title": "Alles", "start_word": 0, "end_word": 3}],
            })
            return names, t, s

    names, t, s = asyncio.run(go())
    assert {"get_transcript", "submit_semantic", "semantic_instructions"} <= set(names)
    assert not t.is_error and t.structured_content["last_word"] == 4 and t.structured_content["next_word"] == 5
    assert not s.is_error, s.content[0].text
    assert s.structured_content["llm_cuts"] == 1 and s.structured_content["chapters"] == 1
    _reset(analyzed)
