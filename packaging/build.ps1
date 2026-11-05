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

Write-Host "4/5 PyInstaller"
# PyInstaller löscht dist\VisualCut komplett; Modelle und Analysen in data\ vorher beiseitelegen
$data = "dist\VisualCut\data"; $keep = "build\data-keep"
if (Test-Path $data) { New-Item -ItemType Directory -Force build | Out-Null; Move-Item $data $keep }
try {
    uv run pyinstaller packaging\visualcut.spec --noconfirm --clean --distpath dist --workpath build\pyinstaller
} finally {
    if (Test-Path $keep) { Move-Item $keep $data }
}

Write-Host "5/5 Modelle in den App-Ordner (USB-portabel, offline)"
uv run python packaging\bundle_models.py dist\VisualCut

Write-Host "Fertig: $root\dist\VisualCut\VisualCut.exe"
