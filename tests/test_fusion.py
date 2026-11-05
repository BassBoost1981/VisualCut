"""Stufe 4 mit konstruierten Wort- und Stillelisten."""

from __future__ import annotations

from conftest import make_cut

from visualcut.fusion import MIN_SEGMENT, fuse, snap_end, snap_start
from visualcut.schema import CutReason, SceneChange, SilenceInterval, Word

FPS = 25.0


def grid_words(n: int, step: float = 0.5, dur: float = 0.4, t0: float = 0.5) -> list[Word]:
    return [Word(id=i, text=f"w{i}", start=round(t0 + i * step, 3), end=round(t0 + i * step + dur, 3)) for i in range(n)]


def assert_no_boundary_in_kept_word(cuts, words):
    removed = set()
    for c in cuts:
        if c.reason != CutReason.long_pause or c.start_word == c.end_word:
            removed.update(range(c.start_word, c.end_word + 1))
    for c in cuts:
        for w in words:
            if w.id in removed:
                continue
            assert not (w.start < c.start < w.end), (c, w)
            assert not (w.start < c.end < w.end), (c, w)


def test_snap_into_silence_middle():
    sil = [SilenceInterval(start=1.0, end=1.4)]
    assert snap_start(1.6, sil) == 1.2   # Stille endet 200 ms vor start
    assert snap_start(1.9, sil) == 1.9   # 500 ms: zu weit
    assert snap_end(0.8, sil) == 1.2     # Stille beginnt 200 ms nach end
    assert snap_end(1.2, sil) == 1.2     # end liegt in der Stille


def test_no_cut_boundary_inside_kept_word_grid():
    words = grid_words(40)
    silences = [SilenceInterval(start=w.end, end=words[w.id + 1].start) for w in words[:-1]]  # 100 ms Lücken
    raw = [make_cut("f1", 3, 3), make_cut("r1", 10, 14, CutReason.retake), make_cut("f2", 20, 20, conf=0.5)]
    cuts = fuse(raw, words, silences, [], FPS, duration=25.0)
    assert len(cuts) == 3
    assert_no_boundary_in_kept_word(cuts, words)
    for c in cuts:
        assert c.start_frame == round(c.start * FPS) and c.end_frame == round(c.end * FPS)
        assert c.start < c.end
    assert [c.maybe for c in cuts] == [False, False, True]


def test_no_cut_boundary_without_silences():
    # keine Stille: Grenzen bleiben Wortgrenzen (plus Padding nach innen), nie im Nachbarwort
    words = grid_words(10, step=0.4, dur=0.4)  # Wörter stoßen direkt aneinander
    cuts = fuse([make_cut("f", 4, 4)], words, [], [], FPS, duration=10.0)
    assert len(cuts) == 1
    assert_no_boundary_in_kept_word(cuts, words)
    c = cuts[0]
    assert words[3].end <= c.start and c.end <= words[5].start
    # ohne Lücke gibt es nichts zu padden: das entfernte Wort wird bis auf Frame-Rundung vollständig entfernt
    assert c.start <= words[4].start + 1 / FPS and c.end >= words[4].end - 1 / FPS


def test_padding_only_uses_gap_between_words():
    words = [Word(id=0, text="a", start=0.5, end=0.9), Word(id=1, text="äh", start=1.0, end=1.3),
             Word(id=2, text="b", start=1.5, end=1.9)]
    cuts = fuse([make_cut("f", 1, 1)], words, [], [], FPS, duration=3.0)
    c = cuts[0]
    # 100 ms Lücke vor "äh": Padding darf höchstens bis zum Wortanfang schrumpfen, nie hinein
    assert words[0].end <= c.start <= words[1].start
    assert words[1].end <= c.end <= words[2].start


def test_long_pause_removes_gap_not_words():
    words = [Word(id=0, text="a", start=0.5, end=0.9), Word(id=1, text="b", start=3.0, end=3.4)]
    sil = [SilenceInterval(start=0.95, end=2.95)]
    cuts = fuse([make_cut("p", 0, 1, CutReason.long_pause, 0.8)], words, sil, [], FPS, duration=5.0)
    assert len(cuts) == 1
    c = cuts[0]
    assert c.start >= words[0].end and c.end <= words[1].start
    assert_no_boundary_in_kept_word(cuts, words)


def test_scene_change_splits_cut():
    words = grid_words(20)
    scenes = [SceneChange(frame=125, time=5.0, detector="content")]
    cuts = fuse([make_cut("r", 6, 12, CutReason.retake)], words, [], scenes, FPS, duration=12.0)
    assert len(cuts) == 2
    assert cuts[0].end <= 5.0 <= cuts[1].start
    assert cuts[0].id == "r.0" and cuts[1].id == "r.1"


def test_close_cuts_merge_and_retake_wins():
    words = grid_words(20)
    raw = [make_cut("f", 5, 5, CutReason.filler, 0.9), make_cut("r", 6, 9, CutReason.retake, 0.7)]
    cuts = fuse(raw, words, [], [], FPS, duration=12.0)
    assert len(cuts) == 1
    c = cuts[0]
    assert c.reason == CutReason.retake
    assert c.id == "r"
    assert (c.start_word, c.end_word) == (5, 9)
    assert c.confidence == 0.9


def test_min_segment_at_start_extends_to_zero():
    words = grid_words(10, t0=0.2)
    cuts = fuse([make_cut("f", 0, 0)], words, [], [], FPS, duration=6.0)
    assert cuts[0].start == 0.0
    assert MIN_SEGMENT == 0.4


def test_invalid_word_ids_are_dropped():
    words = grid_words(5)
    assert fuse([make_cut("x", 3, 9)], words, [], [], FPS) == []
