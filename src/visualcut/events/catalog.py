"""events.yaml laden und speichern. Reihenfolge: Projekt (.visualcut/<hash>/events.yaml), $VISUALCUT_EVENTS,
Repo-Root, Paket. Der Editor in den Einstellungen schreibt die globale Datei."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import yaml

from ..cache import ProjectCache
from ..schema import EventCatalog

FILENAME = "events.yaml"
ENV = "VISUALCUT_EVENTS"


def _candidates() -> list[Path]:
    pkg = Path(__file__).resolve().parents[1]
    out = []
    if os.environ.get(ENV):
        out.append(Path(os.environ[ENV]))
    out.append(pkg.parents[1] / FILENAME)  # Repo-Root (Entwicklung)
    out.append(pkg / FILENAME)  # Wheel
    if getattr(sys, "frozen", False):
        out.append(Path(getattr(sys, "_MEIPASS", "")) / "visualcut" / FILENAME)
    return out


def global_path() -> Path:
    """Die globale events.yaml (erste vorhandene), sonst der bevorzugte Ort für eine neue."""
    cands = _candidates()
    return next((p for p in cands if p.exists()), cands[0])


def project_path(cache: ProjectCache) -> Path:
    return cache.path(FILENAME)


def parse(text: str) -> EventCatalog:
    data = yaml.safe_load(text) or {}
    return EventCatalog.model_validate(data)


def load(cache: ProjectCache | None = None) -> EventCatalog:
    """Projekt-Datei vor globaler Datei. Fehlt beides, ist der Katalog leer."""
    if cache is not None and project_path(cache).exists():
        return parse(project_path(cache).read_text(encoding="utf-8"))
    p = global_path()
    if not p.exists():
        return EventCatalog()
    return parse(p.read_text(encoding="utf-8"))


def dump(catalog: EventCatalog) -> str:
    data = catalog.model_dump(mode="json")
    # Standardwerte pro Eintrag weglassen, damit die Datei lesbar bleibt
    defaults = {"prompt": "", "audio_prompt": "", "kinetics": [], "background": False, "motion": False}
    for d in data["events"]:
        for k, v in defaults.items():
            if d.get(k) == v:
                d.pop(k)
    header = "# VisualCut Stufe 1b: erkennbare Ereignisse. Felder siehe AGENTS.md (Stufe 1b).\n"
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def save(catalog: EventCatalog, path: Path | None = None) -> Path:
    target = path or global_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump(catalog), encoding="utf-8")
    return target


def detection_hash(catalog: EventCatalog) -> str:
    """Nur die Felder, die die Modelle beeinflussen. Label und Wirkung ändern nur die Fusion."""
    h = hashlib.sha1()
    for d in sorted(catalog.events, key=lambda d: d.type):
        h.update(f"{d.type}|{d.prompt}|{d.audio_prompt}|{','.join(d.kinetics)}|{d.background}\n".encode())
    return h.hexdigest()[:16]
