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
