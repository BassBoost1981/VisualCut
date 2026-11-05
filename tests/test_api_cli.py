"""CLI und API liefern dieselben Daten; Exit-Codes; Schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from visualcut.cache import ProjectCache
from visualcut.cli import app as cli_app
from visualcut.schema import MediaInfo, Stage

runner = CliRunner()


@pytest.fixture
def client(analyzed: ProjectCache, monkeypatch):
    monkeypatch.setenv("VISUALCUT_CACHE", str(analyzed.dir.parent))
    from visualcut.api.app import app

    return TestClient(app)


def _video(analyzed: ProjectCache) -> Path:
    return Path(analyzed.load(Stage.ingest, MediaInfo).path)


def test_get_cuts_matches_cli(client: TestClient, analyzed: ProjectCache):
    video = _video(analyzed)
    r = runner.invoke(cli_app, ["cuts", str(video), "--json", "--cache-dir", str(analyzed.dir.parent)])
    assert r.exit_code == 0, r.output
    cli_data = json.loads(r.stdout)
    api = client.get(f"/projects/{analyzed.hash}/cuts")
    assert api.status_code == 200
    assert api.json() == cli_data
    assert cli_data["count"] > 0


def test_projects_listed_and_health(client: TestClient, analyzed: ProjectCache):
    r = client.get("/projects")
    assert r.status_code == 200
    assert analyzed.hash in {p["content_hash"] for p in r.json()}
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/projects/deadbeef/cuts").status_code == 404


def test_decision_via_api_visible_in_cli(client: TestClient, analyzed: ProjectCache):
    video = _video(analyzed)
    cut_id = client.get(f"/projects/{analyzed.hash}/cuts").json()["cuts"][0]["id"]
    r = client.put(f"/projects/{analyzed.hash}/decisions/{cut_id}", json={"status": "accepted", "note": "ok"})
    assert r.status_code == 200
    res = runner.invoke(cli_app, ["cuts", str(video), "--json", "--status", "accepted", "--cache-dir", str(analyzed.dir.parent)])
    assert [c["id"] for c in json.loads(res.stdout)["cuts"]] == [cut_id]
    client.put(f"/projects/{analyzed.hash}/decisions/{cut_id}", json={"status": "open"})


def test_export_via_api(client: TestClient, analyzed: ProjectCache, tmp_path: Path):
    out = tmp_path / "api.fcpxml"
    r = client.post(f"/projects/{analyzed.hash}/export", json={"format": "fcpxml", "out": str(out)})
    assert r.status_code == 200, r.text
    assert out.exists() and r.json()["clips"] >= 1


def test_cli_exit_codes(tmp_path: Path):
    r = runner.invoke(cli_app, ["analyze", str(tmp_path / "fehlt.mp4"), "--json"])
    assert r.exit_code == 2
    assert json.loads(r.stdout)["exit_code"] == 2
    bogus = tmp_path / "kaputt.mp4"
    bogus.write_bytes(b"\x00" * 1024)
    r = runner.invoke(cli_app, ["analyze", str(bogus), "--json", "--cache-dir", str(tmp_path / "c")])
    assert r.exit_code == 3
    r = runner.invoke(cli_app, ["cuts", str(bogus), "--json", "--cache-dir", str(tmp_path / "leer")])
    assert r.exit_code == 3


def test_cli_cache_invalid(analyzed: ProjectCache, tmp_path: Path):
    video = _video(analyzed)
    root = tmp_path / "c"
    bad = ProjectCache(analyzed.hash, root)
    bad.stage_file(Stage.ingest).write_text("{not json", encoding="utf-8")
    r = runner.invoke(cli_app, ["cuts", str(video), "--json", "--cache-dir", str(root)])
    assert r.exit_code == 4


def test_schema_command():
    r = runner.invoke(cli_app, ["schema"])
    assert r.exit_code == 0
    s = json.loads(r.stdout)
    assert {"Analysis", "Decisions", "Cut", "ProgressEvent"} <= set(s["$defs"])


def test_analyze_json_only_on_stdout(analyzed: ProjectCache):
    video = _video(analyzed)
    r = runner.invoke(cli_app, ["analyze", str(video), "--json", "--stage", "technical", "--cache-dir", str(analyzed.dir.parent)])
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)  # ausschließlich JSON auf stdout
    assert data["stages_done"] == ["ingest", "technical"]
