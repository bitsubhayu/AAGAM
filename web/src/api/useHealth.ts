import { useQuery } from "@tanstack/react-query";
import { HEALTH_URL } from "./client";
import type { HealthResponse } from "./types";

export function useHealth() {
  return useQuery<HealthResponse>({
    queryKey: ["health"],
    queryFn: async () => {
      const res = await fetch(HEALTH_URL);
      if (!res.ok) {
        throw new Error(`Health check returned HTTP ${res.status}`);
      }
      return (await res.json()) as HealthResponse;
    },
    staleTime: 15 * 1000,
    refetchInterval: 30 * 1000,
    retry: 3,
  });
}
