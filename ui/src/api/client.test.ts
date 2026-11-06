import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, mediaUrl } from "./client";
import schema from "./schema.json";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: "x",
    json: async () => body,
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("liest Projekte", async () => {
    const fetch = mockFetch(200, [{ content_hash: "abc", path: "a.mp4", duration: 1, fps: 25, stages_done: [], cuts: 0 }]);
    const projects = await api.listProjects();
    expect(projects[0].content_hash).toBe("abc");
    expect(fetch).toHaveBeenCalledWith("/projects", expect.objectContaining({ headers: expect.anything() }));
  });

  it("schreibt eine Entscheidung per PUT", async () => {
    const fetch = mockFetch(200, { schema_version: 1, content_hash: "abc", items: [] });
    await api.putDecision("abc", "cut-1", "accepted", "ok");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/projects/abc/decisions/cut-1");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ status: "accepted", note: "ok" });
  });

  it("legt manuelle Cuts per POST an und löscht sie per DELETE", async () => {
    const fetch = mockFetch(200, { id: "manual-3-5" });
    await api.addManualCut("abc", { start_word: 3, end_word: 5, reason: "redundant" });
    await api.deleteManualCut("abc", "manual-3-5");
    const [[url1, init1], [url2, init2]] = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(url1).toBe("/projects/abc/manual");
    expect(init1.method).toBe("POST");
    expect(JSON.parse(init1.body as string)).toEqual({ start_word: 3, end_word: 5, reason: "redundant" });
    expect(url2).toBe("/projects/abc/manual/manual-3-5");
    expect(init2.method).toBe("DELETE");
  });

  it("wirft ApiError mit detail", async () => {
    mockFetch(404, { detail: "Projekt fehlt" });
    await expect(api.getCuts("nope")).rejects.toMatchObject(new ApiError(404, "Projekt fehlt"));
  });

  it("baut Medien-URLs", () => {
    expect(mediaUrl("abc", "proxy")).toBe("/projects/abc/files/proxy");
  });

  it("Schema enthält die Kernmodelle, aus denen types.ts entsteht", () => {
    expect(Object.keys(schema.$defs)).toEqual(
      expect.arrayContaining(["Analysis", "Cut", "Decisions", "ProgressEvent", "Word"]),
    );
  });
});
