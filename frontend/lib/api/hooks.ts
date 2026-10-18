"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { api, type NutritionPatch } from "./client";
import { TERMINAL, type Scan } from "./schemas";

export const keys = {
  scan: (id: string) => ["scan", id] as const,
  history: (q: string) => ["history", q] as const,
  methodology: ["methodology"] as const,
  me: ["me"] as const,
};

/** Polls every 1.5 s until the scan reaches a state the user must act on or a terminal state. */
export function useScan(id: string) {
  return useQuery({
    queryKey: keys.scan(id),
    queryFn: () => api.getScan(id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return 1500;
      return TERMINAL.has(status) || status === "NEEDS_REVIEW" ? false : 1500;
    },
    retry: (count, error) => count < 3 && !(error as { status?: number }).status,
  });
}

export function useHistory(q: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: keys.history(q),
    queryFn: ({ pageParam }) => api.listScans({ q, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled,
  });
}

export function useMethodology() {
  return useQuery({ queryKey: keys.methodology, queryFn: api.methodology, staleTime: 3600_000 });
}

function setScan(qc: QueryClient, scan: Scan) {
  qc.setQueryData(keys.scan(scan.id), scan);
  void qc.invalidateQueries({ queryKey: ["history"] });
}

export function useCorrectNutrition(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: NutritionPatch) => api.correctNutrition(id, patch),
    onSuccess: (scan) => setScan(qc, scan),
  });
}

export function useConfirmScan(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.confirmScan(id),
    onSuccess: (scan) => setScan(qc, scan),
  });
}

export function useDeleteScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteScan(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["history"] }),
  });
}
