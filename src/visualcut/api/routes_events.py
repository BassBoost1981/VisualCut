"""Stufe 1b über die API: Events eines Projekts, Urteile für Ebene C, Editor für events.yaml."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import pipeline
from ..events import catalog as catalog_mod
from ..ingest import StageError
from ..schema import EventCatalog, EventJudgments
from .routes_projects import get_analysis_or_404, get_cache_or_404

router = APIRouter(tags=["events"])


class CatalogInfo(BaseModel):
    path: str
    catalog: EventCatalog


@router.get("/events/catalog", response_model=CatalogInfo)
def get_catalog() -> CatalogInfo:
    """Die globale events.yaml (die Projektdatei .visualcut/<hash>/events.yaml hat bei der Analyse Vorrang)."""
    return CatalogInfo(path=str(catalog_mod.global_path()), catalog=catalog_mod.load())


@router.put("/events/catalog", response_model=CatalogInfo)
def put_catalog(body: EventCatalog) -> CatalogInfo:
    """events.yaml schreiben. Neue Prompts wirken bei der nächsten Analyse (Stufe 1b rechnet dann neu),
    Label und Wirkung beim nächsten Laden der Events."""
    path = catalog_mod.save(body)
    return CatalogInfo(path=str(path), catalog=catalog_mod.load())


@router.get("/projects/{content_hash}/events")
def get_events(content_hash: str, pending: bool = False) -> dict:
    """Dasselbe Objekt wie `visualcut events --json` (mit pending=true auch die offenen Fenster)."""
    a = get_analysis_or_404(content_hash)
    cache = get_cache_or_404(content_hash)
    try:
        return pipeline.events_info(cache, a, pending=pending)
    except StageError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/projects/{content_hash}/events/judgments")
def post_judgments(content_hash: str, body: EventJudgments) -> dict:
    a = get_analysis_or_404(content_hash)
    try:
        return pipeline.submit_event_judgments(Path(a.media.path), body)
    except (StageError, FileNotFoundError) as e:
        raise HTTPException(422, str(e)) from e
