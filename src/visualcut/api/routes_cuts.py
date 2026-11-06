"""Cuts lesen und Entscheidungen schreiben. Gleiche Daten wie `visualcut cuts --json`."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import decisions as decisions_mod
from .. import manual as manual_mod
from ..pipeline import mark, select_cuts, unmark
from ..schema import Cut, CutReason, CutStatus, Decisions, ManualCuts
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


class ManualBody(BaseModel):
    start_word: int
    end_word: int
    reason: CutReason = CutReason.redundant
    note: str = ""


@router.get("/manual", response_model=ManualCuts)
def get_manual(content_hash: str) -> ManualCuts:
    return manual_mod.load(get_cache_or_404(content_hash))


@router.post("/manual", response_model=Cut)
def post_manual(content_hash: str, body: ManualBody) -> Cut:
    """Wortspanne als manuellen Cut speichern und die Fusion neu rechnen (wie `visualcut mark`)."""
    get_analysis_or_404(content_hash)
    try:
        cut, _ = mark(get_cache_or_404(content_hash), body.start_word, body.end_word, body.reason, body.note)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return cut


@router.delete("/manual/{cut_id}", response_model=ManualCuts)
def delete_manual(content_hash: str, cut_id: str) -> ManualCuts:
    cache = get_cache_or_404(content_hash)
    try:
        unmark(cache, cut_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return manual_mod.load(cache)


@router.put("/decisions", response_model=Decisions)
def put_decisions(content_hash: str, body: Decisions) -> Decisions:
    """Komplette decisions.json ersetzen (UI-Bulk-Speichern)."""
    cache = get_cache_or_404(content_hash)
    body.content_hash = content_hash
    decisions_mod.save(cache, body)
    return body
