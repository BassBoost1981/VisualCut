"""Kopiert die KI-Modelle in den portablen App-Ordner (dist/VisualCut/data/models).

Whisper (Hugging Face, faster-whisper) und die Alignment-Modelle (torch.hub, whisperX) kommen aus den
Caches des Build-Rechners. Fehlt ein Modell dort, wird es vorher geladen. Danach braucht die Exe kein Netz.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

WHISPER = ["Systran/faster-whisper-large-v3", "Systran/faster-whisper-medium"]
ALIGN_LANGUAGES = ["de", "en"]
# Stufe 1b (Ereignisse): CLAP (Audio), X-CLIP und VideoMAE (Aktionen); IDs wie in visualcut.events
EVENT_HF = ["laion/clap-htsat-unfused", "microsoft/xclip-base-patch32", "MCG-NJU/videomae-base-finetuned-kinetics"]


def hf_hub() -> Path:
    from huggingface_hub.constants import HF_HUB_CACHE

    return Path(HF_HUB_CACHE)


def torch_checkpoints() -> Path:
    import torch.hub

    return Path(torch.hub.get_dir()) / "checkpoints"


def ensure_sources() -> None:
    from huggingface_hub import snapshot_download

    for repo in WHISPER + EVENT_HF:
        print(f"Hugging Face {repo}")
        snapshot_download(repo)
    import whisperx

    for lang in ALIGN_LANGUAGES:
        print(f"Alignment {lang}")
        model, _ = whisperx.load_align_model(language_code=lang, device="cpu")
        del model


def copy_tree(src: Path, dst: Path) -> None:
    """Symlinks auflösen (HF-Cache), vorhandene gleich große Dateien überspringen."""
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        target = dst / f.relative_to(src)
        real = f.resolve()
        if target.exists() and target.stat().st_size == real.stat().st_size:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(real, target)


def copy_nltk(target: Path) -> None:
    """Satzdaten `punkt_tab` für das whisperX-Alignment: aus dem lokalen NLTK-Ordner oder frisch laden."""
    import nltk

    for base in map(Path, nltk.data.path):
        src = base / "tokenizers" / "punkt_tab"
        if src.is_dir():
            copy_tree(src, target / "tokenizers" / "punkt_tab")
            return
    nltk.download("punkt_tab", download_dir=str(target), quiet=True)


def copy_pose(models: Path) -> None:
    """RTMPose + YOLOX (ONNX, rtmlib) nach torch/hub/checkpoints, wo rtmlib bei TORCH_HOME sucht, und das
    MediaPipe-Ersatzmodell nach torch/visualcut (visualcut.events.pose.models_dir)."""
    import urllib.request

    from rtmlib import Body
    from rtmlib.tools.file import download_checkpoint

    from visualcut.events.pose import MP_MODEL_URL

    dst = models / "torch" / "hub" / "checkpoints"
    dst.mkdir(parents=True, exist_ok=True)
    cfg = Body.MODE["lightweight"]
    for url in (cfg["det"], cfg["pose"]):
        print(f"Pose {Path(url).stem}")
        onnx = Path(download_checkpoint(url))  # lädt bei Bedarf in den rtmlib-Cache des Build-Rechners
        if not (dst / onnx.name).exists():
            shutil.copy2(onnx, dst / onnx.name)
    mp = models / "torch" / "visualcut" / "pose_landmarker_lite.task"
    if not mp.exists():
        mp.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MP_MODEL_URL, mp)


def main(app_dir: Path) -> None:
    ensure_sources()
    models = app_dir / "data" / "models"
    for repo in WHISPER + EVENT_HF:
        name = "models--" + repo.replace("/", "--")
        copy_tree(hf_hub() / name, models / "huggingface" / "hub" / name)
    copy_tree(torch_checkpoints(), models / "torch" / "hub" / "checkpoints")
    copy_pose(models)
    copy_nltk(models / "nltk_data")
    size = sum(f.stat().st_size for f in models.rglob("*") if f.is_file())
    print(f"Modelle in {models}: {size / 1e9:.1f} GB")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "dist" / "VisualCut")
