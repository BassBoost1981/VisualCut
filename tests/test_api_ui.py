"""Endpunkte, die die Web-UI braucht: Dateien streamen, CORS, statisches Frontend."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from visualcut.cache import ProjectCache


@pytest.fixture
def client(analyzed: ProjectCache, monkeypatch):
    monkeypatch.setenv("VISUALCUT_CACHE", str(analyzed.dir.parent))
    from visualcut.api.app import app

    return TestClient(app)


def test_proxy_and_audio_streamed_with_range(client: TestClient, analyzed: ProjectCache):
    r = client.get(f"/projects/{analyzed.hash}/files/proxy")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.headers.get("accept-ranges") == "bytes"
    r = client.get(f"/projects/{analyzed.hash}/files/audio", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100
    assert r.headers["content-type"].startswith("audio/wav")
    assert client.get(f"/projects/{analyzed.hash}/files/thumbnail").status_code == 404
    assert client.get("/projects/deadbeef/files/proxy").status_code == 404


def test_cors_for_vite_dev_server(client: TestClient):
    r = client.options("/projects", headers={"Origin": "http://localhost:5173",
                                             "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_static_ui_served_when_built(analyzed: ProjectCache, tmp_path: Path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>VisualCut UI</body></html>", encoding="utf-8")
    monkeypatch.setenv("VISUALCUT_UI_DIST", str(dist))
    monkeypatch.setenv("VISUALCUT_CACHE", str(analyzed.dir.parent))
    from visualcut.api.app import create_app

    c = TestClient(create_app())
    assert c.get("/health").json()["ui"] is True
    assert "VisualCut UI" in c.get("/").text
    assert c.get("/projects").status_code == 200  # API-Routen haben Vorrang vor dem Mount


def test_no_static_mount_without_build(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VISUALCUT_UI_DIST", str(tmp_path / "fehlt"))
    from visualcut.api.app import create_app

    c = TestClient(create_app())
    assert c.get("/health").json()["ui"] is False
    assert c.get("/").status_code == 404
