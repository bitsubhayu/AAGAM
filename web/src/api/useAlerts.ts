import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { AlertAckResponse, AlertListResponse } from "./types";

interface UseAlertsParams {
  status?: string;
  hazard?: string;
  region?: string;
  minSeverity?: string;
  maxLeadDays?: number;
  limit?: number;
  offset?: number;
}

export function useAlerts(params: UseAlertsParams = {}) {
  const queryParams = new URLSearchParams();
  if (params.status) queryParams.set("status", params.status);
  if (params.hazard && params.hazard !== "ALL") queryParams.set("hazard", params.hazard);
  if (params.region && params.region !== "ALL") queryParams.set("region", params.region);
  if (params.minSeverity && params.minSeverity !== "ALL") queryParams.set("min_severity", params.minSeverity);
  if (params.maxLeadDays) queryParams.set("max_lead_days", params.maxLeadDays.toString());
  if (params.limit) queryParams.set("limit", params.limit.toString());
  if (params.offset) queryParams.set("offset", params.offset.toString());

  const qs = queryParams.toString();
  const endpoint = `/alerts${qs ? `?${qs}` : ""}`;

  return useQuery<AlertListResponse>({
    queryKey: ["alerts", params],
    queryFn: () => apiFetch<AlertListResponse>(endpoint),
    staleTime: 30 * 1000, // 30 seconds
    retry: 2,
  });
}

export function useAcknowledgeAlert() {
  const queryClient = useQueryClient();

  return useMutation<AlertAckResponse, Error, number>({
    mutationFn: (alertId: number) =>
      apiFetch<AlertAckResponse>(`/alerts/${alertId}/ack`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
}
