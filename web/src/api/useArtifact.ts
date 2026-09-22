import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { ArtifactResponse } from "./types";

export const useArtifact = (
  artifactId: string | null | undefined,
  offset: number = 0,
  limit: number = 50
) => {
  return useQuery<ArtifactResponse>({
    queryKey: ["artifact", artifactId, offset, limit],
    queryFn: async () => {
      if (!artifactId) {
        throw new Error("Artifact ID is required");
      }
      return apiFetch<ArtifactResponse>(
        `/artifacts/${encodeURIComponent(artifactId)}?offset=${offset}&limit=${limit}`
      );
    },
    enabled: !!artifactId,
    staleTime: 5 * 60 * 1000,
  });
};
