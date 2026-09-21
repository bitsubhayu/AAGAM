import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { MapResponse, WeightsMapResponse } from "./types";

export function useMap(variable: string, leadDays: number) {
  return useQuery<MapResponse>({
    queryKey: ["map", variable, leadDays],
    queryFn: () =>
      apiFetch<MapResponse>(
        `/map?variable=${encodeURIComponent(variable)}&lead_days=${leadDays}`
      ),
    enabled: Boolean(variable && leadDays !== undefined),
    staleTime: 60 * 1000,
    retry: 2,
  });
}

export function useWeightsMap(variable: string, leadDays: number, season: string = "all") {
  return useQuery<WeightsMapResponse>({
    queryKey: ["weights-map", variable, leadDays, season],
    queryFn: () =>
      apiFetch<WeightsMapResponse>(
        `/weights/map?variable=${encodeURIComponent(variable)}&lead_days=${leadDays}&season=${encodeURIComponent(season)}`
      ),
    enabled: Boolean(variable && leadDays !== undefined),
    staleTime: 2 * 60 * 1000,
    retry: 2,
  });
}
