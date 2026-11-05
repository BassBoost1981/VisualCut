import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CutList } from "./client";
import type { CutStatus } from "./types";

export const keys = {
  health: ["health"] as const,
  projects: ["projects"] as const,
  project: (hash: string) => ["project", hash] as const,
  cuts: (hash: string) => ["cuts", hash] as const,
  job: (id: string) => ["job", id] as const,
};

export const useHealth = () => useQuery({ queryKey: keys.health, queryFn: api.health, retry: false, refetchInterval: 15000 });
export const useProjects = () => useQuery({ queryKey: keys.projects, queryFn: api.listProjects });
export const useProject = (hash: string) => useQuery({ queryKey: keys.project(hash), queryFn: () => api.getProject(hash) });
export const useCuts = (hash: string) => useQuery({ queryKey: keys.cuts(hash), queryFn: () => api.getCuts(hash) });

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
