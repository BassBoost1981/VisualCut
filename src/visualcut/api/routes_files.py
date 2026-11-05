"""Proxy-Video und WAV aus dem Cache als Datei streamen (Range-Requests für den Player)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .routes_projects import get_analysis_or_404

router = APIRouter(prefix="/projects/{content_hash}/files", tags=["files"])

KINDS = {"proxy": ("proxy_path", "video/mp4"), "audio": ("audio_path", "audio/wav")}


@router.get("/{kind}")
def get_file(content_hash: str, kind: str) -> FileResponse:
    if kind not in KINDS:
        raise HTTPException(404, f"Unbekannte Datei {kind}, erlaubt: {', '.join(KINDS)}")
    attr, media_type = KINDS[kind]
    p = getattr(get_analysis_or_404(content_hash).media, attr)
    if not p or not Path(p).is_file():
        raise HTTPException(404, f"{kind} liegt nicht im Cache")
    return FileResponse(p, media_type=media_type)
