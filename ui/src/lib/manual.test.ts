import { describe, expect, it } from "vitest";
import type { Word } from "../api/types";
import { DEFAULT_MANUAL_REASON, MANUAL_REASONS, rangeText, wordIdAt, wordRange } from "./manual";

const words: Word[] = ["eins", "zwei", "drei", "vier"].map((text, id) => ({ id, text, start: id, end: id + 0.5 }) as Word);

describe("manuelle Cuts", () => {
  it("ordnet die Spanne unabhängig von der Markierrichtung", () => {
    expect(wordRange(7, 3)).toEqual([3, 7]);
    expect(wordRange(3, 3)).toEqual([3, 3]);
  });

  it("findet die Wort-ID am Textknoten und am Element", () => {
    // nachgebaute DOM-Knoten: Vitest läuft hier ohne DOM
    const span = (id: string | null) => ({ closest: () => (id == null ? null : { getAttribute: () => id }) });
    const text = (parent: unknown) => ({ parentElement: parent }) as unknown as Node;
    expect(wordIdAt(text(span("12")))).toBe(12);
    expect(wordIdAt(span("13") as unknown as Node)).toBe(13);
    expect(wordIdAt(span(null) as unknown as Node)).toBeNull();
    expect(wordIdAt(null)).toBeNull();
  });

  it("zeigt den markierten Text gekürzt", () => {
    expect(rangeText(words, [1, 2])).toBe("zwei drei");
    expect(rangeText(words, [0, 3], 2)).toBe("eins zwei …");
  });

  it("bietet keine Pause als Grund an, Standard ist redundant", () => {
    expect(MANUAL_REASONS).not.toContain("long_pause");
    expect(MANUAL_REASONS).toContain(DEFAULT_MANUAL_REASON);
    expect(DEFAULT_MANUAL_REASON).toBe("redundant");
  });
});
