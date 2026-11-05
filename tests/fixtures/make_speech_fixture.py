"""Sprach-Fixture mit Windows-TTS (de-DE): Füllwörter, ein Retake und eine lange Pause.

Nur auf Windows mit einer deutschen SAPI-Stimme erzeugbar. Tests, die es brauchen,
werden übersprungen, wenn die Datei nicht gebaut werden kann.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SENTENCES = [
    "Hallo und herzlich willkommen zu diesem Tutorial über Videoschnitt.",
    "Ähm, heute zeige ich euch, wie man ein Video schneidet.",
    "Also, zuerst öffnen wir das Programm und laden das Material.",
    "Dann ziehen wir die Clips in die Timeline und ordnen sie an.",  # Retake, erste Instanz
    "Dann ziehen wir die Clips in die Timeline und ordnen sie an.",  # Retake, zweite Instanz
    "Das war äh eigentlich schon alles für heute, vielen Dank.",
]
PAUSE_AFTER = {2: 1.8}  # Index des Satzes -> Pause in Sekunden danach (lange Pause > 1,2 s)

PS_SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -eq 'de-DE' } | Select-Object -First 1
if (-not $v) { exit 3 }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = 0
$s.SetOutputToWaveFile($args[0])
$b = New-Object System.Speech.Synthesis.PromptBuilder
%BODY%
$s.Speak($b)
$s.Dispose()
"""


def build(out: Path) -> Path | None:
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    wav = out.with_suffix(".wav")
    body = []
    for i, s in enumerate(SENTENCES):
        body.append(f"$b.AppendText('{s.replace(chr(39), chr(39) * 2)}')")
        body.append(f"$b.AppendBreak([System.TimeSpan]::FromMilliseconds({int(PAUSE_AFTER.get(i, 0.5) * 1000)}))")
    script = PS_SCRIPT.replace("%BODY%", "\n".join(body))
    ps1 = out.with_suffix(".ps1")
    ps1.write_text(script, encoding="utf-8-sig")  # BOM, damit PowerShell die Umlaute als UTF-8 liest
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ps1), str(wav)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    finally:
        ps1.unlink(missing_ok=True)
    if r.returncode != 0 or not wav.exists():
        return None
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
                               capture_output=True, text=True).stdout.strip())
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={dur:.3f}",
        "-i", str(wav), "-map", "0:v", "-map", "1:a", "-shortest",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", str(out),
    ], check=True)
    wav.unlink(missing_ok=True)
    return out


if __name__ == "__main__":
    print(build(Path(__file__).with_name("speech_de.mp4")))
