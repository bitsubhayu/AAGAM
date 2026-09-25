import React, { useEffect, useRef, useState } from "react";
import { useMap, TileLayer } from "react-leaflet";
import { MaptilerLayer } from "@maptiler/leaflet-maptilersdk";
import "@maptiler/sdk/dist/maptiler-sdk.css";

interface MapTilerVectorBasemapProps {
  style?: string;
}

type BasemapStatus = "unconfigured" | "loading" | "ready" | "failed";

/**
 * Official MapTiler Vector Basemap for Leaflet (AAGAM Phase 6 & PRD §6.2)
 * with robust, fault-tolerant raster fallback.
 *
 * Operational rules:
 * 1. When MapTiler key is configured: attempts vector tile load via @maptiler/leaflet-maptilersdk.
 * 2. If vector tiles initialize and load successfully: uses native MapTiler canvas basemap.
 * 3. If MapTiler key is missing, invalid (401/403), network fails, or watchdog times out:
 *    safely bypasses/removes failed vector layer and activates fallback raster basemap.
 * 4. All 40 operational forecast markers, popups, and click interactions remain 100% visible and interactive.
 */
export const MapTilerVectorBasemap: React.FC<MapTilerVectorBasemapProps> = ({
  style = "dataviz-light",
}) => {
  const map = useMap();
  const layerRef = useRef<any>(null);
  const maptilerKey = (import.meta.env.VITE_MAPTILER_KEY || "").trim();
  const hasKey = Boolean(maptilerKey && maptilerKey !== "your-maptiler-key");

  const [status, setStatus] = useState<BasemapStatus>(!hasKey ? "unconfigured" : "loading");

  useEffect(() => {
    if (!hasKey || !maptilerKey) {
      return;
    }

    let isMounted = true;
    let watchdogTimer: any = null;
    let layerInstance: any = null;

    const cleanupLayer = () => {
      if (layerInstance && map) {
        try {
          map.removeLayer(layerInstance);
        } catch {
          // ignore cleanup issues
        }
        layerInstance = null;
        layerRef.current = null;
      }
    };

    const handleFailure = (reason: string) => {
      if (!isMounted) return;
      console.warn(`[MapTiler] Vector basemap unavailable (${reason}). Activating fallback basemap.`);
      cleanupLayer();
      setStatus("failed");
    };

    const handleSuccess = () => {
      if (!isMounted) return;
      if (watchdogTimer) {
        clearTimeout(watchdogTimer);
        watchdogTimer = null;
      }
      setStatus("ready");
    };

    try {
      setStatus("loading");
      layerInstance = new MaptilerLayer({
        apiKey: maptilerKey,
        style,
      });

      // 1. Listen to MaptilerLayer events (Leaflet Evented)
      layerInstance.once("ready", handleSuccess);
      layerInstance.on("error", (e: any) => handleFailure("layer error: " + (e?.message || "unknown")));

      // 2. Add layer to map
      layerInstance.addTo(map);
      layerRef.current = layerInstance;

      // 3. Inspect underlying MapLibre / MapTiler SDK map instance
      try {
        const sdkMap = layerInstance.getMaptilerSDKMap?.();
        if (sdkMap) {
          sdkMap.once("load", handleSuccess);
          sdkMap.on("error", (e: any) => {
            const errStatus = e?.error?.status || e?.status;
            handleFailure(`sdk error (${errStatus || e?.error?.message || "tile error"})`);
          });
        }
      } catch {
        // Ignore SDK introspection errors
      }

      // 4. Watchdog timer: If neither ready nor load fires within 4.5 seconds, activate fallback
      watchdogTimer = setTimeout(() => {
        if (isMounted) {
          handleFailure("load timeout watchdog exceeded (4500ms)");
        }
      }, 4500);

    } catch (err: any) {
      handleFailure("synchronous init exception: " + (err?.message || String(err)));
    }

    return () => {
      isMounted = false;
      if (watchdogTimer) {
        clearTimeout(watchdogTimer);
      }
      cleanupLayer();
    };
  }, [map, hasKey, maptilerKey, style]);

  // If status is unconfigured or failed: render robust fallback TileLayer
  if (status === "unconfigured" || status === "failed") {
    return (
      <>
        {/* Light fallback basemap for local dev when VITE_MAPTILER_KEY is unconfigured or unavailable */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* Clear non-blocking indicator badge */}
        <div className="leaflet-top leaflet-right !mt-12 !mr-3 pointer-events-none z-[1000]">
          {status === "failed" ? (
            <div className="bg-amber-50/95 border border-amber-300 text-amber-900 text-[10px] font-mono px-2.5 py-1 rounded-md shadow-sm flex items-center gap-1.5 backdrop-blur-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
              <span>MapTiler unavailable · fallback basemap</span>
            </div>
          ) : (
            <div className="bg-amber-50/95 border border-amber-200 text-amber-800 text-[10px] font-mono px-2.5 py-1 rounded-md shadow-sm flex items-center gap-1.5 backdrop-blur-sm">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
              <span>MapTiler Vector Basemap: Set VITE_MAPTILER_KEY in web/.env</span>
            </div>
          )}
        </div>
      </>
    );
  }

  return null;
};
