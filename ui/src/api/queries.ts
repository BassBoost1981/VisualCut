import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CutList, type ManualCutRequest } from "./client";
import type { CutStatus, EventCatalog } from "./types";

export const keys = {
  health: ["health"] as const,
  projects: ["projects"] as const,
  project: (hash: string) => ["project", hash] as const,
  cuts: (hash: string) => ["cuts", hash] as const,
  job: (id: string) => ["job", id] as const,
  catalog: ["catalog"] as const,
};

export const useHealth = () => useQuery({ queryKey: keys.health, queryFn: api.health, retry: false, refetchInterval: 15000 });
export const useProjects = () => useQuery({ queryKey: keys.projects, queryFn: api.listProjects });
export const useProject = (hash: string) => useQuery({ queryKey: keys.project(hash), queryFn: () => api.getProject(hash) });
export const useCuts = (hash: string) => useQuery({ queryKey: keys.cuts(hash), queryFn: () => api.getCuts(hash) });
export const useCatalog = () => useQuery({ queryKey: keys.catalog, queryFn: api.getCatalog });

/** PUT /events/catalog: schreibt die globale events.yaml. */
export function useSaveCatalog() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (catalog: EventCatalog) => api.putCatalog(catalog),
    onSuccess: (info) => qc.setQueryData(keys.catalog, info),
  });
}

/** PUT /decisions/{cut_id}, optimistisch in der Cut-Liste gespiegelt, danach neu geladen. */
export function useDecide(hash: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ cutId, status, note }: { cutId: string; status: CutStatus; note?: string }) =>
      api.putDecision(hash, cutId, status, note ?? ""),
    onMutate: async ({ cutId, status }) => {
      await qc.cancelQueries({ queryKey: keys.cuts(hash) });
      const prev = qc.getQueryData<CutList>(keys.cuts(hash));
      if (prev) {
        qc.setQueryData<CutList>(keys.cuts(hash), {
          ...prev,
          cuts: prev.cuts.map((c) => (c.id === cutId ? { ...c, status } : c)),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(keys.cuts(hash), ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.cuts(hash) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

/** Manuelle Cuts anlegen und löschen. Das Backend rechnet die Fusion neu, darum Cuts und Projekt neu laden. */
function useManualMutation<V, R>(hash: string, fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: keys.cuts(hash) });
      void qc.invalidateQueries({ queryKey: keys.project(hash) });
      void qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export const useMarkCut = (hash: string) =>
  useManualMutation(hash, (body: ManualCutRequest) => api.addManualCut(hash, body));

export const useUnmarkCut = (hash: string) =>
  useManualMutation(hash, (cutId: string) => api.deleteManualCut(hash, cutId));
