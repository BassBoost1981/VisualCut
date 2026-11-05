import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Stage } from "../api/types";

/** Das Nötigste: was `POST /analyze` braucht, plus das zuletzt geöffnete Projekt. Liegt im localStorage. */
export interface Settings {
  whisperModel: string;
  language: string;
  stage: Stage;
  lastHash: string | null;
  setWhisperModel: (v: string) => void;
  setLanguage: (v: string) => void;
  setStage: (v: Stage) => void;
  setLastHash: (v: string | null) => void;
}

export const useSettings = create<Settings>()(
  persist(
    (set) => ({
      whisperModel: "large-v3",
      language: "de",
      stage: "fusion",
      lastHash: null,
      setWhisperModel: (whisperModel) => set({ whisperModel }),
      setLanguage: (language) => set({ language }),
      setStage: (stage) => set({ stage }),
      setLastHash: (lastHash) => set({ lastHash }),
    }),
    { name: "visualcut-settings" },
  ),
);

export const WHISPER_MODELS = [
  { id: "large-v3", label: "large-v3 · float16 · beste Qualität" },
  { id: "large-v3-turbo", label: "large-v3-turbo · schnell" },
  { id: "medium", label: "medium · wenig VRAM" },
];

export const LANGUAGES = [
  { id: "de", label: "Deutsch" },
  { id: "en", label: "Englisch" },
];
