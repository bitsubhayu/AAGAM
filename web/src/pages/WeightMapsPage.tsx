import React, { useState } from "react";
import {
  Sliders,
  MapPin,
  Layers,
  History,
} from "lucide-react";
import { useUIStore, VARIABLES } from "@/store/uiStore";
import { useWeights, useWeightOverrides } from "@/api/useWeights";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { WeightHeatmap } from "@/components/charts/WeightHeatmap";
import { WeightSpatialMap } from "@/components/map/WeightSpatialMap";
import { WeightDetailDrawer } from "@/components/weights/WeightDetailDrawer";
import { OverrideFormModal } from "@/components/weights/OverrideFormModal";
import type { WeightMatrixItem } from "@/api/types";
import { Skeleton } from "@/components/ui/Skeleton";

export const WeightMapsPage: React.FC = () => {
  const {
    selectedVariable,
    selectedSeason,
    setSelectedSeason,
  } = useUIStore();

  const [viewMode, setViewMode] = useState<"heatmap" | "spatial">("heatmap");
  const [selectedCell, setSelectedCell] = useState<{
    region: string;
    leadDays: number;
    items: WeightMatrixItem[];
  } | null>(null);

  const [overrideModalOpen, setOverrideModalOpen] = useState(false);

  const { data: weightsData, isLoading: weightsLoading } = useWeights({
    variable: selectedVariable,
    season: selectedSeason,
  });

  const { data: overrides } = useWeightOverrides();
  const varMeta = VARIABLES[selectedVariable];

  const handleSelectCell = (region: string, leadDays: number, items: WeightMatrixItem[]) => {
    setSelectedCell({ region, leadDays, items });
  };

  return (
    <div className="space-y-4 font-sans">
      {/* Top Filter Bar */}
      <div className="flex items-center justify-between gap-3 flex-wrap bg-surface p-3 rounded-lg border border-[rgba(26,23,18,0.10)]">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Sliders className="w-4 h-4 text-brand-blue" />
            <span className="text-xs font-bold text-text-primary">Domain Filters:</span>
          </div>

          {/* Season Filter */}
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-text-muted text-[11px]">Season:</span>
            <select
              value={selectedSeason}
              onChange={(e) => setSelectedSeason(e.target.value)}
              className="px-2.5 py-1 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded text-xs text-text-primary capitalize outline-none"
            >
              <option value="monsoon">Southwest Monsoon (Jun–Sep)</option>
              <option value="postmonsoon">Post-Monsoon (Oct–Dec)</option>
              <option value="winter">Winter (Jan–Feb)</option>
              <option value="premonsoon">Pre-Monsoon (Mar–May)</option>
              <option value="all">Annual Consolidated</option>
            </select>
          </div>

          <div className="text-[11px] text-text-muted">
            Variable: <span className="font-semibold text-text-secondary">{varMeta.label}</span>
          </div>
        </div>

        {/* View Toggle */}
        <div className="flex items-center gap-1 bg-[#F0EDE7] p-0.5 rounded border border-[rgba(26,23,18,0.10)]">
          <button
            onClick={() => setViewMode("heatmap")}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors ${
              viewMode === "heatmap"
                ? "bg-brand-blue text-white"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Region × Lead Matrix</span>
          </button>

          <button
            onClick={() => setViewMode("spatial")}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors ${
              viewMode === "spatial"
                ? "bg-brand-blue text-white"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            <MapPin className="w-3.5 h-3.5" />
            <span>Dominant Station Map</span>
          </button>
        </div>
      </div>

      {/* Main Viewport */}
      {viewMode === "heatmap" ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-2 p-4">
            <CardHeader className="pb-2 mb-2">
              <div>
                <CardTitle>
                  <Layers className="w-4 h-4 text-brand-blue" />
                  <span>Adaptive Weight Matrix (5 Regions × 7 Lead Days)</span>
                </CardTitle>
                <CardDescription>
                  Click any cell to inspect 4-model breakdown and n verification samples
                </CardDescription>
              </div>
              <Badge variant="outline">
                {weightsData?.version_id ? `Model Version #${weightsData.version_id}` : "ACTIVE"}
              </Badge>
            </CardHeader>

            {weightsLoading ? (
              <div className="py-12">
                <Skeleton className="h-64 w-full" />
              </div>
            ) : (
              <WeightHeatmap
                weights={weightsData?.weights || []}
                onSelectCell={handleSelectCell}
                selectedRegion={selectedCell?.region}
                selectedLeadDays={selectedCell?.leadDays}
              />
            )}
          </Card>

          {/* Cell Detail / Forecaster Override Panel */}
          <div>
            {selectedCell ? (
              <WeightDetailDrawer
                region={selectedCell.region}
                leadDays={selectedCell.leadDays}
                variable={selectedVariable}
                season={selectedSeason}
                cellItems={selectedCell.items}
                onOpenOverride={() => setOverrideModalOpen(true)}
              />
            ) : (
              <div className="h-full min-h-[300px] p-6 bg-surface border border-[rgba(26,23,18,0.10)] rounded-lg flex flex-col items-center justify-center text-center text-xs text-text-muted space-y-2">
                <Sliders className="w-8 h-8 text-brand-blue/50" />
                <p className="font-semibold text-text-secondary">Cell Details Inspector</p>
                <p className="max-w-xs text-[11px]">
                  Click any regional cell in the matrix above to view exact model weights, sample
                  sizes, and apply audited forecaster overrides.
                </p>
              </div>
            )}
          </div>
        </div>
      ) : (
        <Card className="p-4">
          <CardHeader className="pb-2 mb-2">
            <div>
              <CardTitle>
                <MapPin className="w-4 h-4 text-brand-blue" />
                <span>Dominant Model Spatial Distribution</span>
              </CardTitle>
              <CardDescription>
                Geographic visualization of highest-weighted model per station
              </CardDescription>
            </div>
          </CardHeader>

          <WeightSpatialMap />
        </Card>
      )}

      {/* Active Overrides Audit Trail (PRD §10.4 FR-UI-3) */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <History className="w-4 h-4 text-brand-orange" />
              <span>Audited Forecaster Overrides Trail</span>
            </CardTitle>
            <CardDescription>
              Logged adjustments applied to multi-model blending formulas
            </CardDescription>
          </div>
        </CardHeader>

        {!overrides || overrides.length === 0 ? (
          <div className="p-4 bg-[#F0EDE7] rounded text-center text-xs text-text-muted">
            No active forecaster weight overrides currently in effect. Baseline model matrix active.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead>
                <tr className="border-b border-[rgba(26,23,18,0.10)] bg-surface text-text-muted font-mono">
                  <th className="p-2.5">Region</th>
                  <th className="p-2.5">Lead</th>
                  <th className="p-2.5">Adjusted Weights</th>
                  <th className="p-2.5">Audit Justification</th>
                  <th className="p-2.5">Status</th>
                  <th className="p-2.5">Expires</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {overrides.map((ov) => (
                  <tr key={ov.id} className="hover:bg-[#F0EDE7]/50">
                    <td className="p-2.5 font-bold">{ov.region}</td>
                    <td className="p-2.5 font-mono">+{ov.lead_days}d</td>
                    <td className="p-2.5 font-mono text-[11px]">
                      {Object.entries(ov.overridden_weights || {})
                        .map(([m, w]) => `${m}: ${Math.round((w as number) * 100)}%`)
                        .join(", ")}
                    </td>
                    <td className="p-2.5 max-w-sm truncate text-text-secondary">
                      {ov.reason}
                    </td>
                    <td className="p-2.5">
                      <Badge variant={ov.status === "active" ? "watch" : "outline"}>
                        {ov.status.toUpperCase()}
                      </Badge>
                    </td>
                    <td className="p-2.5 font-mono text-text-muted text-[11px]">
                      {ov.expires_at ? new Date(ov.expires_at).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Override Modal */}
      {selectedCell && (
        <OverrideFormModal
          isOpen={overrideModalOpen}
          onClose={() => setOverrideModalOpen(false)}
          variable={selectedVariable}
          region={selectedCell.region}
          season={selectedSeason}
          leadDays={selectedCell.leadDays}
          initialWeights={selectedCell.items.reduce((acc, item) => {
            acc[item.model] = item.weight;
            return acc;
          }, {} as Record<string, number>)}
        />
      )}
    </div>
  );
};
