import type { Event, EventEffect } from "../api/types";

/** Event-Farbe aus design/mockups/README.md, wie die Marker im Export (Resolve "Green"). */
export const EVENT_COLOR = "#17C964";

export const EFFECTS: { id: EventEffect; label: string }[] = [
  { id: "highlight", label: "Highlight" },
  { id: "marker", label: "Marker" },
  { id: "cut", label: "Schnitt" },
];

export const EFFECT_LABEL: Record<EventEffect, string> = { highlight: "Highlight", marker: "Marker", cut: "Schnitt" };

const fmt = (t: number) => t.toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function eventTitle(e: Event): string {
  const status = e.status === "confirmed" ? "bestätigt" : "Kandidat";
  const parts = [
    `${e.label || e.type} · ${status} · ${e.confidence.toFixed(2)}`,
    `${fmt(e.start)} bis ${fmt(e.end)} s · ${EFFECT_LABEL[e.effect ?? "marker"]}`,
    `Quellen: ${(e.sources ?? []).join(", ")}`,
  ];
  if (e.description) parts.push(e.description);
  return parts.join("\n");
}

/** Schlüssel aus dem Prompt: "person drinking coffee" -> "drinking_coffee". */
export function typeFromPrompt(prompt: string, taken: Set<string>): string {
  let base = prompt
    .toLowerCase()
    .replace(/^(a |an |the )?person /, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!base || !/^[a-z]/.test(base)) base = `event_${base}`;
  let t = base;
  for (let k = 2; taken.has(t); k++) t = `${base}_${k}`;
  return t;
}
