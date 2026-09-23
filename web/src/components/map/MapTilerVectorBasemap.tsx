import React, { useEffect, useRef } from "react";
import { useMap, TileLayer } from "react-leaflet";
import { MaptilerLayer } from "@maptiler/leaflet-maptilersdk";
import "@maptiler/sdk/dist/maptiler-sdk.css";

interface MapTilerVectorBasemapProps {
  style?: string;
}

/**
 * Official MapTiler Vector Basemap for Leaflet (AAGAM Phase 6 & PRD §6.2).
 *
 * Uses @maptiler/leaflet-maptilersdk MaptilerLayer to render a true vector-tile
 * canvas basemap in Leaflet using the official SDK.
 *
 * When VITE_MAPTILER_KEY is configured:
 *   - Instantiates `new MaptilerLayer({ apiKey, style: "dataviz-light" })`
 *   - No raster tiles or CartoDB layers are used.
 *
 * When VITE_MAPTILER_KEY is unconfigured in development:
 *   - Displays an unambiguous configuration banner indicating vector tiles require a key.
 *   - Provides a neutral, light-mode fallback layer so operational markers remain visible.
 */
export const MapTilerVectorBasemap: React.FC<MapTilerVectorBasemapProps> = ({
  style = "dataviz-light",
}) => {
  const map = useMap();
  const layerRef = useRef<any>(null);
  const maptilerKey = (import.meta.env.VITE_MAPTILER_KEY || "").trim();
  const hasKey = Boolean(maptilerKey && maptilerKey !== "your-maptiler-key");

  useEffect(() => {
    if (!hasKey || !maptilerKey) {
      return;
    }

    try {
      const layer = new MaptilerLayer({
        apiKey: maptilerKey,
        style,
      });
      layer.addTo(map);
      layerRef.current = layer;
    } catch (err) {
      console.warn("[MapTiler] Failed to initialize vector basemap layer:", err);
    }

    return () => {
      if (layerRef.current && map) {
        try {
          map.removeLayer(layerRef.current);
        } catch {
          // ignore cleanup issues
        }
        layerRef.current = null;
      }
    };
  }, [map, hasKey, maptilerKey, style]);

  if (!hasKey) {
    return (
      <>
        {/* Light fallback basemap for local dev when VITE_MAPTILER_KEY is unconfigured */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {/* Clear development configuration indicator */}
        <div className="leaflet-top leaflet-right !mt-12 !mr-3 pointer-events-none z-[1000]">
          <div className="bg-amber-50/95 border border-amber-200 text-amber-800 text-[10px] font-mono px-2.5 py-1 rounded-md shadow-sm flex items-center gap-1.5 backdrop-blur-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
            <span>MapTiler Vector Basemap: Set VITE_MAPTILER_KEY in web/.env</span>
          </div>
        </div>
      </>
    );
  }

  return null;
};
