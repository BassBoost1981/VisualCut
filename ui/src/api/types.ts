/* Generiert aus `visualcut schema` (npm run types). Nicht von Hand ändern. */

export type VisualCutSchema =
  Analysis | Decisions | ProgressEvent | Cut | EventCatalog | EventsResult | EventJudgments | ManualCuts;
export type EventStatus = "confirmed" | "candidate";
/**
 * Wirkung eines Event-Typs: Highlight-Kandidat, nur Marker, oder Schnitt-Kandidat.
 */
export type EventEffect = "highlight" | "marker" | "cut";
export type CutReason =
  "filler" | "retake" | "tangent" | "long_pause" | "false_start" | "redundant" | "technical";
export type CutSource = "rule" | "llm" | "manual";
/**
 * offen / angenommen / verworfen
 */
export type CutStatus = "open" | "accepted" | "rejected";
export type Stage = "ingest" | "technical" | "events" | "speech" | "semantic" | "fusion";
/**
 * offen / angenommen / verworfen
 */
export type CutStatus1 = "open" | "accepted" | "rejected";
/**
 * Wirkung eines Event-Typs: Highlight-Kandidat, nur Marker, oder Schnitt-Kandidat.
 */
export type EventEffect1 = "highlight" | "marker" | "cut";

/**
 * Gesamtergebnis, entspricht analysis.json.
 */
export interface Analysis {
  schema_version?: number;
  media: MediaInfo;
  technical?: TechnicalResult | null;
  events?: Event[];
  speech?: SpeechResult | null;
  semantic?: SemanticResult | null;
  cuts?: Cut[];
  /**
   * Highlights mit Sekunden, nach Fusion
   */
  highlights?: Highlight[];
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
 * Ein Ereignis aus Stufe 1b. Sekunden kommen aus der Erkennung, nie von einem LLM.
 */
export interface Event {
  id: string;
  type: string;
  label?: string;
  start: number;
  end: number;
  confidence: number;
  /**
   * pose, clap, xclip, videomae, vision, agent:<name>
   */
  sources?: string[];
  status?: EventStatus;
  effect?: EventEffect;
  description?: string | null;
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
 * Stufe 3: validierte LLM-Ausgabe. Cuts haben source=llm und nur Wort-IDs, keine Sekunden.
 */
export interface SemanticResult {
  chapters?: Chapter[];
  cuts?: Cut[];
  highlights?: Highlight[];
  flags?: Flag[];
  model?: string;
  prompt_version?: string;
  blocks?: number;
  /**
   * Verworfene Einträge (ungültige IDs, Grenzen, Werte)
   */
  rejected?: number;
}
/**
 * Stufe 3: inhaltlicher Abschnitt, nur Wort-IDs.
 */
export interface Chapter {
  title: string;
  start_word: number;
  end_word: number;
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
export interface Highlight {
  start_word: number;
  end_word: number;
  score: number;
  hook?: string;
  /**
   * Sekunden, nach Fusion (an Event-Grenzen ausgerichtet)
   */
  start?: number | null;
  end?: number | null;
  /**
   * Events, an denen der Clip ausgerichtet wurde
   */
  event_ids?: string[];
}
export interface Flag {
  word: number;
  /**
   * z. B. unclear_audio, name_unclear, fact_check
   */
  type: string;
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
/**
 * events.yaml: Liste der erkennbaren Ereignisse, pro Projekt überschreibbar.
 */
export interface EventCatalog {
  version?: number;
  /**
   * Maximale Vision-LLM-Aufrufe pro Video (Ebene C)
   */
  vision_budget?: number;
  events?: EventDefinition[];
}
/**
 * Ein Eintrag in events.yaml.
 */
export interface EventDefinition {
  /**
   * Stabiler Schlüssel, z. B. dancing
   */
  type: string;
  /**
   * Anzeigename
   */
  label: string;
  /**
   * Text für X-CLIP (Zero-Shot), leer = kein Bild-Prompt
   */
  prompt?: string;
  /**
   * Text für CLAP (Zero-Shot), leer = kein Audio-Prompt
   */
  audio_prompt?: string;
  /**
   * Teilstrings von Kinetics-400-Klassen, die VideoMAE als Bestätigung zählt
   */
  kinetics?: string[];
  effect?: EventEffect1;
  /**
   * Nur Vergleichsklasse für X-CLIP/CLAP, erzeugt kein Event
   */
  background?: boolean;
  /**
   * Grenzen aus der Pose-Bewegungsenergie verfeinern
   */
  motion?: boolean;
}
/**
 * Stufe 1b, entspricht events.json.
 */
export interface EventsResult {
  events?: Event[];
  /**
   * Rohdetektionen pro Quelle, vor der Fusion
   */
  detections?: Event[];
  windows?: EventWindow[];
  judgments?: EventJudgment[];
  /**
   * Bewegungsenergie der Hauptperson pro Pose-Sample
   */
  motion?: number[];
  /**
   * Unterkörperenergie pro Pose-Sample, 0 wenn nicht sichtbar
   */
  motion_lower?: number[];
  motion_fps?: number;
  /**
   * Ebene/Modell -> ok oder Grund fürs Überspringen
   */
  layers?: {
    [k: string]: string;
  };
  vision_calls?: number;
  vision_budget?: number;
  /**
   * Hash der erkennungsrelevanten Felder aus events.yaml
   */
  detection_hash?: string;
}
/**
 * Ein unklares Fenster für Ebene C (Vision-LLM oder der steuernde Agent).
 */
export interface EventWindow {
  id: string;
  start: number;
  end: number;
  /**
   * Event-Typen, um die es geht
   */
  candidates?: string[];
  reason?: string;
  /**
   * JPEG-Pfade im Cache, 4 bis 8 Frames
   */
  frames?: string[];
  judged_by?: string | null;
}
/**
 * Urteil zu einem Fenster: ein Typ aus events.yaml oder `none`. Keine Zeitangaben, die kommen aus dem Fenster.
 */
export interface EventJudgment {
  window_id: string;
  type: string;
  confidence: number;
  description?: string;
}
/**
 * Einreichung von Ebene C durch den steuernden Agenten (`visualcut events --judge`).
 */
export interface EventJudgments {
  source?: string;
  judgments?: EventJudgment[];
}
/**
 * manual.json: Cuts, die der Mensch im Transkript markiert hat (source=manual, nur Wort-IDs).
 */
export interface ManualCuts {
  schema_version?: number;
  content_hash: string;
  cuts?: Cut[];
}
