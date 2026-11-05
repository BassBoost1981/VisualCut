/* Generiert aus `visualcut schema` (npm run types). Nicht von Hand ändern. */

export type VisualCutSchema = Analysis | Decisions | ProgressEvent | Cut;
export type CutReason =
  "filler" | "retake" | "tangent" | "long_pause" | "false_start" | "redundant" | "technical";
export type CutSource = "rule" | "llm" | "manual";
/**
 * offen / angenommen / verworfen
 */
export type CutStatus = "open" | "accepted" | "rejected";
export type Stage = "ingest" | "technical" | "speech" | "fusion";
/**
 * offen / angenommen / verworfen
 */
export type CutStatus1 = "open" | "accepted" | "rejected";

/**
 * Gesamtergebnis, entspricht analysis.json.
 */
export interface Analysis {
  schema_version?: number;
  media: MediaInfo;
  technical?: TechnicalResult | null;
  speech?: SpeechResult | null;
  cuts?: Cut[];
  stages_done?: Stage[];
}
/**
 * Stufe 0: ffprobe-Metadaten des Originals.
 */
export interface MediaInfo {
  path: string;
  content_hash: string;
  size_bytes: number;
  /**
   * Sekunden
   */
  duration: number;
  /**
   * Nominale Framerate, bei VFR die durchschnittliche
   */
  fps: number;
  variable_framerate?: boolean;
  width: number;
  height: number;
  video_codec?: string | null;
  audio_codec?: string | null;
  audio_channels?: number;
  audio_sample_rate?: number;
  has_audio?: boolean;
  proxy_path?: string | null;
  audio_path?: string | null;
  frame_count?: number;
}
/**
 * Stufe 1: nur Messung, keine Interpretation.
 */
export interface TechnicalResult {
  silences?: SilenceInterval[];
  scenes?: SceneChange[];
  silence_threshold_db?: number;
  silence_min_duration?: number;
}
export interface SilenceInterval {
  start: number;
  end: number;
}
export interface SceneChange {
  /**
   * Erster Frame der neuen Szene
   */
  frame: number;
  /**
   * Sekunden
   */
  time: number;
  /**
   * content, adaptive oder content+adaptive
   */
  detector: string;
  score?: number | null;
}
/**
 * Stufe 2: Transkript als Wortliste plus Modellinfo.
 */
export interface SpeechResult {
  words?: Word[];
  language?: string;
  model?: string;
  device?: string;
  aligned?: boolean;
  text?: string;
}
/**
 * Ein Wort aus Stufe 2. `id` ist die stabile Referenz für Cuts und das LLM.
 */
export interface Word {
  id: number;
  text: string;
  start: number;
  end: number;
  speaker?: string | null;
  confidence?: number;
}
/**
 * Ein Schnittvorschlag. Vor der Fusion nur Wort-IDs, danach auch Sekunden und Frames.
 */
export interface Cut {
  id: string;
  start_word: number;
  end_word: number;
  reason: CutReason;
  confidence: number;
  source?: CutSource;
  note?: string;
  status?: CutStatus;
  /**
   * Sekunden, nach Fusion
   */
  start?: number | null;
  end?: number | null;
  start_frame?: number | null;
  end_frame?: number | null;
  /**
   * confidence < 0.6
   */
  maybe?: boolean;
}
/**
 * decisions.json: Entscheidungen der UI oder eines Agenten, von Export/CLI/MCP gelesen.
 */
export interface Decisions {
  schema_version?: number;
  content_hash: string;
  items?: Decision[];
}
export interface Decision {
  cut_id: string;
  status: CutStatus1;
  note?: string;
}
/**
 * Eine JSON-Line auf stderr bzw. eine WebSocket-Nachricht.
 */
export interface ProgressEvent {
  /**
   * stage_start, progress, stage_done, stage_skipped, error, log
   */
  event: string;
  stage?: Stage | null;
  percent?: number | null;
  message?: string;
  data?: {
    [k: string]: unknown;
  };
}
