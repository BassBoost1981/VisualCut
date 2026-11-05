"""Stufe 5: OpenTimelineIO als kanonisches Objekt, daraus FCPXML (eigener Writer, Resolve-tauglich)
und EDL (cmx_3600-Adapter). Vorschau-Render per ffmpeg."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

import opentimelineio as otio

from .decisions import for_export
from .ingest import run
from .schema import Cut, MediaInfo

REASON_COLORS = {
    "filler": otio.schema.MarkerColor.ORANGE,
    "retake": otio.schema.MarkerColor.RED,
    "long_pause": otio.schema.MarkerColor.CYAN,
    "tangent": otio.schema.MarkerColor.PURPLE,
    "false_start": otio.schema.MarkerColor.PINK,
    "redundant": otio.schema.MarkerColor.YELLOW,
    "technical": otio.schema.MarkerColor.WHITE,
}


def kept_segments(duration: float, cuts: list[Cut]) -> list[tuple[float, float]]:
    """Komplement der Cuts innerhalb [0, duration], sortiert und ohne Überlappung."""
    segs: list[tuple[float, float]] = []
    pos = 0.0
    for c in sorted(cuts, key=lambda c: c.start or 0):
        if c.start is None or c.end is None:
            continue
        if c.start > pos:
            segs.append((pos, c.start))
        pos = max(pos, c.end)
    if pos < duration:
        segs.append((pos, duration))
    return segs


def _rt(seconds: float, fps: float) -> otio.opentime.RationalTime:
    return otio.opentime.RationalTime(round(seconds * fps), fps)


def build_timeline(media: MediaInfo, cuts: list[Cut], include_open: bool = False, name: str | None = None) -> otio.schema.Timeline:
    """Eine Videospur mit den erhaltenen Segmenten. Offene Cuts werden als Marker am Clip gesetzt,
    außer include_open=True, dann werden sie geschnitten. Verworfene fehlen."""
    fps = media.fps
    to_cut, to_mark = for_export(cuts, include_open)
    tl = otio.schema.Timeline(name=name or Path(media.path).stem)
    tl.global_start_time = otio.opentime.RationalTime(0, fps)
    tl.metadata["visualcut"] = {
        "path": media.path, "fps": fps, "width": media.width, "height": media.height,
        "has_audio": media.has_audio, "duration": media.duration,
    }
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    tl.tracks.append(track)
    ref = otio.schema.ExternalReference(
        target_url=Path(media.path).as_uri(),
        available_range=otio.opentime.TimeRange(_rt(0, fps), _rt(media.duration, fps)),
    )
    stem = Path(media.path).stem
    for k, (s, e) in enumerate(kept_segments(media.duration, to_cut)):
        clip = otio.schema.Clip(
            name=f"{stem}_{k + 1:03d}", media_reference=ref,
            source_range=otio.opentime.TimeRange(_rt(s, fps), _rt(e - s, fps)),
        )
        for c in to_mark:
            if c.start is None or c.end is None or not (s <= c.start < e):
                continue
            m = otio.schema.Marker(
                name=f"{c.reason.value} {c.confidence:.2f} {c.note}".strip(),
                marked_range=otio.opentime.TimeRange(_rt(c.start, fps), _rt(max(min(c.end, e) - c.start, 1 / fps), fps)),
                color=REASON_COLORS.get(c.reason.value, otio.schema.MarkerColor.GREEN),
            )
            m.metadata["visualcut"] = {"cut_id": c.id, "reason": c.reason.value, "confidence": c.confidence}
            clip.markers.append(m)
        track.append(clip)
    return tl


# ---------------------------------------------------------------- FCPXML


def _frame_rate(fps: float) -> Fraction:
    """25 -> 25/1, 29.97 -> 30000/1001, 23.976 -> 24000/1001."""
    f = Fraction(fps).limit_denominator(1001)
    if f.denominator == 1001:
        return f
    return Fraction(round(fps), 1)


def _t(rt: otio.opentime.RationalTime, rate: Fraction) -> str:
    frames = round(rt.rescaled_to(float(rate)).value)
    if frames == 0:
        return "0s"
    return f"{frames * rate.denominator}/{rate.numerator}s"


def to_fcpxml(tl: otio.schema.Timeline) -> bytes:
    """FCPXML 1.9 mit library/event/project, Format mit Auflösung, Asset mit Audio-Flag, Marker an Clips."""
    meta = dict(tl.metadata.get("visualcut", {}))
    fps = float(meta.get("fps", tl.global_start_time.rate if tl.global_start_time else 25.0))
    rate = _frame_rate(fps)
    track = tl.tracks[0]
    src_path = Path(meta.get("path", "")) if meta.get("path") else None

    root = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", id="r1", name=f"FFVideoFormat{meta.get('height', 1080)}p{rate.numerator / rate.denominator:g}".replace(".", "_"),
                  frameDuration=f"{rate.denominator}/{rate.numerator}s",
                  width=str(meta.get("width", 1920)), height=str(meta.get("height", 1080)))
    total = otio.opentime.RationalTime(round(float(meta.get("duration", 0)) * fps), fps)
    ET.SubElement(resources, "asset", id="r2", name=src_path.stem if src_path else tl.name, start="0s",
                  duration=_t(total, rate), hasVideo="1", hasAudio="1" if meta.get("has_audio") else "0",
                  format="r1", src=src_path.as_uri() if src_path else "")

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name=tl.name)
    project = ET.SubElement(event, "project", name=tl.name)
    seq_dur = sum((c.duration() for c in track), otio.opentime.RationalTime(0, fps))
    sequence = ET.SubElement(project, "sequence", format="r1", duration=_t(seq_dur, rate), tcStart="0s", tcFormat="NDF")
    spine = ET.SubElement(sequence, "spine")
    offset = otio.opentime.RationalTime(0, fps)
    for clip in track:
        sr = clip.source_range
        el = ET.SubElement(spine, "asset-clip", name=clip.name, ref="r2", offset=_t(offset, rate),
                           start=_t(sr.start_time, rate), duration=_t(sr.duration, rate), format="r1", tcFormat="NDF")
        if meta.get("has_audio"):
            el.set("audioRole", "dialogue")
        for m in clip.markers:
            # Marker-start ist in Quellzeit des Clips (wie sr.start_time)
            ET.SubElement(el, "marker", start=_t(m.marked_range.start_time, rate),
                          duration=_t(m.marked_range.duration, rate), value=m.name)
        offset += sr.duration
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="utf-8")


# ---------------------------------------------------------------- Marker-EDL für DaVinci Resolve

RESOLVE_MARKER_COLORS = {
    "filler": "Yellow", "retake": "Red", "long_pause": "Cyan", "tangent": "Purple",
    "false_start": "Pink", "redundant": "Lemon", "technical": "Cream",
}
FORMATS = ("fcpxml", "edl", "otio", "markers-edl")


def _tc(frames: int, fps: float) -> str:
    f = int(round(fps))
    h, rem = divmod(frames, 3600 * f)
    m, rem = divmod(rem, 60 * f)
    sec, fr = divmod(rem, f)
    return f"{h:02d}:{m:02d}:{sec:02d}:{fr:02d}"


def to_marker_edl(tl: otio.schema.Timeline) -> str:
    """Timeline-Marker im EDL-Format, das Resolve unter Timeline > Import > Timeline Markers from EDL liest.
    Ein Event pro Marker, darunter die Zeile `|C:ResolveColor<Farbe> |M:<Name> |D:<Dauer in Frames>`.
    FCPXML transportiert keine Marker-Farben, darum dieser Weg."""
    meta = dict(tl.metadata.get("visualcut", {}))
    fps = float(meta.get("fps", 25.0))
    lines = [f"TITLE: {tl.name}", "FCM: NON-DROP FRAME", ""]
    n = 0
    offset = otio.opentime.RationalTime(0, fps)
    for clip in tl.tracks[0]:
        sr = clip.source_range
        for m in clip.markers:
            tl_start = offset + (m.marked_range.start_time - sr.start_time)
            start = round(tl_start.rescaled_to(fps).value)
            dur = max(1, round(m.marked_range.duration.rescaled_to(fps).value))
            reason = (m.metadata.get("visualcut") or {}).get("reason", "")
            color = RESOLVE_MARKER_COLORS.get(reason, "Blue")
            n += 1
            lines.append(f"{n:03d}  001      V     C        {_tc(start, fps)} {_tc(start + 1, fps)} {_tc(start, fps)} {_tc(start + 1, fps)}")
            name = m.name.replace("|", "/")  # `|` trennt in Resolves EDL die Felder
            lines.append(f" |C:ResolveColor{color} |M:{name} |D:{dur}")
            lines.append("")
        offset += sr.duration
    return "\n".join(lines) + "\n"


def write(tl: otio.schema.Timeline, out: Path, fmt: str) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "fcpxml":
        out.write_bytes(to_fcpxml(tl))
        return out
    if fmt == "markers-edl":
        out.write_text(to_marker_edl(tl), encoding="utf-8", newline="\r\n")
        return out
    adapter = {"edl": "cmx_3600", "otio": "otio_json"}[fmt]
    otio.adapters.write_to_file(tl, str(out), adapter_name=adapter)
    return out


# ---------------------------------------------------------------- Render


def render_preview(media: MediaInfo, cuts: list[Cut], out: Path, include_open: bool = False, source: str | None = None) -> Path:
    """ffmpeg-Vorschau: erhaltene Segmente trimmen und per concat-Filter aneinanderhängen."""
    to_cut, _ = for_export(cuts, include_open)
    segs = kept_segments(media.duration, to_cut)
    if not segs:
        raise ValueError("Alle Inhalte wären geschnitten, nichts zu rendern")
    src = source or media.proxy_path or media.path
    parts = []
    for i, (s, e) in enumerate(segs):
        parts.append(f"[0:v]trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS[v{i}];")
        if media.has_audio:
            parts.append(f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS[a{i}];")
    n = len(segs)
    if media.has_audio:
        parts.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]")
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]")
        maps = ["-map", "[v]"]
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", "".join(parts), *maps,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])
    return out
