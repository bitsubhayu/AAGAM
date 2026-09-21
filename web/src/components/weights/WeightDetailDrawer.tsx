import React from "react";
import type { WeightMatrixItem } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useAuthStore } from "@/auth/authStore";
import { Sliders, AlertCircle } from "lucide-react";

interface WeightDetailDrawerProps {
  region: string;
  leadDays: number;
  variable: string;
  season: string;
  cellItems: WeightMatrixItem[];
  onOpenOverride: () => void;
}

export const WeightDetailDrawer: React.FC<WeightDetailDrawerProps> = ({
  region,
  leadDays,
  variable,
  season,
  cellItems,
  onOpenOverride,
}) => {
  const { role } = useAuthStore();
  const canOverride = role === "forecaster" || role === "admin";

  const modelColors: Record<string, string> = {
    gfs: "#58a6ff",
    ecmwf_ifs: "#3fb950",
    icon: "#f0883e",
    aifs: "#a371f7",
  };

  const sampleCount = cellItems[0]?.n_samples ?? 0;
  const fallbackLevel = cellItems[0]?.fallback_level ?? "cell";

  return (
    <div className="p-4 bg-surface border border-border rounded-lg space-y-4">
      <div className="flex items-center justify-between border-b border-border/80 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm text-text-primary">
              Weight Matrix Cell Inspection
            </span>
            <Badge variant="outline">{region}</Badge>
            <Badge variant="blend">D+{leadDays}</Badge>
          </div>
          <p className="text-xs text-text-muted mt-0.5">
            Season: <span className="capitalize text-text-secondary">{season}</span> · Variable:{" "}
            <span className="text-text-secondary">{variable}</span>
          </p>
        </div>

        <Button
          variant={canOverride ? "primary" : "secondary"}
          size="sm"
          onClick={onOpenOverride}
          disabled={!canOverride}
          title={canOverride ? "Apply audited override" : "Forecaster or Admin role required"}
        >
          <Sliders className="w-3.5 h-3.5 mr-1" />
          <span>{canOverride ? "Override Weights" : "Forecaster Only"}</span>
        </Button>
      </div>

      {/* Model Weight Distribution */}
      <div className="space-y-2.5">
        <span className="text-xs font-semibold text-text-secondary block">
          Model Weight Breakdown:
        </span>
        {cellItems.map((item) => {
          const pct = Math.round(item.weight * 100);
          const color = modelColors[item.model] || "#388bfd";
          return (
            <div key={item.model} className="space-y-1">
              <div className="flex justify-between text-xs font-mono">
                <span className="uppercase text-text-primary font-bold">
                  {item.model}
                </span>
                <span className="text-text-secondary">
                  {(item.weight * 100).toFixed(1)}% ({item.weight.toFixed(3)})
                </span>
              </div>
              <div className="w-full bg-[#21262d] rounded-full h-2 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-300"
                  style={{ width: `${pct}%`, backgroundColor: color }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Telemetry & Fallback Info */}
      <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border/60 text-xs">
        <div className="p-2.5 bg-[#21262d] rounded border border-border">
          <span className="text-text-muted text-[11px] block">Sample Verification Count:</span>
          <span className="font-mono font-bold text-text-primary text-sm">
            n = {sampleCount}
          </span>
          {sampleCount < 30 && (
            <span className="text-[10px] text-amber-400 block mt-0.5 flex items-center gap-1">
              <AlertCircle className="w-3 h-3 shrink-0" /> Low sample size
            </span>
          )}
        </div>

        <div className="p-2.5 bg-[#21262d] rounded border border-border">
          <span className="text-text-muted text-[11px] block">Fallback Tier Applied:</span>
          <span className="font-mono font-bold text-text-primary text-sm uppercase">
            {fallbackLevel}
          </span>
          <span className="text-[10px] text-text-muted block mt-0.5">
            Adaptive Ridge regularizer
          </span>
        </div>
      </div>
    </div>
  );
};
