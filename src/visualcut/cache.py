"""Cache unter .visualcut/<hash>/ und Fortschrittsmeldungen als JSON-Lines."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .schema import ProgressEvent, Stage

T = TypeVar("T", bound=BaseModel)

ProgressFn = Callable[[ProgressEvent], None]

HASH_CHUNK = 10 * 1024 * 1024


def cache_root() -> Path:
    return Path(os.path.abspath(os.environ.get("VISUALCUT_CACHE", ".visualcut")))


def content_hash(path: Path) -> str:
    """SHA-256 der ersten und letzten 10 MB plus Dateigröße."""
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(HASH_CHUNK))
        if size > HASH_CHUNK:
            f.seek(max(size - HASH_CHUNK, HASH_CHUNK))
            h.update(f.read(HASH_CHUNK))
    return h.hexdigest()


class ProjectCache:
    """Ordner .visualcut/<hash>/ mit einer JSON-Datei pro Stufe."""

    def __init__(self, hash_: str, root: Path | None = None):
        self.hash = hash_
        self.dir = (root or cache_root()) / hash_
        self.dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_video(cls, video: Path, root: Path | None = None) -> ProjectCache:
        return cls(content_hash(video), root)

    def path(self, name: str) -> Path:
        return self.dir / name

    def stage_file(self, stage: Stage) -> Path:
        return self.dir / f"{stage.value}.json"

    def has(self, stage: Stage) -> bool:
        return self.stage_file(stage).exists()

    def load(self, stage: Stage, model: type[T]) -> T:
        return model.model_validate_json(self.stage_file(stage).read_text(encoding="utf-8"))

    def save(self, stage: Stage, obj: BaseModel) -> Path:
        p = self.stage_file(stage)
        p.write_text(obj.model_dump_json(indent=2), encoding="utf-8")
        return p

    def read_json(self, name: str) -> dict | None:
        p = self.path(name)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))


def stderr_progress(ev: ProgressEvent) -> None:
    sys.stderr.write(ev.model_dump_json(exclude_none=True) + "\n")
    sys.stderr.flush()


def emit(
    progress: ProgressFn | None,
    event: str,
    stage: Stage | None = None,
    message: str = "",
    percent: float | None = None,
    **data,
) -> None:
    if progress is None:
        return
    progress(ProgressEvent(event=event, stage=stage, message=message, percent=percent, data=data))
