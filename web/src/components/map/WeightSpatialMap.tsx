import React from "react";
import { MapContainer, CircleMarker, Popup } from "react-leaflet";
import { MapTilerVectorBasemap } from "./MapTilerVectorBasemap";
import { useUIStore, VARIABLES } from "@/store/uiStore";
import { useWeightsMap } from "@/api/useMap";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { Sliders } from "lucide-react";

export const WeightSpatialMap: React.FC = () => {
  const { selectedVariable, selectedLeadDays, selectedSeason } = useUIStore();
  const { data: mapData, isLoading, error } = useWeightsMap(
    selectedVariable,
    selectedLeadDays,
    selectedSeason
  );
  const varMeta = VARIABLES[selectedVariable];

  const getModelColor = (model?: string) => {
    switch (model) {
      case "gfs":
        return "#58a6ff";
      case "ecmwf_ifs":
        return "#3fb950";
      case "icon":
        return "#f0883e";
      case "aifs":
        return "#a371f7";
      default:
        return "#388bfd";
    }
  };

  if (isLoading) {
    return (
      <div className="w-full h-[450px] bg-surface border border-[rgba(26,23,18,0.10)] rounded-lg flex items-center justify-center p-6">
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !mapData) {
    return (
      <div className="w-full h-[450px] bg-surface border border-[rgba(26,23,18,0.10)] rounded-lg flex items-center justify-center p-6 text-center text-xs text-text-muted">
        Dominant weight map unavailable.
      </div>
    );
  }

  const validLocations = Array.isArray(mapData.locations)
    ? mapData.locations.filter(
        (loc) => loc && typeof loc.lat === "number" && typeof loc.lon === "number" && !isNaN(loc.lat) && !isNaN(loc.lon)
      )
    : [];

  return (
    <ErrorBoundary
      fallbackTitle="Dominant Station Map Unavailable"
      fallbackMessage="An unexpected error occurred while rendering the spatial map markers."
    >
      <div className="relative w-full h-[450px] bg-surface border border-[rgba(26,23,18,0.10)] rounded-lg overflow-hidden">
        {/* Overlay Header */}
        <div className="absolute top-3 left-3 z-[1000] bg-surface/90 backdrop-blur-xs border border-[rgba(26,23,18,0.10)] rounded-md px-3 py-2 text-xs shadow-md">
          <div className="font-semibold text-text-primary flex items-center gap-1.5">
            <Sliders className="w-3.5 h-3.5 text-brand-blue" />
            <span>Dominant Model Grid</span>
            <span className="text-[10px] text-brand-blue font-mono">D+{selectedLeadDays}</span>
          </div>
          <div className="text-[11px] text-text-muted mt-0.5">
            Variable: <span className="text-text-secondary">{varMeta?.label || selectedVariable}</span> · Season:{" "}
            <span className="capitalize text-text-secondary">{selectedSeason}</span>
          </div>
        </div>

        <MapContainer
          center={[22.5, 82.5]}
          zoom={4.6}
          minZoom={4}
          maxZoom={8}
          scrollWheelZoom={false}
          className="w-full h-full"
        >
          <MapTilerVectorBasemap style="dataviz-light" />

          {validLocations.map((loc, idx) => {
            const color = getModelColor(loc.dominant_model);
            const modelKey = (loc.dominant_model || "").toLowerCase();
            const badgeVariant =
              modelKey === "aifs"
                ? "aifs"
                : modelKey === "ecmwf_ifs"
                ? "ifs"
                : modelKey === "icon"
                ? "icon"
                : "gfs";

            return (
              <CircleMarker
                key={loc.slug || `loc-${idx}`}
                center={[loc.lat, loc.lon]}
                radius={8}
                pathOptions={{
                  color,
                  fillColor: color,
                  fillOpacity: 0.85,
                  weight: 2,
                }}
              >
                <Popup>
                  <div className="p-1 min-w-[210px] text-xs font-sans">
                    <div className="flex items-center justify-between border-b border-[rgba(26,23,18,0.09)] pb-1.5 mb-2">
                      <span className="font-bold text-text-primary">{loc.name || "Station"}</span>
                      <Badge variant="outline">{loc.region || "—"}</Badge>
                    </div>

                    <div className="mb-2">
                      <span className="text-text-muted text-[11px]">Dominant Model:</span>
                      <div className="mt-0.5">
                        <Badge variant={badgeVariant}>
                          {(loc.dominant_model || "EQUAL").toUpperCase()}
                        </Badge>
                      </div>
                    </div>

                    <div className="space-y-1 mt-2 pt-2 border-t border-[rgba(26,23,18,0.07)]">
                      <span className="text-[11px] font-semibold text-text-muted">
                        Weight Distribution:
                      </span>
                      {Object.entries(loc.all_weights || {}).map(([m, w]) => (
                        <div key={m} className="flex justify-between items-center text-[11px]">
                          <span className="uppercase text-text-secondary">{m}</span>
                          <span className="font-mono text-text-primary">
                            {((Number(w) || 0) * 100).toFixed(1)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </Popup>
              </CircleMarker>
            );
          })}
        </MapContainer>

        {/* Model Legend */}
        <div className="absolute bottom-3 right-3 z-[1000] bg-surface/90 backdrop-blur-xs border border-[rgba(26,23,18,0.10)] rounded-md px-3 py-1.5 text-[11px] shadow-md flex items-center gap-2">
          <span className="text-text-muted text-[10px] uppercase font-semibold">Models</span>
          <Badge variant="gfs">GFS</Badge>
          <Badge variant="ifs">ECMWF IFS</Badge>
          <Badge variant="icon">ICON</Badge>
          <Badge variant="aifs">AIFS (AI)</Badge>
        </div>
      </div>
    </ErrorBoundary>
  );
};
