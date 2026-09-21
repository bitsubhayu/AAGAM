import React from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { useUIStore, VARIABLES } from "@/store/uiStore";
import { useMap } from "@/api/useMap";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ArrowRight, CloudRain, AlertTriangle } from "lucide-react";

export const IndiaForecastMap: React.FC = () => {
  const {
    selectedVariable,
    selectedLeadDays,
    setSelectedLocationSlug,
    setActiveTab,
  } = useUIStore();

  const { data: mapData, isLoading, error } = useMap(selectedVariable, selectedLeadDays);
  const varMeta = VARIABLES[selectedVariable];

  // Helper to determine circle color and hazard severity
  const getHazardStyle = (val: number = 0) => {
    if (selectedVariable === "rain_mm") {
      if (val >= 204.5) return { color: "#f85149", fill: "#f85149", severity: "Extremely Heavy" };
      if (val >= 115.6) return { color: "#db6d28", fill: "#db6d28", severity: "Very Heavy" };
      if (val >= 64.5) return { color: "#d29922", fill: "#d29922", severity: "Heavy Rain (Alert)" };
      if (val >= 15.6) return { color: "#388bfd", fill: "#388bfd", severity: "Moderate Rain" };
      return { color: "#2ea043", fill: "#2ea043", severity: "Light / Normal" };
    }
    if (selectedVariable === "tmax_c") {
      if (val >= 45.0) return { color: "#f85149", fill: "#f85149", severity: "Severe Heatwave" };
      if (val >= 40.0) return { color: "#db6d28", fill: "#db6d28", severity: "Heatwave Watch" };
      return { color: "#3fb950", fill: "#3fb950", severity: "Normal Range" };
    }
    // wind_max_kmh
    if (val >= 75.0) return { color: "#f85149", fill: "#f85149", severity: "Strong Gale" };
    if (val >= 62.0) return { color: "#d29922", fill: "#d29922", severity: "Gale Wind" };
    return { color: "#58a6ff", fill: "#58a6ff", severity: "Moderate Wind" };
  };

  if (isLoading) {
    return (
      <div className="w-full h-[450px] bg-[#161b22] border border-border rounded-lg flex items-center justify-center p-6">
        <div className="space-y-3 w-full max-w-md text-center">
          <Skeleton className="h-64 w-full" />
          <p className="text-xs text-text-muted">Loading 40-station spatial grid...</p>
        </div>
      </div>
    );
  }

  if (error || !mapData) {
    return (
      <div className="w-full h-[450px] bg-[#161b22] border border-border rounded-lg flex flex-col items-center justify-center p-6 text-center">
        <AlertTriangle className="w-8 h-8 text-hazard-advisory mb-2" />
        <p className="text-xs font-semibold text-text-primary">Unable to load spatial forecast</p>
        <p className="text-[11px] text-text-muted mt-1 max-w-sm">
          {error?.message || "Verify API server status and network connectivity."}
        </p>
      </div>
    );
  }

  return (
    <div className="relative w-full h-[480px] bg-[#161b22] border border-border rounded-lg overflow-hidden">
      {/* Map Header Overlay */}
      <div className="absolute top-3 left-3 z-[1000] bg-surface/90 backdrop-blur-xs border border-border rounded-md px-3 py-2 text-xs shadow-md">
        <div className="font-semibold text-text-primary flex items-center gap-1.5">
          <CloudRain className="w-3.5 h-3.5 text-brand-blue" />
          <span>{varMeta.label}</span>
          <span className="text-[10px] text-brand-blue font-mono">D+{selectedLeadDays}</span>
        </div>
        <div className="text-[11px] text-text-muted mt-0.5">
          Valid: <span className="font-mono text-text-secondary">{mapData.valid_date}</span> ({mapData.unit})
        </div>
      </div>

      {/* Map Container */}
      <MapContainer
        center={[22.5, 82.5]}
        zoom={4.6}
        minZoom={4}
        maxZoom={8}
        scrollWheelZoom={false}
        className="w-full h-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a> &copy; OpenStreetMap'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />

        {mapData.points.map((pt) => {
          const style = getHazardStyle(pt.blended_value);
          const val = pt.blended_value !== undefined ? pt.blended_value.toFixed(1) : "N/A";

          return (
            <CircleMarker
              key={pt.slug}
              center={[pt.lat, pt.lon]}
              radius={8}
              pathOptions={{
                color: style.color,
                fillColor: style.fill,
                fillOpacity: 0.8,
                weight: 2,
              }}
            >
              <Popup>
                <div className="p-1 min-w-[200px] text-xs font-sans">
                  <div className="flex items-center justify-between border-b border-border/80 pb-1.5 mb-1.5">
                    <span className="font-bold text-text-primary">{pt.name}</span>
                    <Badge variant="outline">{pt.region}</Badge>
                  </div>

                  <div className="space-y-1 my-2">
                    <div className="flex justify-between items-center">
                      <span className="text-text-muted text-[11px]">Blended:</span>
                      <span className="font-mono font-bold text-text-primary text-sm">
                        {val} {varMeta.shortUnit}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-text-muted text-[11px]">Severity:</span>
                      <span className="font-medium text-[11px]" style={{ color: style.color }}>
                        {style.severity}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-text-muted text-[11px]">Dominant Model:</span>
                      <Badge
                        variant={
                          pt.dominant_model === "aifs"
                            ? "aifs"
                            : pt.dominant_model === "ecmwf_ifs"
                            ? "ifs"
                            : pt.dominant_model === "icon"
                            ? "icon"
                            : "gfs"
                        }
                      >
                        {pt.dominant_model?.toUpperCase() || "BLEND"}
                      </Badge>
                    </div>
                  </div>

                  <Button
                    size="sm"
                    variant="primary"
                    className="w-full mt-2"
                    onClick={() => {
                      setSelectedLocationSlug(pt.slug);
                      setActiveTab("forecast");
                    }}
                  >
                    <span>View Forecast</span>
                    <ArrowRight className="w-3 h-3" />
                  </Button>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>

      {/* Map Legend Footer */}
      <div className="absolute bottom-3 right-3 z-[1000] bg-surface/90 backdrop-blur-xs border border-border rounded-md px-3 py-1.5 text-[11px] shadow-md flex items-center gap-3">
        <span className="text-text-muted text-[10px] uppercase font-semibold">Severity</span>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-hazard-normal inline-block" />
          <span className="text-text-muted text-[10px]">Normal</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-hazard-advisory inline-block" />
          <span className="text-text-muted text-[10px]">Advisory</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-hazard-watch inline-block" />
          <span className="text-text-muted text-[10px]">Watch</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-hazard-alert inline-block" />
          <span className="text-text-muted text-[10px]">Alert</span>
        </div>
      </div>
    </div>
  );
};
