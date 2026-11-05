"""FastAPI-App. Alle Endpunkte rufen dieselben Kernfunktionen wie das CLI."""

from __future__ import annotations

from fastapi import FastAPI

from .. import __version__
from .routes_analysis import router as analysis_router
from .routes_cuts import router as cuts_router
from .routes_export import router as export_router
from .routes_projects import router as projects_router
from .ws_progress import router as ws_router

app = FastAPI(title="VisualCut", version=__version__)
app.include_router(projects_router)
app.include_router(analysis_router)
app.include_router(cuts_router)
app.include_router(export_router)
app.include_router(ws_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}
