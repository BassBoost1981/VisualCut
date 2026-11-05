import type { CutReason, CutStatus } from "../api/types";

/** Farben der Cut-Gründe, identisch in Timeline, Transkript, Filter und Export (design/mockups/README.md). */
export const REASON_COLOR: Record<CutReason, string> = {
  filler: "#F5A524",
  retake: "#F31260",
  long_pause: "#7EE7FC",
  tangent: "#C4B5FD",
  false_start: "#F31260",
  redundant: "#C4B5FD",
  technical: "#17C964",
};

export const REASON_LABEL: Record<CutReason, string> = {
  filler: "Füllwort",
  retake: "Retake",
  long_pause: "Pause",
  tangent: "Abschweifung",
  false_start: "Fehlstart",
  redundant: "Redundant",
  technical: "Technisch",
};

export const REASONS = Object.keys(REASON_LABEL) as CutReason[];

export const STATUS_LABEL: Record<CutStatus, string> = {
  open: "offen",
  accepted: "angenommen",
  rejected: "verworfen",
};

export const STATUS_COLOR: Record<CutStatus, string> = {
  open: "#F5A524",
  accepted: "#45D483",
  rejected: "#F871A0",
};
