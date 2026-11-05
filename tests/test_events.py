"""Stufe 1b: Fusion der Ebenen, Regel 8 im Snapping, Budget von Ebene C, Urteile des Agenten, Export,
Negativtest mit echten Modellen (nur mit Extra `events`)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from visualcut import export as export_mod
from visualcut.cache import ProjectCache
from visualcut.events import apply_judgments, catalog, fuse as fuse_mod, pose, vision_llm
from visualcut.events.action import ClipScore, plan_clips
from visualcut.events.words import events_on_words, format_events
from visualcut.fusion import align_highlights, fuse
from visualcut.schema import (
    Cut, CutReason, Event, EventCatalog, EventDefinition, EventEffect, EventJudgment, EventJudgments, EventsResult,
    EventStatus, EventWindow, Highlight, LLMEventJudgment, MediaInfo, Stage, Word,
)
from visualcut.semantic import block_content

CAT = EventCatalog(events=[
    EventDefinition(type="dancing", label="Tanzen", prompt="person dancing", kinetics=["danc"], effect="highlight", motion=True),
    EventDefinition(type="laughing", label="Lacht", prompt="person laughing", audio_prompt="laughter", effect="highlight"),
    EventDefinition(type="applause", label="Applaus", audio_prompt="applause", effect="highlight"),
    EventDefinition(type="drinking", label="Trinkt", prompt="person drinking", effect="cut"),
    EventDefinition(type="talking", label="Spricht", prompt="person talking", background=True),
])


def det(type_: str, a: float, b: float, conf: float, src: str) -> Event:
    return Event(id=f"{src}-{type_}-{a}", type=type_, start=a, end=b, confidence=conf, sources=[src])


def ev(type_: str, a: float, b: float, status=EventStatus.confirmed, effect=EventEffect.highlight) -> Event:
    return Event(id=f"ev-{type_}-{a}", type=type_, label=type_, start=a, end=b, confidence=0.8, sources=["pose", "xclip"],
                 status=status, effect=effect)


# ---------------------------------------------------------------- Fusion der Ebenen (Regeln 1 bis 4)


def test_two_sources_confirm_with_weighted_confidence():
    r = EventsResult(detections=[det("dancing", 10, 20, 0.6, "pose"), det("dancing", 12, 14, 0.9, "xclip"),
                                 det("dancing", 15, 17, 0.7, "xclip")])
    [e] = fuse_mod.fuse_events(r, CAT)
    assert e.status == EventStatus.confirmed and e.sources == ["pose", "xclip"]
    assert (e.start, e.end) == (10, 20) and e.label == "Tanzen" and e.effect == EventEffect.highlight
    # Ebene A zählt halb: (0.5 * 0.6 + 1.0 * 0.8) / 1.5
    assert e.confidence == pytest.approx((0.5 * 0.6 + 1.0 * 0.8) / 1.5, abs=1e-3)


def test_single_source_stays_candidate_and_background_is_ignored():
    r = EventsResult(detections=[det("laughing", 3, 5, 0.9, "xclip"), det("talking", 0, 30, 0.9, "xclip"),
                                 det("unbekannt", 0, 5, 0.9, "xclip")])
    [e] = fuse_mod.fuse_events(r, CAT)
    assert e.type == "laughing" and e.status == EventStatus.candidate


def test_level_c_alone_confirms_and_counts_double():
    r = EventsResult(
        detections=[det("laughing", 3, 5, 0.4, "xclip")],
        windows=[EventWindow(id="w-1", start=3, end=5, candidates=["laughing"], judged_by="vision")],
        judgments=[EventJudgment(window_id="w-1", type="laughing", confidence=0.9, description="lacht laut")],
    )
    [e] = fuse_mod.fuse_events(r, CAT)
    assert e.status == EventStatus.confirmed and e.description == "lacht laut"
    assert e.confidence == pytest.approx((1.0 * 0.4 + 2.0 * 0.9) / 3.0, abs=1e-3)


def test_level_c_none_vetoes_candidates():
    r = EventsResult(
        detections=[det("laughing", 3, 5, 0.5, "xclip"), det("laughing", 40, 42, 0.5, "xclip")],
        windows=[EventWindow(id="w-1", start=3, end=5, candidates=["laughing"], judged_by="agent:test")],
        judgments=[EventJudgment(window_id="w-1", type="none", confidence=0.8)],
    )
    assert [e.start for e in fuse_mod.fuse_events(r, CAT)] == [40]


def test_rule3_bounds_from_pose_energy():
    fps = 5.0
    lower = np.zeros(200)
    lower[56:150] = 0.3  # Bewegung ab 11,2 s bis 30 s
    r = EventsResult(detections=[det("dancing", 10.0, 30.0, 0.6, "pose"), det("dancing", 12, 14, 0.8, "xclip")],
                     motion=[0.5] * 200, motion_lower=list(lower), motion_fps=fps)
    [e] = fuse_mod.fuse_events(r, CAT)
    assert abs(e.start - 11.2) <= 0.5 and abs(e.end - 30.0) <= 0.5


def test_rule4_short_events_dropped_except_audio():
    r = EventsResult(detections=[det("laughing", 3, 3.6, 0.9, "xclip"), det("laughing", 3.1, 3.5, 0.9, "pose"),
                                 det("applause", 8, 8.5, 0.9, "clap")])
    assert [e.type for e in fuse_mod.fuse_events(r, CAT)] == ["applause"]


# ---------------------------------------------------------------- Ebene A: Pose-Signale (konstruiert)


def _person(hip_y: float, knee_dx: float, visible_lower: bool) -> tuple[np.ndarray, np.ndarray]:
    kp = np.zeros((1, 17, 2), np.float32)
    sc = np.full((1, 17), 0.9, np.float32)
    kp[0, 0] = (320, 60)
    kp[0, 5], kp[0, 6] = (290, 120), (350, 120)
    kp[0, 7], kp[0, 8], kp[0, 9], kp[0, 10] = (270, 170), (370, 170), (260, 210), (380, 210)
    kp[0, 11], kp[0, 12] = (300, hip_y), (340, hip_y)
    kp[0, 13], kp[0, 14] = (300 + knee_dx, hip_y + 60), (340 - knee_dx, hip_y + 60)
    kp[0, 15], kp[0, 16] = (300 + 2 * knee_dx, hip_y + 120), (340 - 2 * knee_dx, hip_y + 120)
    if not visible_lower:
        sc[0, 11:] = 0.05
    return kp, sc


def test_pose_dancing_needs_moving_lower_body():
    t = np.arange(100) / 5.0
    dancing = [_person(230 + 8 * np.sin(2 * np.pi * x), 25 * np.sin(2 * np.pi * x), True) for x in t]
    # Talking Head: Hände und Kopf bewegen sich, Unterkörper unsichtbar
    talking = []
    for x in t:
        kp, sc = _person(230, 0, False)
        kp[0, 9:11, 1] += 40 * np.sin(4 * np.pi * x)
        talking.append((kp, sc))
    d = pose.detections(pose.track_signals(dancing, 360))
    assert [e.type for e in d] == ["dancing"] and d[0].end - d[0].start >= 15
    assert [e for e in pose.detections(pose.track_signals(talking, 360)) if e.type == "dancing"] == []


def test_pose_empty_frame():
    samples = [_person(230, 0, True)] * 20 + [(np.zeros((0, 17, 2)), np.zeros((0, 17)))] * 20
    d = pose.detections(pose.track_signals(samples, 360))
    assert [(e.type, e.start) for e in d if e.type == "empty_frame"] == [("empty_frame", 4.0)]


def test_plan_clips_covers_windows_and_grid():
    clips = plan_clips(60.0, [(10.0, 16.0)])
    starts = [s for s, _ in clips]
    assert {10.0, 12.0, 14.0} <= set(starts) and 4.0 in starts and 54.0 in starts
    assert all(e - s == pytest.approx(2.0) for s, e in clips)


# ---------------------------------------------------------------- Ebene C: Fenster und Budget


class FakeVision:
    def __init__(self, answer: LLMEventJudgment):
        self.answer, self.calls = answer, 0
        self.messages = self

    def parse(self, **kw):
        self.calls += 1
        assert kw["output_format"] is LLMEventJudgment
        assert sum(1 for c in kw["messages"][0]["content"] if c["type"] == "image") == 1
        answer = self.answer

        class R:
            stop_reason = "end_turn"
            parsed_output = answer
        return R()


def _windows(tmp_path: Path, n: int) -> list[EventWindow]:
    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")
    return [EventWindow(id=f"w-{k}", start=k * 3.0, end=k * 3.0 + 2, candidates=["dancing"], frames=[str(img)])
            for k in range(n)]


def test_vision_budget_is_a_hard_limit(tmp_path: Path):
    client = FakeVision(LLMEventJudgment(type="dancing", confidence=0.8, description="tanzt"))
    windows = _windows(tmp_path, 50)
    judged, calls, status = vision_llm.judge(windows, CAT, 40, client=client)
    assert client.calls == 40 == calls and len(judged) == 40 and "10 Fenster offen" in status
    assert sum(w.judged_by == "vision" for w in windows) == 40
    client2 = FakeVision(LLMEventJudgment(type="dancing", confidence=0.8, description=""))
    assert vision_llm.judge(_windows(tmp_path, 5), CAT, 0, client=client2)[1] == 0 and client2.calls == 0


def test_vision_without_key_is_skipped(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    judged, calls, status = vision_llm.judge(_windows(tmp_path, 3), CAT, 40)
    assert (judged, calls) == ([], 0) and "3 Fenster offen" in status


def test_vision_invalid_answers_are_rejected(tmp_path: Path):
    for bad in (LLMEventJudgment(type="fliegen", confidence=0.9, description=""),
                LLMEventJudgment(type="dancing", confidence=1.4, description="")):
        judged, calls, _ = vision_llm.judge(_windows(tmp_path, 1), CAT, 40, client=FakeVision(bad))
        assert calls == 1 and judged == []


def test_uncertain_and_contradicting_clips_become_windows():
    scores = [ClipScore(0, 2, {"dancing": 0.55, "talking": 0.45}), ClipScore(2, 4, {"dancing": 0.6, "talking": 0.4}),
              ClipScore(10, 12, {"dancing": 0.9, "talking": 0.1}), ClipScore(20, 22, {"dancing": 0.2, "talking": 0.8})]
    lower = np.zeros(150)
    lower[100:110] = 0.3  # Unterkörper bewegt sich bei 20 bis 22 s, X-CLIP sagt "talking"
    ws = vision_llm.uncertain_windows(scores, CAT, lower, 5.0, pose.LOWER_THRESHOLD)
    assert [(w.start, w.end) for w in ws] == [(0, 4), (20, 22)]
    assert "Widerspruch" in ws[1].reason


def test_agent_judgments_count_as_level_c(tmp_path: Path):
    cache = ProjectCache("abc", tmp_path)
    catalog.save(CAT, catalog.project_path(cache))
    cache.save(Stage.events, EventsResult(
        detections=[det("dancing", 10, 12, 0.5, "xclip")],
        windows=[EventWindow(id="w-1", start=10, end=12, candidates=["dancing"])],
    ))
    sub = EventJudgments(source="claude-code", judgments=[
        EventJudgment(window_id="w-1", type="dancing", confidence=0.9, description="tanzt"),
        EventJudgment(window_id="w-9", type="dancing", confidence=0.9),
        EventJudgment(window_id="w-1", type="fliegen", confidence=0.9),
    ])
    result, rejected = apply_judgments(cache, sub)
    assert rejected == 2 and result.windows[0].judged_by == "agent:claude-code"
    [e] = result.events
    assert e.status == EventStatus.confirmed and "agent:claude-code" in e.sources


# ---------------------------------------------------------------- Regel 8 im Snapping


def _words() -> list[Word]:
    return [Word(id=i, text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(40)]


def test_rule8_no_cut_inside_confirmed_event():
    words = _words()
    cuts = [Cut(id="inside", start_word=11, end_word=12, reason=CutReason.filler, confidence=0.9),
            Cut(id="into", start_word=4, end_word=8, reason=CutReason.tangent, confidence=0.9)]
    dance = ev("dancing", 3.2, 8.0)  # beginnt in Wort 6 (3,0 bis 3,4)
    out = fuse(cuts, words, [], [], 25.0, 20.0, events=[dance])
    assert [c.id for c in out] == ["into"]
    c = out[0]
    assert c.end <= dance.start and c.end == pytest.approx(3.0, abs=0.05)  # vor Wort 6, nicht in ihm
    assert not any(w.start < c.end < w.end for w in words) and "Event-Grenze" in c.note
    assert c.end_word == 5
    # ohne Event bleiben beide Cuts
    assert len(fuse(cuts, words, [], [], 25.0, 20.0)) == 2


def test_rule8_ignores_candidates_and_cut_effect():
    words = _words()
    cuts = [Cut(id="inside", start_word=11, end_word=12, reason=CutReason.filler, confidence=0.9)]
    for e in (ev("dancing", 3.2, 8.0, status=EventStatus.candidate), ev("drinking", 3.2, 8.0, effect=EventEffect.cut)):
        assert [c.id for c in fuse(cuts, words, [], [], 25.0, 20.0, events=[e])] == ["inside"]


def test_highlight_aligned_to_event_with_lead():
    words = _words()
    h = Highlight(start_word=12, end_word=20, score=0.9, hook="tanzt")  # 6,0 bis 10,4 s
    dance = ev("dancing", 5.0, 11.0)
    [a] = align_highlights([h], words, [dance], 25.0, 20.0)
    assert 4.5 - 1 / 25 < a.start <= 4.5 and a.end == pytest.approx(11.0) and a.event_ids == [dance.id]  # Frame nach außen
    [b] = align_highlights([h], words, [], 25.0, 20.0)
    assert b.start == pytest.approx(6.0) and b.end == pytest.approx(10.4) and b.event_ids == []


# ---------------------------------------------------------------- Stufe 3: Events auf Wort-IDs


def test_events_on_words_spoken_and_silent():
    words = [Word(id=0, text="a", start=0, end=1), Word(id=1, text="b", start=1, end=2),
             Word(id=2, text="c", start=10, end=11)]
    spoken, silent = events_on_words([ev("laughing", 0.5, 1.5), ev("dancing", 3, 9)], words)
    assert (spoken["start_word"], spoken["end_word"], spoken["spoken"]) == (0, 1, True)
    assert (silent["start_word"], silent["end_word"], silent["spoken"]) == (1, 2, False)
    text = format_events([silent])
    assert "ohne Sprache, zwischen Wort 1 und 2" in text and "confirmed" in text
    content = block_content(words, words, [ev("dancing", 3, 9)])
    assert content.startswith("0 a\n1 b\n2 c\n\n## Ereignisse\n")


# ---------------------------------------------------------------- Katalog und Export


def test_repo_catalog_is_valid_and_project_overrides(tmp_path: Path):
    cat = catalog.load()
    types = {d.type for d in cat.events}
    assert {"dancing", "laughing", "applause", "music", "nothing"} <= types and cat.vision_budget == 40
    assert all(d.label for d in cat.events) and catalog.parse(catalog.dump(cat)) == cat
    cache = ProjectCache("p", tmp_path)
    catalog.save(CAT, catalog.project_path(cache))
    assert catalog.load(cache) == CAT
    with pytest.raises(ValueError):
        catalog.parse("events:\n  - {type: a, label: A}\n  - {type: a, label: B}\n")


def test_confirmed_events_exported_as_green_markers(tmp_path: Path):
    media = MediaInfo(path=str(tmp_path / "v.mp4"), content_hash="x", size_bytes=1, duration=20.0, fps=25.0,
                      width=640, height=360, has_audio=True)
    events = [ev("dancing", 5.0, 9.0), ev("laughing", 12.0, 13.0, status=EventStatus.candidate)]
    tl = export_mod.build_timeline(media, [], events=events)
    assert export_mod.count_event_markers(tl) == 1
    edl = export_mod.write(tl, tmp_path / "m.edl", "markers-edl").read_text(encoding="utf-8")
    assert " |C:ResolveColorGreen |M:Event dancing 0.80 |D:100" in edl and "laughing" not in edl
    xml = export_mod.write(tl, tmp_path / "t.fcpxml", "fcpxml").read_text(encoding="utf-8")
    assert 'value="Event dancing 0.80"' in xml


# ---------------------------------------------------------------- echte Modelle (nur mit Extra `events`)

HAS_EXTRA = all(importlib.util.find_spec(m) for m in ("rtmlib", "transformers", "torch"))


@pytest.mark.models
@pytest.mark.skipif(not HAS_EXTRA, reason="Extra events nicht installiert (uv sync --extra events)")
def test_quiet_synthetic_video_has_no_dancing(synthetic_video: Path, tmp_path: Path):
    from visualcut.events import detect_events
    from visualcut.ingest import ingest
    from visualcut.technical import analyze_technical

    cache = ProjectCache.for_video(synthetic_video, tmp_path)
    media = ingest(synthetic_video, cache)
    tech = analyze_technical(media, cache)
    result = detect_events(media, tech, cache, vision=False)
    assert result is not None and cache.has(Stage.events)
    assert result.layers["pose"].startswith("ok") and result.layers["xclip"].startswith("ok")
    assert [e for e in result.events if e.type == "dancing"] == []
    assert [d for d in result.detections if d.type == "dancing" and "pose" in d.sources] == []


# ---------------------------------------------------------------- API


def test_api_catalog_roundtrip_keeps_header(analyzed: ProjectCache, tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from visualcut.api.app import create_app

    target = tmp_path / "events.yaml"
    target.write_text((Path(catalog.__file__).resolve().parents[3] / "events.yaml").read_text(encoding="utf-8"),
                      encoding="utf-8")
    monkeypatch.setenv("VISUALCUT_EVENTS", str(target))
    monkeypatch.setenv("VISUALCUT_CACHE", str(analyzed.dir.parent))
    client = TestClient(create_app())
    info = client.get("/events/catalog").json()
    assert info["path"] == str(target) and info["catalog"]["vision_budget"] == 40
    cat = info["catalog"]
    cat["vision_budget"] = 12
    cat["events"].append({"type": "drinking_coffee", "label": "Kaffee", "prompt": "person drinking coffee", "effect": "cut"})
    saved = client.put("/events/catalog", json=cat).json()["catalog"]
    assert saved["vision_budget"] == 12 and saved["events"][-1]["type"] == "drinking_coffee"
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# VisualCut Stufe 1b") and "#   effect" in text  # Feldbeschreibung bleibt
    bad = dict(cat, events=cat["events"] + [cat["events"][0]])
    assert client.put("/events/catalog", json=bad).status_code == 422  # doppelter Typ
    r = client.get(f"/projects/{analyzed.hash}/events", params={"pending": True}).json()
    assert r["count"] == 0 and r["windows"] == [] and r["instructions_path"].endswith("vision_event_v1.md")


def test_highlight_aligned_to_silent_event_after_last_word():
    """Event ohne Sprache hinter dem letzten Wort: Stufe 3 sieht es als "zwischen Wort 5 und 5" und meldet 5..5."""
    words = [Word(id=i, text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(6)]
    dance = ev("dancing", 11.4, 188.2)
    [a] = align_highlights([Highlight(start_word=5, end_word=5, score=0.9)], words, [dance], 60.0, 199.0)
    assert a.event_ids == [dance.id] and 10.9 - 1 / 60 < a.start <= 10.9 and a.end == pytest.approx(188.2, abs=1 / 60)


def test_only_highlight_events_anchor_highlights():
    words = [Word(id=i, text=f"w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(6)]
    events = [ev("dancing", 11.4, 188.2), ev("empty_frame", 189.2, 199.0, effect=EventEffect.cut),
              ev("music", 0.0, 190.0, effect=EventEffect.marker)]
    [a] = align_highlights([Highlight(start_word=5, end_word=5, score=0.9)], words, events, 60.0, 199.0)
    assert a.event_ids == ["ev-dancing-11.4"] and a.end == pytest.approx(188.2, abs=1 / 60)
