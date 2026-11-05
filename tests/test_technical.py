"""Stufe 0 und 1 auf dem synthetischen Fixture: Szenen auf ±1 Frame, Stille-Inseln, Proxy-Dauer."""

from __future__ import annotations

from conftest import FPS, SCENE_CUT_FRAMES, SILENCES

from visualcut.cache import ProjectCache
from visualcut.schema import MediaInfo, Stage, TechnicalResult


def test_ingest_metadata_and_proxy(analyzed: ProjectCache):
    media = analyzed.load(Stage.ingest, MediaInfo)
    assert media.fps == FPS
    assert media.has_audio
    assert media.frame_count == 500
    assert media.proxy_path and media.audio_path
    # Proxy-Dauer stimmt mit Original auf ±1 Frame
    from visualcut.ingest import probe

    from pathlib import Path

    proxy = probe(Path(media.proxy_path), "x")
    assert abs(proxy.duration - media.duration) <= 1 / FPS + 1e-6


def test_scene_cuts_within_one_frame(analyzed: ProjectCache):
    tech = analyzed.load(Stage.technical, TechnicalResult)
    found = sorted(s.frame for s in tech.scenes)
    assert len(found) == len(SCENE_CUT_FRAMES)
    for expected, got in zip(SCENE_CUT_FRAMES, found):
        assert abs(expected - got) <= 1, (expected, got)
    assert all(s.detector == "adaptive+content" for s in tech.scenes)


def test_silences_detected(analyzed: ProjectCache):
    tech = analyzed.load(Stage.technical, TechnicalResult)
    assert len(tech.silences) == len(SILENCES)
    for (es, ee), got in zip(SILENCES, tech.silences):
        assert abs(got.start - es) < 0.05
        assert abs(got.end - ee) < 0.05


def test_stage_skipped_on_second_run(analyzed: ProjectCache):
    from visualcut.ingest import ingest
    from visualcut.schema import ProgressEvent
    from pathlib import Path

    events: list[ProgressEvent] = []
    media = analyzed.load(Stage.ingest, MediaInfo)
    ingest(Path(media.path), analyzed, events.append)
    assert [e.event for e in events] == ["stage_skipped"]


def test_cache_paths_follow_moved_cache(analyzed: ProjectCache, tmp_path):
    """USB-Stick mit anderem Laufwerksbuchstaben: Cache-Ordner verschoben, Proxy/WAV-Pfade folgen."""
    import shutil

    from visualcut.pipeline import load_analysis

    moved_root = tmp_path / "anderes-laufwerk"
    shutil.copytree(analyzed.dir, moved_root / analyzed.hash)
    moved = ProjectCache(analyzed.hash, moved_root)
    media = load_analysis(moved).media
    assert media.proxy_path == str(moved.path("proxy.mp4"))
    assert media.audio_path == str(moved.path("audio.wav"))
