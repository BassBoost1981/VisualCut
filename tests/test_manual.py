"""Manuelle Cuts per Transkript-Markierung: manual.json, Fusion, CLI, API und MCP."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from typer.testing import CliRunner

from conftest import fake_words, make_cut
from visualcut import manual as manual_mod
from visualcut import pipeline
from visualcut.cache import ProjectCache
from visualcut.cli import app as cli_app
from visualcut.fusion import fuse
from visualcut.mcp_server import server
from visualcut.schema import Cut, CutReason, CutSource, CutStatus, Event, EventEffect, EventStatus, MediaInfo, Stage

runner = CliRunner()


def _video(analyzed: ProjectCache) -> Path:
    return Path(analyzed.load(Stage.ingest, MediaInfo).path)


@pytest.fixture
def clean(analyzed: ProjectCache):
    """manual.json vor und nach jedem Test entfernen und die Fusion zurückrechnen (Session-Cache wird geteilt)."""
    analyzed.path(manual_mod.FILENAME).unlink(missing_ok=True)
    yield analyzed
    analyzed.path(manual_mod.FILENAME).unlink(missing_ok=True)
    pipeline._refuse(analyzed, None)


def _manual(id_: str, a: int, b: int) -> Cut:
    return Cut(id=id_, start_word=a, end_word=b, reason=CutReason.redundant, confidence=1.0,
               source=CutSource.manual, status=CutStatus.accepted)


def test_manual_cut_snaps_like_others_and_never_cuts_into_kept_words():
    words = fake_words()
    cuts = fuse([_manual("manual-6-8", 6, 8)], words, [], [], 25.0, 20.0)
    assert len(cuts) == 1
    c = cuts[0]
    assert c.source == CutSource.manual and c.status == CutStatus.accepted and c.start_frame is not None
    kept = [w for w in words if not 6 <= w.id <= 8]
    assert not any(w.start < t < w.end for w in kept for t in (c.start, c.end))


def test_manual_cut_leads_when_merged_with_stronger_rule_cut():
    words = fake_words()
    cuts = fuse([make_cut("retake-5", 5, 7, CutReason.retake, 0.95), _manual("manual-6-9", 6, 9)],
                words, [], [], 25.0, 20.0)
    assert len(cuts) == 1
    assert cuts[0].id == "manual-6-9" and cuts[0].source == CutSource.manual and cuts[0].status == CutStatus.accepted
    assert cuts[0].start_word == 5 and cuts[0].end_word == 9


def test_rule_8_does_not_drop_manual_cuts():
    words = fake_words()
    w = {x.id: x for x in words}
    ev = Event(id="ev-dance", type="dancing", start=w[5].start - 0.5, end=w[10].end + 0.5, confidence=0.9,
               status=EventStatus.confirmed, effect=EventEffect.highlight)
    rule = fuse([make_cut("filler-7", 7, 7)], words, [], [], 25.0, 20.0, events=[ev])
    manual = fuse([_manual("manual-7-7", 7, 7)], words, [], [], 25.0, 20.0, events=[ev])
    assert rule == [] and len(manual) == 1


def test_add_validates_word_ids(clean: ProjectCache):
    words = fake_words()
    with pytest.raises(ValueError):
        manual_mod.add(clean, words, 0, 9999)
    with pytest.raises(ValueError):
        manual_mod.add(clean, words, 5, 3)
    with pytest.raises(ValueError):
        manual_mod.add(clean, words, 3, 5, CutReason.long_pause)
    assert manual_mod.load(clean).cuts == []


def test_mark_persists_refuses_and_unmark_removes(clean: ProjectCache):
    cut, analysis = pipeline.mark(clean, 12, 14, note="unnötig")
    assert cut.id == "manual-12-14" and clean.path("manual.json").exists()
    fused = [c for c in analysis.cuts if c.source == CutSource.manual]
    assert fused and fused[0].status == CutStatus.accepted and fused[0].start is not None
    # analysis.json und ein frischer Ladevorgang sehen den Cut ebenfalls
    on_disk = json.loads(clean.path("analysis.json").read_text(encoding="utf-8"))
    assert any(c["source"] == "manual" for c in on_disk["cuts"])
    assert any(c.id == cut.id for c in pipeline.load_analysis(clean).cuts)
    # dieselbe Spanne noch einmal ersetzt den Eintrag, statt ihn zu verdoppeln
    pipeline.mark(clean, 12, 14, CutReason.tangent)
    assert [c.reason for c in manual_mod.load(clean).cuts] == [CutReason.tangent]
    _, after = pipeline.unmark(clean, fused[0].id)
    assert manual_mod.load(clean).cuts == [] and not any(c.source == CutSource.manual for c in after.cuts)
    with pytest.raises(ValueError):
        pipeline.unmark(clean, "manual-1-2")


def test_cli_mark_unmark_and_cuts_lists_manual(clean: ProjectCache):
    video, root = str(_video(clean)), str(clean.dir.parent)
    r = runner.invoke(cli_app, ["mark", video, "12", "14", "--reason", "tangent", "--json", "--cache-dir", root])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["cut"]["id"] == "manual-12-14" and data["fused"]
    r = runner.invoke(cli_app, ["cuts", video, "--json", "--cache-dir", root])
    assert any(c["source"] == "manual" and c["status"] == "accepted" for c in json.loads(r.stdout)["cuts"])
    r = runner.invoke(cli_app, ["mark", video, "0", "9999", "--json", "--cache-dir", root])
    assert r.exit_code == 2
    r = runner.invoke(cli_app, ["unmark", video, "manual-12-14", "--json", "--cache-dir", root])
    assert r.exit_code == 0 and json.loads(r.stdout)["removed"] == "manual-12-14"


def test_api_manual_roundtrip_and_mcp_reads_it(clean: ProjectCache, monkeypatch):
    monkeypatch.setenv("VISUALCUT_CACHE", str(clean.dir.parent))
    from visualcut.api.app import app

    client = TestClient(app)
    base = f"/projects/{clean.hash}"
    r = client.post(f"{base}/manual", json={"start_word": 12, "end_word": 14})
    assert r.status_code == 200 and r.json()["reason"] == "redundant"
    assert client.post(f"{base}/manual", json={"start_word": 14, "end_word": 12}).status_code == 422
    assert [c["id"] for c in client.get(f"{base}/manual").json()["cuts"]] == ["manual-12-14"]
    assert any(c["source"] == "manual" for c in client.get(f"{base}/cuts").json()["cuts"])

    async def mcp_cuts() -> list[dict]:
        async with Client(server) as c:
            res = await c.call_tool("get_cuts", {"path": str(_video(clean))})
            assert not res.is_error, res.content[0].text
            return res.structured_content["cuts"]

    assert any(c["source"] == "manual" for c in asyncio.run(mcp_cuts()))
    assert client.delete(f"{base}/manual/manual-12-14").json()["cuts"] == []
    assert client.delete(f"{base}/manual/manual-12-14").status_code == 404
