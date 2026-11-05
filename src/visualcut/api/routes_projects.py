"""Projekte = Einträge unter .visualcut/<hash>/."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..cache import ProjectCache, cache_root
from ..pipeline import load_analysis
from ..schema import Analysis, MediaInfo, Stage

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectSummary(BaseModel):
    content_hash: str
    path: str
    duration: float
    fps: float
    stages_done: list[Stage]
    cuts: int


class ProjectCreate(BaseModel):
    path: str


def _summary(cache: ProjectCache) -> ProjectSummary | None:
    a = load_analysis(cache)
    if a is None:
        return None
    return ProjectSummary(content_hash=cache.hash, path=a.media.path, duration=a.media.duration, fps=a.media.fps,
                          stages_done=a.stages_done, cuts=len(a.cuts))


def get_cache_or_404(content_hash: str) -> ProjectCache:
    d = cache_root() / content_hash
    if not d.is_dir():
        raise HTTPException(404, f"Projekt {content_hash} nicht gefunden")
    return ProjectCache(content_hash)


def get_analysis_or_404(content_hash: str) -> Analysis:
    a = load_analysis(get_cache_or_404(content_hash))
    if a is None:
        raise HTTPException(404, f"Projekt {content_hash} hat noch keine Analyse")
    return a


@router.get("", response_model=list[ProjectSummary])
def list_projects() -> list[ProjectSummary]:
    root = cache_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "ingest.json").exists():
            s = _summary(ProjectCache(d.name))
            if s:
                out.append(s)
    return out


@router.post("", response_model=ProjectSummary, status_code=201)
def create_project(body: ProjectCreate) -> ProjectSummary:
    """Projekt per Pfad registrieren (nur Hash und Metadaten, keine Analyse)."""
    from ..ingest import ingest

    video = Path(body.path)
    if not video.is_file():
        raise HTTPException(422, f"Datei nicht gefunden: {video}")
    cache = ProjectCache.for_video(video)
    ingest(video, cache)
    return _summary(cache)  # type: ignore[return-value]


@router.get("/{content_hash}", response_model=Analysis)
def get_project(content_hash: str) -> Analysis:
    return get_analysis_or_404(content_hash)


@router.get("/{content_hash}/media", response_model=MediaInfo)
def get_media(content_hash: str) -> MediaInfo:
    return get_analysis_or_404(content_hash).media
