"""Regelbasierte Cuts auf konstruierten Wortlisten."""

from __future__ import annotations

from visualcut.schema import CutReason, Word
from visualcut.speech import filler_cuts, long_pause_cuts, retake_cuts


def words_from(text: str, gap_after: dict[int, float] | None = None) -> list[Word]:
    out: list[Word] = []
    t = 0.0
    for i, tok in enumerate(text.split()):
        out.append(Word(id=i, text=tok, start=round(t, 3), end=round(t + 0.3, 3)))
        t += 0.3 + (gap_after or {}).get(i, 0.1)
    return out


def test_filler_lexicon():
    w = words_from("Ähm, heute zeige ich äh euch halt alles. Also, los.")
    cuts = filler_cuts(w)
    assert [c.start_word for c in cuts] == [0, 4, 6, 8]
    assert all(c.reason == CutReason.filler for c in cuts)


def test_also_only_at_sentence_start():
    w = words_from("Ich bin also nicht sicher. Also fangen wir an.")
    cuts = filler_cuts(w)
    assert [c.start_word for c in cuts] == [5]


def test_retake_first_instance_is_candidate():
    w = words_from("Dann ziehen wir die Clips in die Timeline. Dann ziehen wir die Clips in die Timeline. Fertig.")
    cuts = retake_cuts(w)
    assert len(cuts) == 1
    c = cuts[0]
    assert (c.start_word, c.end_word) == (0, 7)
    assert c.reason == CutReason.retake


def test_retake_fuzzy_and_anchored():
    # kleiner Versprecher in der ersten Instanz, Fenster-Anker verhindert Fehltreffer bei ähnlichem Kontext
    w = words_from("und laden das Material. Dann ziehn wir die Clips in die Timeline und ordnen sie an. "
                   "Dann ziehen wir die Clips in die Timeline und ordnen sie an.")
    cuts = retake_cuts(w)
    assert len(cuts) == 1
    assert cuts[0].start_word == 4  # "Dann", nicht "und laden..."
    assert cuts[0].end_word == 15


def test_retake_window_15s():
    w = words_from("eins zwei drei vier fünf sechs eins zwei drei vier fünf sechs", gap_after={5: 16.0})
    assert retake_cuts(w) == []


def test_long_pause():
    w = words_from("eins zwei drei vier", gap_after={1: 1.5})
    cuts = long_pause_cuts(w)
    assert len(cuts) == 1
    assert (cuts[0].start_word, cuts[0].end_word) == (1, 2)
    assert cuts[0].reason == CutReason.long_pause
