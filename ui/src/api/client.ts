/** Typisierter Client für `visualcut serve`. Kernmodelle kommen aus types.ts (generiert), die
 *  API-Hüllen (ProjectSummary, JobInfo, …) sind hier nachgebildet, weil sie nicht im Schema stehen. */
import type { Analysis, Cut, CutStatus, Decisions, EventCatalog, ProgressEvent, Stage } from "./types";

export interface ProjectSummary {
  content_hash: string;
  path: string;
  duration: number;
  fps: number;
  stages_done: Stage[];
  cuts: number;
}

export interface AnalyzeRequest {
  path: string;
  stage?: Stage;
  force?: boolean;
  whisper_model?: string;
  language?: string;
}

export interface JobInfo {
  job_id: string;
  content_hash: string;
  status: "running" | "done" | "failed";
  error: string | null;
  events: ProgressEvent[];
}

export interface CutList {
  content_hash: string;
  fps: number;
  count: number;
  cuts: Cut[];
}

export interface ExportRequest {
  format: "fcpxml" | "markers-edl" | "edl" | "otio";
  out?: string | null;
  open_as_cut?: boolean;
}

export interface ExportResult {
  path: string;
  format: string;
  cuts_applied: number;
  markers: number;
  event_markers?: number;
  clips: number;
}

export interface CatalogInfo {
  path: string;
  catalog: EventCatalog;
}

export interface RenderRequest {
  out: string;
  open_as_cut?: boolean;
  original?: boolean;
}

export interface Health {
  status: string;
  version: string;
  ui: boolean;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Basis-URL: im Dev-Modus leer (Vite-Proxy), sonst derselbe Origin wie das Backend. */
export const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* kein JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/health"),
  listProjects: () => request<ProjectSummary[]>("/projects"),
  getProject: (hash: string) => request<Analysis>(`/projects/${hash}`),
  createProject: (path: string) => request<ProjectSummary>("/projects", { method: "POST", ...json({ path }) }),
  analyze: (body: AnalyzeRequest) => request<JobInfo>("/analyze", { method: "POST", ...json(body) }),
  getJob: (jobId: string) => request<JobInfo>(`/jobs/${jobId}`),
  getCuts: (hash: string) => request<CutList>(`/projects/${hash}/cuts`),
  getDecisions: (hash: string) => request<Decisions>(`/projects/${hash}/decisions`),
  putDecision: (hash: string, cutId: string, status: CutStatus, note = "") =>
    request<Decisions>(`/projects/${hash}/decisions/${cutId}`, { method: "PUT", ...json({ status, note }) }),
  exportProject: (hash: string, body: ExportRequest) =>
    request<ExportResult>(`/projects/${hash}/export`, { method: "POST", ...json(body) }),
  renderPreview: (hash: string, body: RenderRequest) =>
    request<{ path: string }>(`/projects/${hash}/render`, { method: "POST", ...json(body) }),
  getCatalog: () => request<CatalogInfo>("/events/catalog"),
  putCatalog: (catalog: EventCatalog) => request<CatalogInfo>("/events/catalog", { method: "PUT", ...json(catalog) }),
};

export const mediaUrl = (hash: string, kind: "proxy" | "audio") => `${BASE}/projects/${hash}/files/${kind}`;

export function progressSocketUrl(jobId: string): string {
  const loc = window.location;
  const proto = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${loc.host}${BASE}/ws/progress/${jobId}`;
}
