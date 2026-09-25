import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { SkillQueryResponse } from "./types";

interface UseSkillParams {
  scope?: "live" | "held_out";
  groupBy?: string;
  variable?: string;
  windowDays?: number;
  region?: string;
  season?: string;
}

export function useSkill(params: UseSkillParams = {}) {
  const queryParams = new URLSearchParams();
  queryParams.set("scope", params.scope || "live");
  if (params.groupBy) queryParams.set("group_by", params.groupBy);
  if (params.variable) queryParams.set("variable", params.variable);
  if (params.windowDays) queryParams.set("window_days", params.windowDays.toString());
  queryParams.set("region", params.region || "ALL");
  queryParams.set("season", params.season || "ALL");

  const qs = queryParams.toString();
  const endpoint = `/skill${qs ? `?${qs}` : ""}`;

  return useQuery<SkillQueryResponse>({
    queryKey: ["skill", params],
    queryFn: () => apiFetch<SkillQueryResponse>(endpoint),
    staleTime: 5 * 60 * 1000,
    retry: 2,
  });
}
