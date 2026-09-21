import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { SkillQueryResponse } from "./types";

interface UseSkillParams {
  groupBy?: string;
  variable?: string;
  windowDays?: number;
  region?: string;
  season?: string;
}

export function useSkill(params: UseSkillParams = {}) {
  const queryParams = new URLSearchParams();
  if (params.groupBy) queryParams.set("group_by", params.groupBy);
  if (params.variable) queryParams.set("variable", params.variable);
  if (params.windowDays) queryParams.set("window_days", params.windowDays.toString());
  if (params.region && params.region !== "ALL") queryParams.set("region", params.region);
  if (params.season && params.season !== "all") queryParams.set("season", params.season);

  const qs = queryParams.toString();
  const endpoint = `/skill${qs ? `?${qs}` : ""}`;

  return useQuery<SkillQueryResponse>({
    queryKey: ["skill", params],
    queryFn: () => apiFetch<SkillQueryResponse>(endpoint),
    staleTime: 5 * 60 * 1000,
    retry: 2,
  });
}
