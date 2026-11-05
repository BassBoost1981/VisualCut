# Baut die eigenständige VisualCut-App nach dist\VisualCut\VisualCut.exe.
# Voraussetzung: uv, Node, ffmpeg/ffprobe auf dem PATH. Dauer: mehrere Minuten, Ergebnis rund 5 GB.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "1/4 Python-Abhängigkeiten (speech, desktop)"
uv sync --extra speech --extra desktop --extra dev

Write-Host "2/4 UI bauen"
Push-Location ui
npm ci --no-audit --no-fund
npm run build
Pop-Location

Write-Host "3/4 Icon"
uv run python packaging\make_icon.py

Write-Host "4/4 PyInstaller"
uv run pyinstaller packaging\visualcut.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller

Write-Host "Fertig: $root\dist\VisualCut\VisualCut.exe"
