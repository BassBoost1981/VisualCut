"""Stufe 0: ffprobe-Metadaten, 720p-Proxy mit konstanter Framerate, 16-kHz-Mono-WAV."""

from __future__ import annotations

import json
import os
import subprocess
from fractions import Fraction
from pathlib import Path

from .cache import ProgressFn, ProjectCache, emit
from .schema import MediaInfo, Stage


class StageError(RuntimeError):
    """Eine Stufe ist fehlgeschlagen (Exit-Code 3)."""


# Desktop-Exe ohne Konsole: ffmpeg nie von einem ungültigen stdin lesen lassen und kein Konsolenfenster öffnen
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def tool_cmd(cmd: list[str]) -> list[str]:
    return [cmd[0], "-nostdin", *cmd[1:]] if cmd[0] == "ffmpeg" and "-nostdin" not in cmd else cmd


def run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    cmd = tool_cmd(cmd)
    try:
        return subprocess.run(cmd, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, **kw)
    except FileNotFoundError as e:
        raise StageError(f"{cmd[0]} nicht gefunden, ist es auf dem PATH?") from e
    except subprocess.CalledProcessError as e:
        raise StageError(f"{cmd[0]} fehlgeschlagen (Code {e.returncode}): {(e.stderr or '')[-2000:]}") from e


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
        path=os.path.abspath(video),
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


def rebase(info: MediaInfo, cache: ProjectCache) -> MediaInfo:
    """Proxy und WAV liegen immer im Cache-Ordner; gespeicherte absolute Pfade auf den aktuellen Ort umbiegen."""
    for attr, name in (("proxy_path", "proxy.mp4"), ("audio_path", "audio.wav")):
        if getattr(info, attr) and cache.path(name).exists():
            setattr(info, attr, str(cache.path(name)))
    return info


def ingest(video: Path, cache: ProjectCache, progress: ProgressFn | None = None, force: bool = False) -> MediaInfo:
    stage = Stage.ingest
    if cache.has(stage) and not force:
        info = rebase(cache.load(stage, MediaInfo), cache)
        info.path = os.path.abspath(video)  # anderer Laufwerksbuchstabe (USB): aktuellen Pfad merken
        if info.proxy_path and Path(info.proxy_path).exists():
            cache.save(stage, info)
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
