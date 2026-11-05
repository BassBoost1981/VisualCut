from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(FIXTURES))

from make_fixture import FPS, SCENE_CUT_FRAMES, SILENCES, build  # noqa: E402

from visualcut.cache import ProjectCache  # noqa: E402
from visualcut.fusion import fuse  # noqa: E402
from visualcut.ingest import ingest  # noqa: E402
from visualcut.events import catalog  # noqa: E402
from visualcut.schema import Cut, CutReason, EventsResult, FusionResult, SpeechResult, Stage, Word  # noqa: E402
from visualcut.speech import rule_cuts  # noqa: E402
from visualcut.technical import analyze_technical  # noqa: E402

__all__ = ["FPS", "SCENE_CUT_FRAMES", "SILENCES"]


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@pytest.fixture(scope="session")
def synthetic_video() -> Path:
    if not _has("ffmpeg") or not _has("ffprobe"):
        pytest.skip("ffmpeg fehlt")
    return build(FIXTURES / "synthetic.mp4")


@pytest.fixture(scope="session")
def session_cache_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("visualcut-cache")


@pytest.fixture(scope="session")
def analyzed(synthetic_video: Path, session_cache_root: Path) -> ProjectCache:
    """Stufe 0 und 1 echt, Stufe 2 konstruiert (Whisper muss hier nicht laufen), Stufe 4 echt."""
    cache = ProjectCache.for_video(synthetic_video, session_cache_root)
    media = ingest(synthetic_video, cache)
    tech = analyze_technical(media, cache)
    # Stufe 1b konstruiert (leer), damit hier keine Modelle laden; echte Läufe stehen in test_events.py
    cache.save(Stage.events, EventsResult(detection_hash=catalog.detection_hash(catalog.load(cache))))
    words = fake_words()
    speech = SpeechResult(words=words, language="de", model="fake", device="cpu", aligned=False,
                          text=" ".join(w.text for w in words))
    cache.save(Stage.speech, speech)
    cuts = fuse(rule_cuts(words), words, tech.silences, tech.scenes, media.fps, media.duration)
    cache.save(Stage.fusion, FusionResult(cuts=cuts, fps=media.fps))
    return cache


def fake_words() -> list[Word]:
    """Wörter im Raster 0,4 s Dauer plus 0,1 s Abstand; die Stille-Inseln des Fixtures bleiben frei."""
    text = ("hallo und herzlich willkommen ähm heute zeige ich euch wie das geht "
            "also zuerst öffnen wir das programm dann laden wir das material "
            "dann ziehen wir die clips in die timeline dann ziehen wir die clips in die timeline "
            "das war äh alles für heute vielen dank und bis zum nächsten mal").split()
    words: list[Word] = []
    t = 0.3
    for tok in text:
        for s, e in SILENCES:
            if s - 0.05 <= t <= e + 0.05 or (t < s < t + 0.4):
                t = e + 0.15
        if t + 0.4 > 20.0:
            break
        words.append(Word(id=len(words), text=tok, start=round(t, 3), end=round(t + 0.4, 3)))
        t += 0.5
    return words


def make_cut(id_: str, a: int, b: int, reason: CutReason = CutReason.filler, conf: float = 0.9) -> Cut:
    return Cut(id=id_, start_word=a, end_word=b, reason=reason, confidence=conf)
