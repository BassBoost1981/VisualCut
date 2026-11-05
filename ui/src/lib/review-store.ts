import { create } from "zustand";
import type { CutReason } from "../api/types";

/** UI-Zustand des Review-Screens: Auswahl, Filter, Zoom, Mitlauf. Serverdaten liegen in TanStack Query. */
interface ReviewState {
  selectedCutId: string | null;
  reasonFilter: CutReason | null;
  onlyOpen: boolean;
  onlyMaybe: boolean;
  follow: boolean;
  pxPerSec: number;
  select: (id: string | null) => void;
  setReasonFilter: (r: CutReason | null) => void;
  setOnlyOpen: (v: boolean) => void;
  setOnlyMaybe: (v: boolean) => void;
  setFollow: (v: boolean) => void;
  setPxPerSec: (v: number) => void;
}

export const useReview = create<ReviewState>((set) => ({
  selectedCutId: null,
  reasonFilter: null,
  onlyOpen: false,
  onlyMaybe: false,
  follow: true,
  pxPerSec: 20,
  select: (selectedCutId) => set({ selectedCutId }),
  setReasonFilter: (reasonFilter) => set({ reasonFilter }),
  setOnlyOpen: (onlyOpen) => set({ onlyOpen }),
  setOnlyMaybe: (onlyMaybe) => set({ onlyMaybe }),
  setFollow: (follow) => set({ follow }),
  setPxPerSec: (pxPerSec) => set({ pxPerSec: Math.min(400, Math.max(2, pxPerSec)) }),
}));
