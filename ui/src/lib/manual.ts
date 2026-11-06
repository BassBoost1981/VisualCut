import type { CutReason, Word } from "../api/types";
import { REASONS } from "./reasons";

/** Gründe für manuelle Cuts: alle außer Pause (ein manueller Cut schneidet Wörter, keine Lücke). */
export const MANUAL_REASONS: CutReason[] = REASONS.filter((r) => r !== "long_pause");
export const DEFAULT_MANUAL_REASON: CutReason = "redundant";

export type WordRange = [number, number];

/** Spanne zwischen zwei Wort-IDs, egal in welcher Richtung markiert wurde. */
export function wordRange(a: number, b: number): WordRange {
  return a <= b ? [a, b] : [b, a];
}

/** Wort-ID am Knoten (Text-Knoten oder Element) aus dem Attribut `data-word-id` des nächsten Vorfahren. */
export function wordIdAt(node: Node | null): number | null {
  const el = node && "closest" in node ? (node as Element) : node?.parentElement;
  const raw = el?.closest("[data-word-id]")?.getAttribute("data-word-id");
  return raw == null ? null : Number(raw);
}

/** Markierte Wörter als Text, für die Vorschau in der Markierungsleiste. */
export function rangeText(words: Word[], range: WordRange, max = 12): string {
  const sel = words.filter((w) => w.id >= range[0] && w.id <= range[1]);
  const text = sel.slice(0, max).map((w) => w.text).join(" ");
  return sel.length > max ? `${text} …` : text;
}
