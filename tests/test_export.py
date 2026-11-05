"""FCPXML/EDL-Export und decisions.json."""

from __future__ import annotations

import re
from pathlib import Path

import opentimelineio as otio
from lxml import etree

from visualcut import decisions as decisions_mod, export as export_mod
from visualcut.cache import ProjectCache
from visualcut.schema import CutStatus, FusionResult, MediaInfo, Stage

RATIONAL = re.compile(r"^-?\d+(/\d+)?s$")


def _load(analyzed: ProjectCache):
    media = analyzed.load(Stage.ingest, MediaInfo)
    cuts = analyzed.load(Stage.fusion, FusionResult).cuts
    assert cuts, "Fixture-Fusion liefert keine Cuts"
    return media, cuts


def validate_fcpxml(path: Path) -> etree._Element:
    """Strukturprüfung nach dem FCPXML-DTD-Grundgerüst (Apple veröffentlicht die DTD nur in Final Cut)."""
    root = etree.parse(str(path)).getroot()
    assert root.tag == "fcpxml" and re.match(r"^\d+\.\d+$", root.get("version", ""))
    resources = root.find("resources")
    assert resources is not None
    formats = resources.findall("format")
    assert formats and all(f.get("id") and RATIONAL.match(f.get("frameDuration", "")) and f.get("width") and f.get("height") for f in formats)
    assets = resources.findall("asset")
    assert assets and all(a.get("id") and a.get("src") and a.get("hasVideo") == "1" and a.get("hasAudio") == "1" for a in assets)
    projects = root.findall("library/event/project")
    assert len(projects) == 1
    sequences = projects[0].findall("sequence")
    assert len(sequences) == 1
    seq = sequences[0]
    assert seq.get("format") in {f.get("id") for f in formats} and RATIONAL.match(seq.get("duration", ""))
    spine = seq.find("spine")
    assert spine is not None
    clips = spine.findall("asset-clip")
    assert clips
    expected_offset = 0.0
    for c in clips:
        for attr in ("offset", "duration", "start"):
            assert RATIONAL.match(c.get(attr, "")), (c.tag, attr, c.get(attr))
        assert c.get("ref") in {a.get("id") for a in assets}
        assert abs(_sec(c.get("offset")) - expected_offset) < 1e-9  # Clips liegen lückenlos hintereinander
        expected_offset = _sec(c.get("offset")) + _sec(c.get("duration"))
        for m in c.findall("marker"):
            assert RATIONAL.match(m.get("start", "")) and RATIONAL.match(m.get("duration", "")) and m.get("value")
            assert _sec(c.get("start")) <= _sec(m.get("start")) < _sec(c.get("start")) + _sec(c.get("duration"))
    return root


def _sec(r: str) -> float:
    from fractions import Fraction

    return float(Fraction(r.rstrip("s")))





def test_fcpxml_markers_for_open_cuts(analyzed: ProjectCache, tmp_path: Path):
    media, cuts = _load(analyzed)
    tl = export_mod.build_timeline(media, cuts, include_open=False)
    out = export_mod.write(tl, tmp_path / "offen.fcpxml", "fcpxml")
    root = validate_fcpxml(out)
    assert len(root.findall(".//spine/asset-clip")) == 1  # nichts geschnitten
    assert len(root.findall(".//marker")) == len(cuts)
    assert len(tl.tracks[0][0].markers) == len(cuts)


def test_fcpxml_cuts_applied_and_rejected_missing(analyzed: ProjectCache, tmp_path: Path):
    media, cuts = _load(analyzed)
    cuts = [c.model_copy(update={"status": CutStatus.accepted}) for c in cuts]
    cuts[0] = cuts[0].model_copy(update={"status": CutStatus.rejected})
    tl = export_mod.build_timeline(media, cuts, include_open=False)
    out = export_mod.write(tl, tmp_path / "schnitt.fcpxml", "fcpxml")
    root = validate_fcpxml(out)
    clips = root.findall(".//spine/asset-clip")
    assert len(clips) == len(cuts) - 1 + 1  # n-1 Cuts -> n Segmente
    assert root.findall(".//marker") == []
    kept = sum(item.duration().to_seconds() for item in tl.tracks[0])
    removed = sum(c.end - c.start for c in cuts if c.status == CutStatus.accepted)
    assert abs(kept + removed - media.duration) < 1 / media.fps + 1e-6


def test_edl_and_otio_written(analyzed: ProjectCache, tmp_path: Path):
    media, cuts = _load(analyzed)
    tl = export_mod.build_timeline(media, cuts, include_open=True)
    edl = export_mod.write(tl, tmp_path / "s.edl", "edl").read_text()
    assert "TITLE:" in edl and "V     C" in edl
    otio_path = export_mod.write(tl, tmp_path / "s.otio", "otio")
    assert otio.adapters.read_from_file(str(otio_path)).name == tl.name


def test_decisions_roundtrip(analyzed: ProjectCache):
    _, cuts = _load(analyzed)
    d = decisions_mod.set_status(analyzed, cuts[0].id, CutStatus.rejected, "zu hart")
    assert d.as_map()[cuts[0].id].status == CutStatus.rejected
    applied = decisions_mod.apply(cuts, decisions_mod.load(analyzed))
    assert applied[0].status == CutStatus.rejected and applied[1].status == CutStatus.open
    decisions_mod.set_status(analyzed, cuts[0].id, CutStatus.open)
    assert decisions_mod.load(analyzed).items == []
