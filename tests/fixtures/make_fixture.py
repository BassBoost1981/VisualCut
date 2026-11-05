"""Synthetisches Testvideo: testsrc-Segmente mit harten Schnitten und Stille-Inseln im Ton.

Aufbau (25 fps, 20 s):
  0.0 -  4.0  testsrc,     Ton 440 Hz
  4.0 -  8.0  smptebars,   Ton bis 5.0, Stille 5.0 - 6.5, Ton ab 6.5
  8.0 - 14.0  testsrc2,    Ton bis 10.0, Stille 10.0 - 10.6, Ton ab 10.6
 14.0 - 20.0  rgbtestsrc,  Ton bis 17.0, Stille bis 20.0

Harte Schnitte bei Frame 100, 200, 350 (4 s, 8 s, 14 s).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FPS = 25
SCENE_CUT_FRAMES = [100, 200, 350]
SILENCES = [(5.0, 6.5), (10.0, 10.6), (17.0, 20.0)]
DURATION = 20.0


def build(out: Path) -> Path:
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    vol = "+".join(f"between(t,{s},{e})" for s, e in SILENCES)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size=640x360:rate={FPS}:duration=4",
        "-f", "lavfi", "-i", f"smptebars=size=640x360:rate={FPS}:duration=4",
        "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate={FPS}:duration=6",
        "-f", "lavfi", "-i", f"rgbtestsrc=size=640x360:rate={FPS}:duration=6",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={DURATION}",
        "-filter_complex",
        "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0[v];"
        f"[4:a]volume='if({vol},0,0.5)':eval=frame[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-g", "12", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(DURATION),
        str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


if __name__ == "__main__":
    print(build(Path(__file__).with_name("synthetic.mp4")))
