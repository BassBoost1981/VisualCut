# VisualCut Stufe 1b, Ebene C, Prompt v1

Du bekommst 4 bis 8 Einzelbilder aus einem kurzen Videofenster, in zeitlicher Reihenfolge, dazu die Ereignistypen, um die es geht. Die automatische Erkennung war hier unsicher oder widersprüchlich. Entscheide, was im Fenster passiert.

## Regeln

1. Antworte mit genau einem `type` aus der Liste der erlaubten Typen oder mit `none`, wenn keiner davon zutrifft. Erfinde keine Typen.
2. Gib keine Zeitangaben, Sekunden oder Bildnummern aus. Die Zeit des Fensters kennt der Code.
3. `confidence` zwischen 0 und 1: wie sicher bist du, dass der Typ für den größten Teil des Fensters zutrifft. Ist es nur ein kurzer Moment, ist die Konfidenz niedrig.
4. `description`: ein kurzer Satz auf Deutsch, was zu sehen ist („fängt an zu tanzen, bricht lachend ab"). Keine Spekulation über Personen, nur die Handlung.
5. Gestikulieren beim Reden ist kein Tanzen. Tanzen heißt: rhythmische Bewegung des ganzen Körpers.
6. Wenn die Bilder nichts erkennen lassen (schwarz, unscharf, nur Overlay), antworte `none` mit niedriger Konfidenz.

## Ausgabe

JSON nach dem vorgegebenen Schema: `type`, `confidence`, `description`.

## Für den steuernden Agenten (ohne API-Key)

Der Agent, der VisualCut steuert, kann diese Rolle selbst übernehmen: `visualcut events video.mp4 --pending --json` (bzw. MCP `get_events(path)`) liefert die offenen Fenster mit den Pfaden der Einzelbilder. Bilder ansehen, pro Fenster ein Urteil nach den Regeln oben, dann einreichen mit `visualcut events video.mp4 --judge urteile.json --source agent:<name>` (bzw. MCP `judge_events(path, judgments=[...])`). Format: `{"source": "agent:claude-code", "judgments": [{"window_id": "w-3", "type": "dancing", "confidence": 0.8, "description": "..."}]}`.
