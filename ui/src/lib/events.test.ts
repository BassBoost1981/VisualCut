import { describe, expect, it } from "vitest";
import type { Event } from "../api/types";
import { eventTitle, typeFromPrompt } from "./events";

describe("events", () => {
  it("leitet einen gültigen, eindeutigen Typ aus dem Prompt ab", () => {
    expect(typeFromPrompt("person drinking coffee", new Set())).toBe("drinking_coffee");
    expect(typeFromPrompt("person drinking coffee", new Set(["drinking_coffee"]))).toBe("drinking_coffee_2");
    expect(typeFromPrompt("3 people jumping", new Set())).toMatch(/^[a-z][a-z0-9_]*$/);
  });

  it("beschreibt ein Event für den Tooltip", () => {
    const e: Event = { id: "ev-dancing-11.4", type: "dancing", label: "Tanzen", start: 11.4, end: 188.2, confidence: 0.54,
      sources: ["pose", "xclip"], status: "confirmed", effect: "highlight", description: null };
    expect(eventTitle(e).split("\n")).toEqual(["Tanzen · bestätigt · 0.54", "11,4 bis 188,2 s · Highlight", "Quellen: pose, xclip"]);
  });
});
