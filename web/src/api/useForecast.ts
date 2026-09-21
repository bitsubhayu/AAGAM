import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { ForecastResponse } from "./types";

export function useForecast(location: string, variable: string) {
  return useQuery<ForecastResponse>({
    queryKey: ["forecast", location, variable],
    queryFn: () =>
      apiFetch<ForecastResponse>(
        `/forecast?location=${encodeURIComponent(location)}&variable=${encodeURIComponent(variable)}`
      ),
    enabled: Boolean(location && variable),
    staleTime: 60 * 1000, // 1 minute
    retry: 2,
  });
}
