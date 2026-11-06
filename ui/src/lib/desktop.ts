// Brücke zur Desktop-App (visualcut/desktop.py, pywebview). Im normalen Browser gibt es sie nicht.
import { useEffect, useState } from "react";

type PywebviewApi = { pick_video: () => Promise<string | null> };
type PywebviewWindow = Window & { pywebview?: { api: PywebviewApi } };

function bridge(): PywebviewApi | null {
  return (window as PywebviewWindow).pywebview?.api ?? null;
}

/** true, sobald die Desktop-Brücke bereit ist (pywebview meldet sich per Event). */
export function useDesktop(): boolean {
  const [ready, setReady] = useState(() => bridge() !== null);
  useEffect(() => {
    if (ready) return;
    const on = () => setReady(bridge() !== null);
    window.addEventListener("pywebviewready", on);
    return () => window.removeEventListener("pywebviewready", on);
  }, [ready]);
  return ready;
}

/** Nativer Dateidialog, gibt den vollständigen Pfad zurück oder null. */
export async function pickVideo(): Promise<string | null> {
  const api = bridge();
  return api ? api.pick_video() : null;
}

/** Desktop-App: der Python-Drop-Handler meldet den vollen Pfad der abgelegten Datei (desktop.watch_drops). */
export function useDroppedFile(onPath: (path: string) => void): void {
  useEffect(() => {
    const on = (e: Event) => {
      const path = (e as CustomEvent<string>).detail;
      if (path) onPath(path);
    };
    window.addEventListener("visualcut:dropped", on);
    return () => window.removeEventListener("visualcut:dropped", on);
  }, [onPath]);
}

/** Vollständiger Pfad einer abgelegten Datei: pywebview setzt `pywebviewFullPath`, Electron `path`. */
export function droppedPath(file: File): string | null {
  const f = file as File & { pywebviewFullPath?: string; path?: string };
  return f.pywebviewFullPath || f.path || null;
}
