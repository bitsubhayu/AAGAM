import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { MetaResponse } from "./types";

export function useMeta() {
  return useQuery<MetaResponse>({
    queryKey: ["meta"],
    queryFn: () => apiFetch<MetaResponse>("/meta"),
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: 2,
  });
}
