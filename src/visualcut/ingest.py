"""Stufe 0: ffprobe-Metadaten, 720p-Proxy mit konstanter Framerate, 16-kHz-Mono-WAV."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path

from .cache import ProgressFn, ProjectCache, emit
from .schema import MediaInfo, Stage


class StageError(RuntimeError):
    """Eine Stufe ist fehlgeschlagen (Exit-Code 3)."""


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    except FileNotFoundError as e:
        raise StageError(f"{cmd[0]} nicht gefunden, ist es auf dem PATH?") from e
    except subprocess.CalledProcessError as e:
        raise StageError(f"{cmd[0]} fehlgeschlagen: {e.stderr[-2000:]}") from e


def _fps(stream: dict) -> tuple[float, bool]:
    r = Fraction(stream.get("r_frame_rate", "25/1") or "25/1")
    avg = Fraction(stream.get("avg_frame_rate", "0/1") or "0/1")
    if avg == 0:
        return float(r), False
    vfr = abs(float(r) - float(avg)) > 0.01
    return float(avg if vfr else r), vfr


def probe(video: Path, hash_: str) -> MediaInfo:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)]).stdout
    data = json.loads(out)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        raise StageError("Keine Videospur gefunden")
    fps, vfr = _fps(v)
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    nb = int(v.get("nb_frames") or 0) or round(duration * fps)
    return MediaInfo(
        path=str(video.resolve()),
        content_hash=hash_,
        size_bytes=video.stat().st_size,
        duration=duration,
        fps=fps,
        variable_framerate=vfr,
        width=int(v["width"]),
        height=int(v["height"]),
        video_codec=v.get("codec_name"),
        audio_codec=a.get("codec_name") if a else None,
        audio_channels=int(a.get("channels", 0)) if a else 0,
        audio_sample_rate=int(a.get("sample_rate", 0)) if a else 0,
        has_audio=a is not None,
        frame_count=nb,
    )


def make_proxy(video: Path, out: Path, fps: float) -> None:
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video),
        "-vf", f"scale=-2:'min(720,ih)',fps={fps:.6g}",
        "-fps_mode", "cfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ])


def extract_audio(video: Path, out: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)])


def ingest(video: Path, cache: ProjectCache, progress: ProgressFn | None = None, force: bool = False) -> MediaInfo:
    stage = Stage.ingest
    if cache.has(stage) and not force:
        info = cache.load(stage, MediaInfo)
        if info.proxy_path and Path(info.proxy_path).exists():
            emit(progress, "stage_skipped", stage, "Cache vorhanden")
            return info
    emit(progress, "stage_start", stage, str(video))
    info = probe(video, cache.hash)
    emit(progress, "progress", stage, "Metadaten gelesen", 10, fps=info.fps, duration=info.duration)
    proxy = cache.path("proxy.mp4")
    make_proxy(video, proxy, info.fps)
    info.proxy_path = str(proxy)
    emit(progress, "progress", stage, "Proxy erzeugt", 70)
    if info.has_audio:
        wav = cache.path("audio.wav")
        extract_audio(video, wav)
        info.audio_path = str(wav)
    emit(progress, "progress", stage, "Audio extrahiert", 95)
    cache.save(stage, info)
    emit(progress, "stage_done", stage)
    return info
