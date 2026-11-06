import { api } from "./client";

export type Format = "fcpxml" | "markers-edl" | "otio" | "edl" | "preview";

/** Startet Export oder Vorschau-Render. `original` gilt nur für den Vorschau-Render. */
export function startExport(hash: string, format: Format, out: string, opts: { openAsCut: boolean; original: boolean }) {
  if (format === "preview") return api.renderPreview(hash, { out, open_as_cut: opts.openAsCut, original: opts.original });
  return api.exportProject(hash, { format, out, open_as_cut: opts.openAsCut });
}
