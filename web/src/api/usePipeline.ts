import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { ModelActivationResponse, PipelineStatusResponse } from "./types";

export function usePipelineStatus() {
  return useQuery<PipelineStatusResponse>({
    queryKey: ["pipeline-status"],
    queryFn: () => apiFetch<PipelineStatusResponse>("/pipeline/status"),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
    retry: 2,
  });
}

export function useActivateModel() {
  const queryClient = useQueryClient();

  return useMutation<ModelActivationResponse, Error, number>({
    mutationFn: (modelId: number) =>
      apiFetch<ModelActivationResponse>(`/models/${modelId}/activate`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pipeline-status"] });
      queryClient.invalidateQueries({ queryKey: ["meta"] });
      queryClient.invalidateQueries({ queryKey: ["weights"] });
      queryClient.invalidateQueries({ queryKey: ["weights-map"] });
      queryClient.invalidateQueries({ queryKey: ["forecast"] });
    },
  });
}
