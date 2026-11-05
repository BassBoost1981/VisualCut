"""Stufe 3: Blockbildung, harte Validierung konstruierter LLM-Antworten, Zusammenführung, Pipeline ohne Key."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import make_cut
from typer.testing import CliRunner

from visualcut import semantic
from visualcut.cache import ProjectCache
from visualcut.cli import app as cli_app
from visualcut.pipeline import run_fusion
from visualcut.schema import (
    Chapter, Cut, CutReason, CutSource, Flag, FusionResult, LLMChapter, LLMCut, LLMFlag, LLMHighlight, LLMResponse,
    MediaInfo, ProgressEvent, SemanticResult, SpeechResult, Stage, TechnicalResult, Word,
)

runner = CliRunner()


def words(n: int) -> list[Word]:
    return [Word(id=i, text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(n)]


def llm_cut(a: int, b: int, reason: CutReason = CutReason.tangent, conf: float = 0.8, note: str = "x") -> LLMCut:
    return LLMCut(start_word=a, end_word=b, reason=reason, confidence=conf, note=note)


def llm_resp(cuts: list[LLMCut], chapters: list[LLMChapter] | None = None) -> LLMResponse:
    return LLMResponse(chapters=chapters or [], cuts=cuts, highlights=[], flags=[])


# ---------------------------------------------------------------- Blöcke


def test_blocks_overlap_and_cover_everything():
    w = words(4500)
    parts = semantic.blocks(w)
    assert [p[0].id for p in parts] == [0, 1800, 3600]
    assert all(len(p) <= semantic.BLOCK_WORDS for p in parts)
    assert parts[0][-1].id == 1999 and parts[1][0].id == 1800  # 200 Wörter Überlappung
    assert parts[-1][-1].id == 4499
    assert semantic.blocks([]) == []
    assert len(semantic.blocks(words(10))) == 1


def test_format_block_is_id_text_lines():
    assert semantic.format_block(words(2)) == "0 w0\n1 w1"


# ---------------------------------------------------------------- Validierung


def test_validate_drops_unknown_ids_swapped_bounds_and_bad_values():
    block = words(10)
    logs: list[ProgressEvent] = []
    resp = LLMResponse(
        chapters=[LLMChapter(title="ok", start_word=0, end_word=9), LLMChapter(title="raus", start_word=0, end_word=99)],
        cuts=[
            llm_cut(2, 4),                         # gültig
            llm_cut(5, 3),                         # vertauscht
            llm_cut(8, 12),                        # ID 12 existiert nicht
            llm_cut(100, 101),                     # beide unbekannt
            llm_cut(6, 6, conf=1.4),               # confidence außerhalb
            llm_cut(7, 7, CutReason.filler, 0.9),  # gültig
        ],
        highlights=[LLMHighlight(start_word=1, end_word=3, score=0.5, hook="h"),
                    LLMHighlight(start_word=3, end_word=1, score=0.5, hook="h"),
                    LLMHighlight(start_word=1, end_word=3, score=2.0, hook="h")],
        flags=[LLMFlag(word=4, type="unclear_audio"), LLMFlag(word=40, type="unclear_audio")],
    )
    res = semantic.validate(resp, block, logs.append)
    assert [(c.start_word, c.end_word) for c in res.cuts] == [(2, 4), (7, 7)]
    assert all(c.source == CutSource.llm for c in res.cuts)
    assert res.cuts[0].id == "llm-2-4" and res.cuts[1].reason == CutReason.filler
    assert [ch.title for ch in res.chapters] == ["ok"]
    assert len(res.highlights) == 1 and [f.word for f in res.flags] == [4]
    assert res.rejected == 8  # 1 Kapitel, 4 Cuts, 2 Highlights, 1 Flag
    assert len([e for e in logs if e.event == "log" and "verworfen" in e.message]) == 8


def test_validate_rejects_ids_outside_block_even_if_video_has_them():
    """Das Modell sieht nur seinen Block, IDs außerhalb sind Halluzinationen."""
    block = words(50)[20:30]
    res = semantic.validate(llm_resp([llm_cut(5, 8), llm_cut(22, 24)]), block)
    assert [c.start_word for c in res.cuts] == [22] and res.rejected == 1


# ---------------------------------------------------------------- Zusammenführung


def test_merge_with_rules_unions_overlap_and_keeps_rest():
    rules = [make_cut("filler-3", 3, 3, CutReason.filler, 0.9), make_cut("retake-10", 10, 15, CutReason.retake, 0.7)]
    llm = [
        Cut(id="llm-2-5", start_word=2, end_word=5, reason=CutReason.tangent, confidence=0.8, source=CutSource.llm, note="Abschweifung"),
        Cut(id="llm-14-20", start_word=14, end_word=20, reason=CutReason.redundant, confidence=0.95, source=CutSource.llm, note="doppelt"),
        Cut(id="llm-30-31", start_word=30, end_word=31, reason=CutReason.false_start, confidence=0.6, source=CutSource.llm, note="Neustart"),
    ]
    merged = semantic.merge_with_rules(llm, rules)
    assert [(c.start_word, c.end_word) for c in merged] == [(2, 5), (10, 20), (30, 31)]
    a, b, c = merged
    assert a.reason == CutReason.tangent and a.source == CutSource.llm and "filler-3" in a.note  # tangent schlägt filler
    assert b.reason == CutReason.retake and b.source == CutSource.rule and b.id == "retake-10"  # retake schlägt redundant
    assert b.confidence == 0.7 and "doppelt" in b.note
    assert c.id == "llm-30-31"


def test_combine_dedupes_block_overlap():
    cut = Cut(id="llm-1-2", start_word=1, end_word=2, reason=CutReason.filler, confidence=0.9, source=CutSource.llm)
    r1 = SemanticResult(cuts=[cut], chapters=[Chapter(title="A", start_word=0, end_word=5)], flags=[Flag(word=1, type="x")], rejected=1)
    r2 = SemanticResult(cuts=[cut], chapters=[Chapter(title="A again", start_word=3, end_word=8), Chapter(title="B", start_word=6, end_word=9)],
                        flags=[Flag(word=1, type="x")], rejected=2)
    res = semantic.combine([r1, r2])
    assert len(res.cuts) == 1 and len(res.flags) == 1 and res.blocks == 2 and res.rejected == 3
    assert [ch.title for ch in res.chapters] == ["A", "B"]


# ---------------------------------------------------------------- Stufe und Pipeline


class FakeClient:
    """Ersetzt anthropic.Anthropic: gibt pro Block eine vorbereitete Antwort zurück."""

    def __init__(self, responses: list[LLMResponse]):
        self.responses, self.calls = list(responses), []
        self.messages = self

    def parse(self, **kw):
        self.calls.append(kw)
        resp = self.responses.pop(0)

        class R:
            stop_reason = "end_turn"
            parsed_output = resp
        return R()


def test_analyze_semantic_with_fake_client_writes_cache(tmp_path: Path):
    cache = ProjectCache("abc", tmp_path)
    speech = SpeechResult(words=words(30), language="de")
    client = FakeClient([llm_resp(
        [llm_cut(3, 5, CutReason.retake, 0.9, "nochmal ab 6"), llm_cut(50, 60)],
        [LLMChapter(title="Intro", start_word=0, end_word=29)],
    )])
    events: list[ProgressEvent] = []
    res = semantic.analyze_semantic(speech, cache, events.append, client=client, model="test-model")
    assert res is not None and [c.id for c in res.cuts] == ["llm-3-5"] and res.rejected == 1
    assert res.model == "test-model" and res.prompt_version == "semantic_v2" and res.blocks == 1
    assert cache.has(Stage.semantic) and cache.load(Stage.semantic, SemanticResult).cuts[0].note == "nochmal ab 6"
    call = client.calls[0]
    assert call["model"] == "test-model" and call["output_format"] is LLMResponse
    assert call["messages"][0]["content"].startswith("0 w0\n1 w1")
    assert "Wort-IDs" in call["system"]
    assert events[0].event == "stage_start" and events[-1].event == "stage_done"
    # zweiter Lauf: Cache
    assert semantic.analyze_semantic(speech, cache, events.append, client=client).cuts[0].id == "llm-3-5"
    assert events[-1].event == "stage_skipped"


def test_analyze_semantic_skips_without_key_or_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(semantic.API_KEY_ENV, raising=False)
    cache = ProjectCache("abc", tmp_path)
    events: list[ProgressEvent] = []
    assert semantic.analyze_semantic(SpeechResult(words=words(5)), cache, events.append) is None
    assert [e.event for e in events] == ["stage_skipped"] and semantic.API_KEY_ENV in events[0].message
    assert not cache.has(Stage.semantic)
    monkeypatch.setenv(semantic.API_KEY_ENV, "sk-test")
    events.clear()
    assert semantic.analyze_semantic(SpeechResult(words=words(5)), cache, events.append, enabled=False) is None
    assert events[0].event == "stage_skipped" and "--no-llm" in events[0].message


def test_pipeline_without_key_skips_semantic_and_keeps_rule_cuts(analyzed: ProjectCache, monkeypatch):
    monkeypatch.delenv(semantic.API_KEY_ENV, raising=False)
    video = analyzed.load(Stage.ingest, MediaInfo).path
    r = runner.invoke(cli_app, ["analyze", video, "--json", "--cache-dir", str(analyzed.dir.parent)])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert "semantic" not in data["stages_done"] and "fusion" in data["stages_done"]
    assert data["semantic"] is None and data["cuts"] and all(c["source"] == "rule" for c in data["cuts"])
    assert '"event":"stage_skipped","stage":"semantic"' in r.stderr.replace(" ", "")
    r = runner.invoke(cli_app, ["analyze", video, "--json", "--stage", "semantic", "--cache-dir", str(analyzed.dir.parent)])
    assert r.exit_code == 0 and json.loads(r.stdout)["stages_done"] == ["ingest", "technical", "events", "speech"]


def test_fusion_recomputes_when_llm_cuts_arrive(analyzed: ProjectCache):
    media = analyzed.load(Stage.ingest, MediaInfo)
    tech, speech = analyzed.load(Stage.technical, TechnicalResult), analyzed.load(Stage.speech, SpeechResult)
    before = run_fusion(analyzed, media, tech, speech)  # Cache, llm_model None
    assert before.llm_model is None
    w = speech.words
    sem = SemanticResult(model="fake", cuts=[Cut(
        id=f"llm-{w[4].id}-{w[6].id}", start_word=w[4].id, end_word=w[6].id, reason=CutReason.tangent,
        confidence=0.85, source=CutSource.llm, note="Abschweifung",
    )])
    events: list[ProgressEvent] = []
    after = run_fusion(analyzed, media, tech, speech, sem, events.append)
    assert after.llm_model == "fake" and events[0].event == "log" and events[1].event == "stage_start"
    llm = [c for c in after.cuts if c.source == CutSource.llm]
    assert llm and llm[0].start is not None and llm[0].note.startswith("Abschweifung")
    assert len(after.cuts) >= len(before.cuts)
    # Ohne semantic wieder zurück auf die reine Regel-Fusion
    again = run_fusion(analyzed, media, tech, speech)
    assert again.llm_model is None and len(again.cuts) == len(before.cuts)
    analyzed.save(Stage.fusion, FusionResult(cuts=before.cuts, fps=media.fps))


# ---------------------------------------------------------------- Integration (echte API)


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get(semantic.API_KEY_ENV), reason="ANTHROPIC_API_KEY nicht gesetzt")
def test_real_api_returns_only_known_word_ids(tmp_path: Path):
    text = ("hallo und ähm herzlich willkommen heute zeige ich euch heute zeige ich euch wie das geht "
            "also zuerst öffnen wir das programm warte ist das mikro an okay dann laden wir das material").split()
    speech = SpeechResult(words=[Word(id=i, text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate(text)], language="de")
    res = semantic.analyze_semantic(speech, ProjectCache("real", tmp_path))
    assert res is not None and res.model == semantic.DEFAULT_MODEL
    ids = {w.id for w in speech.words}
    assert all(c.start_word in ids and c.end_word in ids and c.source == CutSource.llm for c in res.cuts)
    assert all(ch.start_word in ids and ch.end_word in ids for ch in res.chapters)
