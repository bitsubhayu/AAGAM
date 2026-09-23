import React from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { useUIStore, VARIABLES } from "@/store/uiStore";
import { useWeightsMap } from "@/api/useMap";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
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

  return (
    <div className="relative w-full h-[450px] bg-surface border border-[rgba(26,23,18,0.10)] rounded-lg overflow-hidden">
      {/* Overlay Header */}
      <div className="absolute top-3 left-3 z-[1000] bg-surface/90 backdrop-blur-xs border border-[rgba(26,23,18,0.10)] rounded-md px-3 py-2 text-xs shadow-md">
        <div className="font-semibold text-text-primary flex items-center gap-1.5">
          <Sliders className="w-3.5 h-3.5 text-brand-blue" />
          <span>Dominant Model Grid</span>
          <span className="text-[10px] text-brand-blue font-mono">D+{selectedLeadDays}</span>
        </div>
        <div className="text-[11px] text-text-muted mt-0.5">
          Variable: <span className="text-text-secondary">{varMeta.label}</span> · Season:{" "}
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
        <TileLayer
          attribution={
            import.meta.env.VITE_MAPTILER_KEY && import.meta.env.VITE_MAPTILER_KEY !== "your-maptiler-key"
              ? '&copy; <a href="https://www.maptiler.com/">MapTiler</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          }
          url={
            import.meta.env.VITE_MAPTILER_KEY && import.meta.env.VITE_MAPTILER_KEY !== "your-maptiler-key"
              ? `https://api.maptiler.com/maps/dataviz-light/{z}/{x}/{y}.png?key=${import.meta.env.VITE_MAPTILER_KEY}`
              : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          }
        />

        {mapData.locations.map((loc) => {
          const color = getModelColor(loc.dominant_model);
          return (
            <CircleMarker
              key={loc.slug}
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
                    <span className="font-bold text-text-primary">{loc.name}</span>
                    <Badge variant="outline">{loc.region}</Badge>
                  </div>

                  <div className="mb-2">
                    <span className="text-text-muted text-[11px]">Dominant Model:</span>
                    <div className="mt-0.5">
                      <Badge
                        variant={
                          loc.dominant_model === "aifs"
                            ? "aifs"
                            : loc.dominant_model === "ecmwf_ifs"
                            ? "ifs"
                            : loc.dominant_model === "icon"
                            ? "icon"
                            : "gfs"
                        }
                      >
                        {loc.dominant_model?.toUpperCase()}
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
                          {((w as number) * 100).toFixed(1)}%
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
  );
};
