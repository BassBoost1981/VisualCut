"""Cuts lesen und Entscheidungen schreiben. Gleiche Daten wie `visualcut cuts --json`."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import decisions as decisions_mod
from ..pipeline import select_cuts
from ..schema import Cut, CutStatus, Decisions
from .routes_projects import get_analysis_or_404, get_cache_or_404

router = APIRouter(prefix="/projects/{content_hash}", tags=["cuts"])


class CutList(BaseModel):
    content_hash: str
    fps: float
    count: int
    cuts: list[Cut]


class DecisionBody(BaseModel):
    status: CutStatus
    note: str = ""


@router.get("/cuts", response_model=CutList)
def get_cuts(
    content_hash: str, min_confidence: float = 0.0, status: CutStatus | None = None,
    reason: list[str] | None = Query(None),
) -> CutList:
    a = get_analysis_or_404(content_hash)
    sel = select_cuts(a.cuts, min_confidence, status, reason)
    return CutList(content_hash=content_hash, fps=a.media.fps, count=len(sel), cuts=sel)


@router.get("/decisions", response_model=Decisions)
def get_decisions(content_hash: str) -> Decisions:
    return decisions_mod.load(get_cache_or_404(content_hash))


@router.put("/decisions/{cut_id}", response_model=Decisions)
def put_decision(content_hash: str, cut_id: str, body: DecisionBody) -> Decisions:
    a = get_analysis_or_404(content_hash)
    if cut_id not in {c.id for c in a.cuts}:
        raise HTTPException(404, f"Cut {cut_id} nicht gefunden")
    return decisions_mod.set_status(get_cache_or_404(content_hash), cut_id, body.status, body.note)


@router.put("/decisions", response_model=Decisions)
def put_decisions(content_hash: str, body: Decisions) -> Decisions:
    """Komplette decisions.json ersetzen (UI-Bulk-Speichern)."""
    cache = get_cache_or_404(content_hash)
    body.content_hash = content_hash
    decisions_mod.save(cache, body)
    return body
