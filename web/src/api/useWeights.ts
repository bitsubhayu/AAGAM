import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { WeightOverrideCreate, WeightOverrideResponse, WeightsResponse } from "./types";

interface UseWeightsParams {
  variable?: string;
  region?: string;
  season?: string;
  leadDays?: number;
}

export function useWeights(params: UseWeightsParams = {}) {
  const queryParams = new URLSearchParams();
  if (params.variable) queryParams.set("variable", params.variable);
  if (params.region && params.region !== "ALL") queryParams.set("region", params.region);
  if (params.season && params.season !== "all") queryParams.set("season", params.season);
  if (params.leadDays !== undefined) queryParams.set("lead_days", params.leadDays.toString());

  const qs = queryParams.toString();
  const endpoint = `/weights${qs ? `?${qs}` : ""}`;

  return useQuery<WeightsResponse>({
    queryKey: ["weights", params],
    queryFn: () => apiFetch<WeightsResponse>(endpoint),
    staleTime: 2 * 60 * 1000,
    retry: 2,
  });
}

export function useWeightOverrides() {
  return useQuery<WeightOverrideResponse[]>({
    queryKey: ["weight-overrides"],
    queryFn: () => apiFetch<WeightOverrideResponse[]>("/weights/overrides"),
    staleTime: 60 * 1000,
    retry: 2,
  });
}

export function useCreateWeightOverride() {
  const queryClient = useQueryClient();

  return useMutation<WeightOverrideResponse, Error, WeightOverrideCreate>({
    mutationFn: (override) =>
      apiFetch<WeightOverrideResponse>("/weights/override", {
        method: "POST",
        body: JSON.stringify(override),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["weight-overrides"] });
      queryClient.invalidateQueries({ queryKey: ["weights"] });
      queryClient.invalidateQueries({ queryKey: ["forecast"] });
    },
  });
}
