import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type {
  AlertAckResponse,
  AlertEventAckResponse,
  AlertEventDetailResponse,
  AlertListResponse,
  AlertCancelResponse,
  AlertEventCancelResponse,
} from "./types";

export interface UseAlertsParams {
  window?: "upcoming_2d" | "upcoming_3d" | "upcoming_7d" | "past_24h" | "past_7d" | string;
  status?: string;
  hazard?: string;
  region?: string;
  severity?: string;
  minSeverity?: string;
  search?: string;
  maxLeadDays?: number;
  limit?: number;
  offset?: number;
}

export function useAlerts(params: UseAlertsParams = {}) {
  const queryParams = new URLSearchParams();
  if (params.window) queryParams.set("window", params.window);
  if (params.status) queryParams.set("status", params.status);
  if (params.hazard && params.hazard !== "ALL") queryParams.set("hazard", params.hazard);
  if (params.region && params.region !== "ALL") queryParams.set("region", params.region);
  if (params.severity && params.severity !== "ALL") queryParams.set("severity", params.severity);
  if (params.minSeverity && params.minSeverity !== "ALL") queryParams.set("min_severity", params.minSeverity);
  if (params.search && params.search.trim()) queryParams.set("search", params.search.trim());
  if (params.maxLeadDays !== undefined) queryParams.set("max_lead_days", params.maxLeadDays.toString());
  if (params.limit !== undefined) queryParams.set("limit", params.limit.toString());
  if (params.offset !== undefined) queryParams.set("offset", params.offset.toString());

  const qs = queryParams.toString();
  const endpoint = `/alerts${qs ? `?${qs}` : ""}`;

  return useQuery<AlertListResponse>({
    queryKey: ["alerts", params],
    queryFn: () => apiFetch<AlertListResponse>(endpoint),
    staleTime: 30 * 1000, // 30 seconds
    retry: 2,
  });
}

export function useAlertEvent(eventId?: number | null) {
  return useQuery<AlertEventDetailResponse>({
    queryKey: ["alert-event", eventId],
    queryFn: () => apiFetch<AlertEventDetailResponse>(`/alerts/events/${eventId}`),
    enabled: typeof eventId === "number" && eventId > 0,
    staleTime: 30 * 1000,
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
      queryClient.invalidateQueries({ queryKey: ["alert-event"] });
    },
  });
}

export function useAcknowledgeAlertEvent() {
  const queryClient = useQueryClient();

  return useMutation<AlertEventAckResponse, Error, number>({
    mutationFn: (eventId: number) =>
      apiFetch<AlertEventAckResponse>(`/alerts/events/${eventId}/ack`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["alert-event"] });
    },
  });
}

export function useCancelAlert() {
  const queryClient = useQueryClient();

  return useMutation<AlertCancelResponse, Error, number>({
    mutationFn: (alertId: number) =>
      apiFetch<AlertCancelResponse>(`/alerts/${alertId}/cancel`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["alert-event"] });
    },
  });
}

export function useCancelAlertEvent() {
  const queryClient = useQueryClient();

  return useMutation<AlertEventCancelResponse, Error, number>({
    mutationFn: (eventId: number) =>
      apiFetch<AlertEventCancelResponse>(`/alerts/events/${eventId}/cancel`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
      queryClient.invalidateQueries({ queryKey: ["alert-event"] });
    },
  });
}

