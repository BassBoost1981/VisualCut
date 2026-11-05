"""Desktop-Start: Backend im selben Prozess, UI in einem nativen Fenster (WebView2 über pywebview).

Entry-Point `visualcut-desktop` und Einstieg der gebauten Exe (packaging/visualcut.spec). Im Bundle
(PyInstaller, `sys.frozen`) liegen UI, ffmpeg und Prompts neben dem Programm; Cache und Logs gehen nach
%LOCALAPPDATA%\\VisualCut, weil das Programmverzeichnis schreibgeschützt sein kann.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "VisualCut"
VIDEO_TYPES = ("Videodateien (*.mp4;*.mov;*.mkv;*.mxf;*.avi;*.webm;*.m4v)", "Alle Dateien (*.*)")


def bundle_dir() -> Path | None:
    """Wurzel der entpackten Dateien in der gebauten Exe, sonst None."""
    return Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else None


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def prepare_environment() -> None:
    """Pfade für das Bundle setzen, bevor das Backend importiert wird."""
    root = bundle_dir()
    if root is not None:
        os.environ.setdefault("VISUALCUT_UI_DIST", str(root / "ui"))
        ffbin = root / "ffmpeg"
        if ffbin.is_dir():
            os.environ["PATH"] = str(ffbin) + os.pathsep + os.environ.get("PATH", "")
        os.environ.setdefault("VISUALCUT_CACHE", str(data_dir() / "cache"))
        if (root / "nltk_data").is_dir():
            os.environ.setdefault("NLTK_DATA", str(root / "nltk_data"))
        os.chdir(data_dir())  # relative Pfade (Exporte ohne --out) landen nicht im Programmordner
        # Ohne Konsole sind stdout/stderr None; Fortschritt und Logs in eine Datei schreiben.
        if sys.stdout is None or sys.stderr is None:
            log = open(data_dir() / "visualcut.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            sys.stdout = sys.stdout or log
            sys.stderr = sys.stderr or log


def free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Kein freier Port gefunden")


def start_backend(port: int):
    import uvicorn

    from .api.app import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, name="visualcut-backend", daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
                if r.status == 200:
                    return server, thread
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Backend ist nicht gestartet")


class Bridge:
    """Wird der UI als `window.pywebview.api` angeboten."""

    def __init__(self) -> None:
        self._window = None

    def pick_video(self) -> str | None:
        import webview

        result = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False, file_types=VIDEO_TYPES)
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else str(result)


def main() -> None:
    prepare_environment()
    import webview

    port = free_port()
    server, thread = start_backend(port)
    bridge = Bridge()
    window = webview.create_window(
        APP_NAME, f"http://127.0.0.1:{port}/", js_api=bridge,
        width=1440, height=900, min_size=(1024, 700), background_color="#09090b",
    )
    bridge._window = window
    try:
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(data_dir() / "webview"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
