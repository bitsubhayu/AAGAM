import React from "react";
import type { WeightMatrixItem } from "@/api/types";
import { Badge } from "@/components/ui/Badge";

interface WeightHeatmapProps {
  weights: WeightMatrixItem[];
  onSelectCell?: (region: string, leadDays: number, cellWeights: WeightMatrixItem[]) => void;
  selectedRegion?: string;
  selectedLeadDays?: number;
}

const REGIONS = ["NW", "CENTRAL", "EAST_NE", "SOUTH", "HIMALAYAN"];
const LEADS = [1, 2, 3, 4, 5, 6, 7];

export const WeightHeatmap: React.FC<WeightHeatmapProps> = ({
  weights,
  onSelectCell,
  selectedRegion,
  selectedLeadDays,
}) => {
  // Aggregate weights by [region, lead_days]
  const cellMap = new Map<string, WeightMatrixItem[]>();

  weights.forEach((w) => {
    const key = `${w.region}_${w.lead_days}`;
    if (!cellMap.has(key)) {
      cellMap.set(key, []);
    }
    cellMap.get(key)!.push(w);
  });

  const getDominant = (cellItems?: WeightMatrixItem[]) => {
    if (!cellItems || cellItems.length === 0) return null;
    let maxWeight = -1;
    let dominantModel = "blend";
    cellItems.forEach((item) => {
      if (item.weight > maxWeight) {
        maxWeight = item.weight;
        dominantModel = item.model;
      }
    });
    return { model: dominantModel, weight: maxWeight, items: cellItems };
  };

  const getModelStyle = (model: string, weight: number) => {
    // Opacity based on dominance strength (0.25 to 0.65)
    const normalizedOpacity = Math.min(0.9, Math.max(0.2, (weight - 0.25) * 2 + 0.3));
    switch (model) {
      case "gfs":
        return {
          bg: `rgba(88, 166, 255, ${normalizedOpacity})`,
          text: "#f0f6fc",
          label: "GFS",
          color: "#58a6ff",
        };
      case "ecmwf_ifs":
        return {
          bg: `rgba(63, 185, 80, ${normalizedOpacity})`,
          text: "#f0f6fc",
          label: "IFS",
          color: "#3fb950",
        };
      case "icon":
        return {
          bg: `rgba(240, 136, 62, ${normalizedOpacity})`,
          text: "#f0f6fc",
          label: "ICON",
          color: "#f0883e",
        };
      case "aifs":
        return {
          bg: `rgba(163, 113, 247, ${normalizedOpacity})`,
          text: "#f0f6fc",
          label: "AIFS",
          color: "#a371f7",
        };
      default:
        return {
          bg: "rgba(56, 139, 253, 0.2)",
          text: "#c9d1d9",
          label: "EQUAL",
          color: "#388bfd",
        };
    }
  };

  return (
    <div className="w-full overflow-x-auto">
      <div className="min-w-[550px]">
        {/* Table / Grid */}
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr>
              <th className="p-2.5 text-left font-medium text-text-muted border-b border-border bg-[#161b22]">
                Region \ Lead
              </th>
              {LEADS.map((lead) => (
                <th
                  key={lead}
                  className="p-2.5 text-center font-mono font-medium text-text-secondary border-b border-border bg-[#161b22]"
                >
                  D+{lead}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {REGIONS.map((region) => (
              <tr key={region} className="border-b border-border/60">
                <td className="p-2.5 font-semibold text-text-primary bg-[#161b22]/70">
                  {region}
                </td>
                {LEADS.map((lead) => {
                  const key = `${region}_${lead}`;
                  const cellItems = cellMap.get(key) || [];
                  const dom = getDominant(cellItems);
                  const isSelected =
                    selectedRegion === region && selectedLeadDays === lead;

                  if (!dom) {
                    return (
                      <td
                        key={lead}
                        className="p-2 text-center text-text-muted font-mono text-[11px] bg-[#161b22]/30"
                      >
                        —
                      </td>
                    );
                  }

                  const style = getModelStyle(dom.model, dom.weight);

                  return (
                    <td
                      key={lead}
                      onClick={() => onSelectCell?.(region, lead, cellItems)}
                      className={`p-2 text-center cursor-pointer transition-all duration-150 relative ${
                        isSelected
                          ? "ring-2 ring-brand-blue ring-inset z-10 scale-102 shadow-md"
                          : "hover:brightness-125"
                      }`}
                      style={{ backgroundColor: style.bg }}
                    >
                      <div className="flex flex-col items-center justify-center">
                        <span
                          className="font-mono font-bold text-xs"
                          style={{ color: style.text }}
                        >
                          {style.label}
                        </span>
                        <span className="font-mono text-[10px] text-white/90">
                          {(dom.weight * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>

        {/* Legend */}
        <div className="mt-3 flex items-center justify-between text-xs text-text-muted px-1 flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider font-semibold">Dominant:</span>
            <Badge variant="gfs">GFS (NOAA)</Badge>
            <Badge variant="ifs">ECMWF IFS</Badge>
            <Badge variant="icon">DWD ICON</Badge>
            <Badge variant="aifs">ECMWF AIFS (AI)</Badge>
          </div>
          <span className="text-[10px] text-text-muted font-mono">
            *Cell saturation indicates margin of model dominance
          </span>
        </div>
      </div>
    </div>
  );
};
