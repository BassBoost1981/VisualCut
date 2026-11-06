"""FastAPI-App. Alle Endpunkte rufen dieselben Kernfunktionen wie das CLI."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .routes_analysis import router as analysis_router
from .routes_cuts import router as cuts_router
from .routes_events import router as events_router
from .routes_export import router as export_router
from .routes_files import router as files_router
from .routes_projects import router as projects_router
from .ws_progress import router as ws_router

# Vite-Dev-Server (ui/, `npm run dev`); im Produktionsmodus kommt die UI vom selben Origin.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def ui_dist() -> Path | None:
    """Gebautes Frontend: $VISUALCUT_UI_DIST oder ui/dist im Repo."""
    env = os.environ.get("VISUALCUT_UI_DIST")
    candidates = [Path(env)] if env else [Path(__file__).resolve().parents[3] / "ui" / "dist"]
    for d in candidates:
        if (d / "index.html").is_file():
            return d
    return None


class UIFiles(StaticFiles):
    """Gebaute UI. index.html nie zwischenspeichern, sonst lädt das Fenster (WebView2-Cache in data/webview)
    nach einem Update die alte Oberfläche; die Assets haben pro Build eindeutige Namen."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.media_type == "text/html" or path in ("", ".", "index.html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="VisualCut", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    app.include_router(projects_router)
    app.include_router(analysis_router)
    app.include_router(cuts_router)
    app.include_router(export_router)
    app.include_router(events_router)
    app.include_router(files_router)
    app.include_router(ws_router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "ui": ui_dist() is not None}

    dist = ui_dist()
    if dist is not None:  # zuletzt, damit die API-Routen Vorrang haben
        app.mount("/", UIFiles(directory=dist, html=True), name="ui")
    return app


app = create_app()
