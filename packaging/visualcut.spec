# PyInstaller-Spec für die eigenständige VisualCut-App (onedir, ohne Konsole).
# Bauen: packaging\build.ps1  (baut vorher die UI und das Icon)
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "ui" / "dist"), "ui"),
    (str(ROOT / "prompts"), "visualcut/prompts"),
    (str(ROOT / "events.yaml"), "visualcut"),  # Standard-Ereignisliste (Stufe 1b)
]
binaries = []
hiddenimports = []

# ffmpeg/ffprobe vom PATH mitnehmen (Build-Rechner)
for tool in ("ffmpeg", "ffprobe"):
    exe = shutil.which(tool)
    if not exe:
        raise SystemExit(f"{tool} nicht auf dem PATH, wird für das Bundle gebraucht")
    binaries.append((exe, "ffmpeg"))

# NLTK-Satzdaten (punkt_tab) kopiert packaging/bundle_models.py nach data/models/nltk_data

for pkg in ("faster_whisper", "ctranslate2", "whisperx", "scenedetect", "opentimelineio",
            "otio_fcpx_xml_adapter", "otio_cmx3600_adapter", "webview", "nltk",
            "onnxruntime", "rtmlib", "mediapipe"):  # Stufe 1b: Pose (ONNX) und MediaPipe-Ersatz
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Paket-Metadaten: OTIO findet Adapter über Entry-Points, transformers prüft Versionen
for dist in ("otio-fcpx-xml-adapter", "otio-cmx3600-adapter", "opentimelineio", "transformers", "tokenizers",
             "huggingface-hub", "safetensors", "torch", "numpy", "tqdm", "regex", "requests", "packaging",
             "filelock", "pyyaml", "faster-whisper", "ctranslate2", "whisperx", "visualcut"):
    try:
        datas += copy_metadata(dist)
    except Exception:  # noqa: BLE001
        pass

datas += collect_data_files("transformers", include_py_files=False)
hiddenimports += collect_submodules("uvicorn") + collect_submodules("visualcut") + [
    "anthropic", "torchaudio", "transformers.models.wav2vec2",
]

a = Analysis(
    [str(ROOT / "packaging" / "visualcut_desktop.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "pytest", "PyInstaller"],  # matplotlib bleibt: MediaPipe (Pose-Ersatz) braucht es
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="VisualCut",
    icon=str(ROOT / "design" / "visualcut-v-transparent.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="VisualCut", upx=False)
