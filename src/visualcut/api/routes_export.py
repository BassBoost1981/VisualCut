"""Export über dieselbe Funktion wie `visualcut export`."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import decisions as decisions_mod, export as export_mod
from ..ingest import StageError
from .routes_projects import get_analysis_or_404, get_cache_or_404

router = APIRouter(prefix="/projects/{content_hash}", tags=["export"])


class ExportRequest(BaseModel):
    format: str = "fcpxml"
    out: str | None = None
    open_as_cut: bool = False


class ExportResult(BaseModel):
    path: str
    format: str
    cuts_applied: int
    markers: int
    event_markers: int = 0
    clips: int


@router.post("/export", response_model=ExportResult)
def export(content_hash: str, body: ExportRequest) -> ExportResult:
    if body.format not in export_mod.FORMATS:
        raise HTTPException(422, f"Unbekanntes Format {body.format}")
    a = get_analysis_or_404(content_hash)
    cache = get_cache_or_404(content_hash)
    target = Path(body.out) if body.out else cache.path(f"{Path(a.media.path).stem}.{body.format}")
    tl = export_mod.build_timeline(a.media, a.cuts, include_open=body.open_as_cut, events=a.events)
    export_mod.write(tl, target, body.format)
    to_cut, to_mark = decisions_mod.for_export(a.cuts, body.open_as_cut)
    return ExportResult(path=str(target), format=body.format, cuts_applied=len(to_cut), markers=len(to_mark),
                        event_markers=export_mod.count_event_markers(tl), clips=len(list(tl.tracks[0])))


@router.get("/export/{fmt}")
def download(content_hash: str, fmt: str) -> FileResponse:
    a = get_analysis_or_404(content_hash)
    cache = get_cache_or_404(content_hash)
    p = cache.path(f"{Path(a.media.path).stem}.{fmt}")
    if not p.exists():
        raise HTTPException(404, "Noch nicht exportiert")
    return FileResponse(p, filename=p.name)


class RenderRequest(BaseModel):
    out: str
    open_as_cut: bool = False
    original: bool = False


@router.post("/render")
def render(content_hash: str, body: RenderRequest) -> dict:
    a = get_analysis_or_404(content_hash)
    try:
        p = export_mod.render_preview(a.media, a.cuts, Path(body.out), include_open=body.open_as_cut,
                                      source=a.media.path if body.original else None)
    except (StageError, ValueError) as e:
        raise HTTPException(500, str(e)) from e
    return {"path": str(p)}
