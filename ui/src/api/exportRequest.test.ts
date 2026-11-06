import { afterEach, describe, expect, it, vi } from "vitest";
import { startExport } from "./exportRequest";

function mockFetch() {
  const fn = vi.fn(async () => ({ ok: true, status: 200, statusText: "OK", json: async () => ({ path: "x" }) }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

const sent = (fetch: ReturnType<typeof mockFetch>) => {
  const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
  return { url, body: JSON.parse(init.body as string) };
};

afterEach(() => vi.unstubAllGlobals());

describe("startExport", () => {
  it("Vorschau-Render aus dem Original setzt original: true", async () => {
    const fetch = mockFetch();
    await startExport("abc", "preview", "C:\\out.mp4", { openAsCut: false, original: true });
    expect(sent(fetch)).toEqual({ url: "/projects/abc/render", body: { out: "C:\\out.mp4", open_as_cut: false, original: true } });
  });

  it("Vorschau-Render vom Proxy setzt original: false", async () => {
    const fetch = mockFetch();
    await startExport("abc", "preview", "o.mp4", { openAsCut: true, original: false });
    expect(sent(fetch).body).toEqual({ out: "o.mp4", open_as_cut: true, original: false });
  });

  it("Timeline-Export schickt kein original", async () => {
    const fetch = mockFetch();
    await startExport("abc", "fcpxml", "o.fcpxml", { openAsCut: false, original: true });
    expect(sent(fetch).body).not.toHaveProperty("original");
  });
});
