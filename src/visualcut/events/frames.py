"""Frames aus dem Proxy per ffmpeg-Pipe (rawvideo, RGB). Gemeinsam für Pose, X-CLIP, VideoMAE und Ebene C."""

from __future__ import annotations

import queue
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import numpy as np


def size_for(width: int, height: int, short_side: int) -> tuple[int, int]:
    """Zielgröße mit kurzer Seite `short_side`, gerade Werte (ffmpeg/yuv)."""
    if width >= height:
        h = short_side
        w = int(round(width * short_side / max(1, height) / 2) * 2)
    else:
        w = short_side
        h = int(round(height * short_side / max(1, width) / 2) * 2)
    return w, h


def iter_frames(video: Path, fps: float, width: int, height: int, start: float = 0.0,
                duration: float | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """(Zeit, RGB-Frame) mit fester Abtastrate. Zeit = start + k / fps."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video)]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-an", "-vf", f"fps={fps:.6g},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    frame_bytes = width * height * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert proc.stdout is not None
    # Lesethread: ffmpeg dekodiert weiter, während der Aufrufer rechnet (die Pipe puffert nur 64 KB)
    q: queue.Queue[bytes | None] = queue.Queue(maxsize=32)
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                buf = proc.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
                q.put(buf)
        finally:
            q.put(None)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    k = 0
    try:
        while (buf := q.get()) is not None:
            yield start + k / fps, np.frombuffer(buf, np.uint8).reshape(height, width, 3)
            k += 1
    finally:
        stop.set()
        proc.kill()
        while t.is_alive():  # Reader aus einem vollen q.put befreien
            try:
                q.get_nowait()
            except queue.Empty:
                t.join(0.05)
        proc.stdout.close()
        proc.wait()


def read_frames(video: Path, start: float, end: float, n: int, width: int, height: int) -> list[np.ndarray]:
    """Genau `n` gleichmäßig verteilte Frames aus [start, end). Fehlen am Videoende Frames, wird der letzte wiederholt."""
    span = max(end - start, 1e-3)
    fps = n / span
    frames = [f for _, f in iter_frames(video, fps, width, height, max(0.0, start), span)][:n]
    if not frames:
        return []
    while len(frames) < n:
        frames.append(frames[-1])
    return frames
