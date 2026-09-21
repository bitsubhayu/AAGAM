import { useQuery } from "@tanstack/react-query";
import { API_BASE, apiFetch, getAuthToken } from "./client";
import type { HistoryResponse } from "./types";

interface UseHistoryParams {
  location: string;
  variable: string;
  start?: string;
  end?: string;
  kind?: "blended" | "models" | "both";
  limit?: number;
  offset?: number;
}

export function useHistory(params: UseHistoryParams) {
  const queryParams = new URLSearchParams();
  queryParams.set("location", params.location);
  queryParams.set("variable", params.variable);
  if (params.start) queryParams.set("start", params.start);
  if (params.end) queryParams.set("end", params.end);
  if (params.kind) queryParams.set("kind", params.kind);
  if (params.limit) queryParams.set("limit", params.limit.toString());
  if (params.offset) queryParams.set("offset", params.offset.toString());

  const qs = queryParams.toString();
  const endpoint = `/history?${qs}`;

  return useQuery<HistoryResponse>({
    queryKey: ["history", params],
    queryFn: () => apiFetch<HistoryResponse>(endpoint),
    enabled: Boolean(params.location && params.variable),
    staleTime: 60 * 1000,
    retry: 2,
  });
}

export function getExportDownloadUrl(
  dataset: "forecasts" | "alerts" | "weights" | "skill",
  format: "csv" | "json",
  variable?: string,
  location?: string
): string {
  const queryParams = new URLSearchParams();
  queryParams.set("dataset", dataset);
  queryParams.set("format", format);
  if (variable && variable !== "ALL") queryParams.set("variable", variable);
  if (location && location !== "ALL") queryParams.set("location", location);

  return `${API_BASE}/export?${queryParams.toString()}`;
}

export async function downloadExportFile(
  dataset: "forecasts" | "alerts" | "weights" | "skill",
  format: "csv" | "json",
  variable?: string,
  location?: string
) {
  const token = getAuthToken();
  const url = getExportDownloadUrl(dataset, format, variable, location);

  const headers = new Headers();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const res = await fetch(url, { headers });
  if (!res.ok) {
    throw new Error(`Export download failed with status ${res.status}`);
  }

  const blob = await res.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = downloadUrl;
  a.download = `aagam_${dataset}_${new Date().toISOString().slice(0, 10)}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(downloadUrl);
}
