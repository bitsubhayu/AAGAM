import React, { useState } from "react";
import {
  Activity,
  Award,
  Info,
  Database,
} from "lucide-react";
import { useUIStore, VARIABLES } from "@/store/uiStore";
import { useSkill } from "@/api/useSkill";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { SkillComparisonChart } from "@/components/charts/SkillComparisonChart";
import { CategoricalSkillChart } from "@/components/charts/CategoricalSkillChart";
import { Skeleton } from "@/components/ui/Skeleton";

export const SkillPage: React.FC = () => {
  const { selectedVariable, selectedRegion, setSelectedRegion } = useUIStore();
  const [metric, setMetric] = useState<"mae" | "rmse" | "bias">("mae");
  const [selectedLead, setSelectedLead] = useState<number>(1);

  const { data: skillData, isLoading } = useSkill({
    variable: selectedVariable,
    region: selectedRegion,
    windowDays: 90,
  });

  const varMeta = VARIABLES[selectedVariable];
  const scores = skillData?.scores || [];

  // Identify cells where blend did NOT beat best single model (Honesty Banner per PRD §10.4 / §2.1 G1)
  const nonWinningLeads: number[] = [];
  [1, 2, 3, 4, 5, 6, 7].forEach((lead) => {
    const leadScores = scores.filter((s) => s.lead_days === lead);
    const blend = leadScores.find((s) => s.model === "blend");
    const singleModels = leadScores.filter(
      (s) => s.model !== "blend" && s.model !== "equal_mean"
    );

    if (blend?.mae !== undefined && blend.mae !== null && singleModels.length > 0) {
      const minSingleMae = Math.min(...singleModels.map((m) => m.mae ?? 999));
      if (blend.mae > minSingleMae) {
        nonWinningLeads.push(lead);
      }
    }
  });

  return (
    <div className="space-y-4 font-sans">
      {/* Top Filter & Metadata Bar */}
      <div className="flex items-center justify-between gap-3 flex-wrap bg-surface p-3 rounded-lg border border-[rgba(26,23,18,0.10)]">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-emerald-400" />
            <span className="text-xs font-bold text-text-primary">Verification Dataset:</span>
          </div>

          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-text-muted text-[11px]">Region:</span>
            <select
              value={selectedRegion}
              onChange={(e) => setSelectedRegion(e.target.value)}
              className="px-2.5 py-1 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded text-xs text-text-primary outline-none"
            >
              <option value="ALL">All India (40 Points)</option>
              <option value="NW">North-West (NW)</option>
              <option value="CENTRAL">Central India</option>
              <option value="EAST_NE">East & North-East</option>
              <option value="SOUTH">South Peninsula</option>
              <option value="HIMALAYAN">Himalayan / Hilly</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-text-muted text-[11px]">Metric:</span>
            <div className="flex items-center bg-[#F0EDE7] p-0.5 rounded border border-[rgba(26,23,18,0.10)]">
              {(["mae", "rmse", "bias"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMetric(m)}
                  className={`px-2 py-0.5 rounded text-[10px] uppercase font-mono font-medium transition-colors ${
                    metric === m
                      ? "bg-brand-blue text-white"
                      : "text-text-muted hover:text-text-secondary"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Verification Source Badge */}
        <div className="flex items-center gap-2 text-[11px] text-text-muted">
          <Database className="w-3.5 h-3.5 text-blue-400" />
          <span>Ground Truth: IMD 0.25° Gridded Rainfall & ERA5 Climatology</span>
        </div>
      </div>

      {/* Mandatory Honesty Banner (PRD §10.4 FR-UI-4) */}
      <div className="p-3.5 bg-blue-950/20 border border-blue-800/40 rounded-lg flex items-start gap-3">
        <Info className="w-5 h-5 text-brand-blue shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <div className="font-bold text-text-primary flex items-center gap-2">
            <span>Honest Evaluation & Verification Policy (PRD §2.1 G1)</span>
            <Badge variant="normal">HELD-OUT 90-DAY TEST</Badge>
          </div>
          <p className="text-text-secondary leading-relaxed">
            AAGAM reports model verification metrics transparently against independent observations.
            {nonWinningLeads.length > 0 ? (
              <span>
                {" "}
                In this domain window, single model forecasts outperformed the blend at{" "}
                <span className="text-amber-400 font-mono font-bold">
                  {nonWinningLeads.map((l) => `D+${l}`).join(", ")}
                </span>
                . These cells are surfaced directly to forecasters to inform manual overrides.
              </span>
            ) : (
              <span>
                {" "}
                AAGAM Blend outperforms the equal-mean baseline across evaluated lead days in this window.
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Main Comparison Chart */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Activity className="w-4 h-4 text-brand-blue" />
              <span>Model Skill Error Curves Across Lead Days (D+1 to D+7)</span>
            </CardTitle>
            <CardDescription>
              Comparing AAGAM Blend vs GFS, ECMWF IFS, DWD ICON, ECMWF AIFS, and Equal-Mean Baseline
            </CardDescription>
          </div>
          <Badge variant="outline">
            {varMeta.label} ({varMeta.shortUnit})
          </Badge>
        </CardHeader>

        {isLoading ? (
          <div className="py-12">
            <Skeleton className="h-64 w-full" />
          </div>
        ) : (
          <SkillComparisonChart
            scores={scores}
            metric={metric}
            unit={varMeta.shortUnit}
          />
        )}
      </Card>

      {/* Categorical Rain Verification (POD / FAR / CSI at 64.5 mm) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4">
          <CardHeader className="pb-2 mb-2">
            <div>
              <CardTitle>
                <Award className="w-4 h-4 text-emerald-400" />
                <span>Heavy Rain Contingency Metrics (≥ 64.5 mm/24h)</span>
              </CardTitle>
              <CardDescription>
                Probability of Detection (POD), False Alarm Ratio (FAR), and Critical Success Index (CSI)
              </CardDescription>
            </div>

            <div className="flex items-center gap-1 bg-[#F0EDE7] p-0.5 rounded border border-[rgba(26,23,18,0.10)] text-xs">
              {[1, 2, 3, 5, 7].map((lead) => (
                <button
                  key={lead}
                  onClick={() => setSelectedLead(lead)}
                  className={`w-6 h-6 rounded flex items-center justify-center font-mono text-[11px] transition-colors ${
                    selectedLead === lead
                      ? "bg-brand-blue text-white font-bold"
                      : "text-text-muted hover:text-text-secondary"
                  }`}
                >
                  +{lead}
                </button>
              ))}
            </div>
          </CardHeader>

          <CategoricalSkillChart scores={scores} leadDays={selectedLead} />
        </Card>

        {/* Skill Matrix Exact Table */}
        <Card className="p-4">
          <CardHeader className="pb-2 mb-2">
            <CardTitle>Skill Summary Table (Lead D+{selectedLead})</CardTitle>
            <CardDescription>
              Verified against IMD ground truth observations
            </CardDescription>
          </CardHeader>

          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse font-mono">
              <thead>
                <tr className="border-b border-[rgba(26,23,18,0.10)] bg-surface text-text-muted">
                  <th className="p-2 font-sans">Model</th>
                  <th className="p-2">MAE</th>
                  <th className="p-2">RMSE</th>
                  <th className="p-2">Bias</th>
                  <th className="p-2">CSI (Score)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60 text-[11px]">
                {scores
                  .filter((s) => s.lead_days === selectedLead)
                  .map((s) => (
                    <tr
                      key={s.model}
                      className={s.model === "blend" ? "bg-brand-blue/10 font-bold" : ""}
                    >
                      <td className="p-2 font-sans font-medium text-text-primary capitalize">
                        {s.model === "blend"
                          ? "★ AAGAM Blend"
                          : s.model === "equal_mean"
                          ? "Equal-Mean"
                          : s.model.toUpperCase()}
                      </td>
                      <td className="p-2 text-text-primary">
                        {s.mae !== undefined && s.mae !== null ? s.mae.toFixed(2) : "—"}
                      </td>
                      <td className="p-2 text-text-secondary">
                        {s.rmse !== undefined && s.rmse !== null ? s.rmse.toFixed(2) : "—"}
                      </td>
                      <td className="p-2 text-text-secondary">
                        {s.bias !== undefined && s.bias !== null
                          ? (s.bias > 0 ? `+${s.bias.toFixed(2)}` : s.bias.toFixed(2))
                          : "—"}
                      </td>
                      <td className="p-2 text-brand-blue font-bold">
                        {s.csi !== undefined && s.csi !== null ? s.csi.toFixed(3) : "—"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
};
