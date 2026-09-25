import React, { useState } from "react";
import {
  Activity,
  Award,
  Info,
  Database,
  Calendar,
  Sparkles,
  ShieldCheck,
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
  const [scope, setScope] = useState<"live" | "held_out">("live");
  const [metric, setMetric] = useState<"mae" | "rmse" | "bias">("mae");
  const [selectedLead, setSelectedLead] = useState<number>(1);

  const { data: skillData, isLoading } = useSkill({
    variable: selectedVariable,
    region: selectedRegion,
    season: "ALL",
    windowDays: 90,
    scope,
  });

  const varMeta = VARIABLES[selectedVariable];
  const scores = skillData?.scores || [];

  // Filter continuous rows (threshold_mm === 0 or mae !== null) for error metric curves and honesty banner
  const continuousScores = scores.filter(
    (s) => s.threshold_mm === 0 || s.threshold_mm === null || s.mae !== null
  );

  // Filter categorical rows for heavy rain (threshold_mm ≈ 64.5)
  const heavyRainScores = scores.filter(
    (s) => s.threshold_mm !== null && s.threshold_mm !== undefined && Math.abs(s.threshold_mm - 64.5) < 1.0
  );

  // Identify leads with valid continuous data
  const leadsWithData = [1, 2, 3, 4, 5, 6, 7].filter((lead) =>
    continuousScores.some((s) => s.lead_days === lead && s.mae !== null && s.mae !== undefined)
  );

  // Identify cells where blend did NOT beat best single model (Honesty Banner per PRD §10.4 / §2.1 G1)
  const nonWinningLeads: number[] = [];
  leadsWithData.forEach((lead) => {
    const leadScores = continuousScores.filter((s) => s.lead_days === lead);
    const blend = leadScores.find((s) => s.model === "blend");
    const singleModels = leadScores.filter(
      (s) =>
        s.model !== "blend" &&
        s.model !== "equal_mean" &&
        s.model !== "ridge" &&
        s.model !== "lgbm" &&
        s.mae !== null &&
        s.mae !== undefined
    );

    if (blend?.mae !== undefined && blend.mae !== null && singleModels.length > 0) {
      const minSingleMae = Math.min(...singleModels.map((m) => m.mae!));
      if (blend.mae > minSingleMae) {
        nonWinningLeads.push(lead);
      }
    }
  });

  // Dynamic maturity label and styling
  const verifiedDays = skillData?.verified_days_count ?? 0;
  const dataStatus = skillData?.data_status ?? (scope === "live" ? "NO VERIFICATION DATA" : "HELD-OUT 90-DAY TEST");

  const getMaturityBadge = () => {
    if (scope === "held_out") {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-purple-500/10 text-purple-700 border border-purple-500/30 flex items-center gap-1.5">
          <ShieldCheck className="w-3 h-3 text-purple-600" />
          HELD-OUT 90-DAY TEST · BENCHMARK
        </span>
      );
    }
    if (verifiedDays === 0) {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-gray-500/10 text-text-muted border border-gray-500/20">
          NO VERIFICATION DATA
        </span>
      );
    }
    if (verifiedDays <= 3) {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-amber-500/10 text-amber-700 border border-amber-500/30 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          PRELIMINARY LIVE VERIFICATION · {verifiedDays} {verifiedDays === 1 ? "DAY" : "DAYS"}
        </span>
      );
    }
    if (verifiedDays <= 6) {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-blue-500/10 text-blue-700 border border-blue-500/30 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          EARLY LIVE VERIFICATION · {verifiedDays} DAYS
        </span>
      );
    }
    if (verifiedDays >= 90 || (skillData?.effective_window_days ?? 0) >= 90) {
      return (
        <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-emerald-500/10 text-emerald-700 border border-emerald-500/30 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          LIVE VERIFICATION · 90-DAY MAX
        </span>
      );
    }
    return (
      <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-emerald-500/10 text-emerald-700 border border-emerald-500/30 flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        LIVE VERIFICATION · {verifiedDays} DAYS
      </span>
    );
  };

  // Summary table models to display
  const tableModels = ["blend", "gfs", "ecmwf_ifs", "icon", "aifs", "equal_mean"];

  return (
    <div className="space-y-4 font-sans">
      {/* Scope Selector Tabs */}
      <div className="flex items-center justify-between gap-3 flex-wrap bg-surface p-2 rounded-xl border border-[rgba(26,23,18,0.10)]">
        <div className="flex items-center gap-1 bg-[#F0EDE7] p-1 rounded-lg border border-[rgba(26,23,18,0.08)]">
          <button
            onClick={() => setScope("live")}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-2 ${
              scope === "live"
                ? "bg-white text-text-primary shadow-xs font-semibold"
                : "text-text-muted hover:text-text-primary"
            }`}
          >
            <Activity className="w-3.5 h-3.5 text-emerald-600" />
            <span>Live Operational Verification</span>
            {skillData?.verified_days_count !== undefined && scope === "live" && (
              <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700 font-mono font-bold">
                {skillData.verified_days_count}d
              </span>
            )}
          </button>
          <button
            onClick={() => setScope("held_out")}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-2 ${
              scope === "held_out"
                ? "bg-white text-text-primary shadow-xs font-semibold"
                : "text-text-muted hover:text-text-primary"
            }`}
          >
            <ShieldCheck className="w-3.5 h-3.5 text-purple-600" />
            <span>Held-Out 90-Day Test</span>
            <span className="text-[10px] px-1.5 py-0.2 rounded bg-purple-50 text-purple-700 font-mono font-bold">
              Benchmark
            </span>
          </button>
        </div>

        {/* Dynamic Verification Window Details */}
        <div className="flex items-center gap-2.5 flex-wrap">
          {getMaturityBadge()}
          {skillData?.window_start && skillData?.window_end && (
            <div className="flex items-center gap-1 text-[11px] text-text-muted font-mono bg-[#F0EDE7] px-2 py-0.5 rounded border border-[rgba(26,23,18,0.08)]">
              <Calendar className="w-3 h-3 text-text-muted" />
              <span>{skillData.window_start} → {skillData.window_end}</span>
            </div>
          )}
        </div>
      </div>

      {/* Filter & Controls Bar */}
      <div className="flex items-center justify-between gap-3 flex-wrap bg-surface p-3 rounded-lg border border-[rgba(26,23,18,0.10)]">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-text-muted text-[11px]">Region:</span>
            <select
              value={selectedRegion}
              onChange={(e) => setSelectedRegion(e.target.value)}
              className="px-2.5 py-1 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded text-xs text-text-primary outline-none cursor-pointer"
            >
              <option value="ALL">All India (40 Locations)</option>
              <option value="NW">North-West (NW)</option>
              <option value="CENTRAL">Central India</option>
              <option value="EAST_NE">East & North-East</option>
              <option value="SOUTH">South Peninsula</option>
              <option value="HIMALAYAN">Himalayan / Hilly</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-text-muted text-[11px]">Error Metric:</span>
            <div className="flex items-center bg-[#F0EDE7] p-0.5 rounded border border-[rgba(26,23,18,0.10)]">
              {(["mae", "rmse", "bias"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMetric(m)}
                  className={`px-2.5 py-0.5 rounded text-[10px] uppercase font-mono font-medium transition-colors ${
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

        {/* Scientifically Accurate Ground Truth Source Badge */}
        <div className="flex items-center gap-1.5 text-[11px] text-text-muted bg-[#F0EDE7]/60 px-2.5 py-1 rounded border border-[rgba(26,23,18,0.06)]">
          <Database className="w-3.5 h-3.5 text-blue-500 shrink-0" />
          <span>Ground Truth:</span>
          <span className="font-medium text-text-secondary">
            {skillData?.truth_source || "ERA5 Climatology Fallback / IMD 0.25°"}
          </span>
        </div>
      </div>

      {/* Mandatory Honesty Banner (PRD §10.4 FR-UI-4) */}
      <div className="p-3.5 bg-blue-950/20 border border-blue-800/40 rounded-lg flex items-start gap-3">
        <Info className="w-5 h-5 text-brand-blue shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <div className="font-bold text-text-primary flex items-center gap-2">
            <span>Honest Evaluation & Verification Policy (PRD §2.1 G1)</span>
            <Badge variant="normal">
              {scope === "held_out" ? "HELD-OUT 90-DAY TEST" : dataStatus}
            </Badge>
          </div>
          <p className="text-text-secondary leading-relaxed">
            AAGAM reports model verification metrics transparently against independent observations.
            {leadsWithData.length === 0 ? (
              <span>
                {" "}
                No operational forecasts have matching verified observations in this selected domain window yet.
              </span>
            ) : nonWinningLeads.length > 0 ? (
              <span>
                {" "}
                In this domain window, single model forecasts outperformed the blend at{" "}
                <span className="text-amber-500 font-mono font-bold">
                  {nonWinningLeads.map((l) => `D+${l}`).join(", ")}
                </span>
                . These cells are surfaced directly to forecasters to inform manual overrides.
              </span>
            ) : (
              <span>
                {" "}
                AAGAM Blend outperforms or matches single-model baselines across all verified lead days (
                {leadsWithData.map((l) => `D+${l}`).join(", ")}) in this evaluation window.
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
          <div className="flex items-center gap-2">
            <Badge variant="outline">
              {varMeta.label} ({varMeta.shortUnit})
            </Badge>
          </div>
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
            dataStatus={dataStatus}
          />
        )}
      </Card>

      {/* Categorical Rain Verification (POD / FAR / CSI at 64.5 mm) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card className="p-4">
          <CardHeader className="pb-2 mb-2">
            <div>
              <CardTitle>
                <Award className="w-4 h-4 text-emerald-500" />
                <span>Heavy Rain Contingency Metrics (≥ 64.5 mm/24h)</span>
              </CardTitle>
              <CardDescription>
                Probability of Detection (POD), False Alarm Ratio (FAR), and Critical Success Index (CSI)
              </CardDescription>
            </div>

            <div className="flex items-center gap-1 bg-[#F0EDE7] p-0.5 rounded border border-[rgba(26,23,18,0.10)] text-xs">
              {[1, 2, 3, 4, 5, 6, 7].map((lead) => {
                const hasLeadData = leadsWithData.includes(lead);
                return (
                  <button
                    key={lead}
                    onClick={() => setSelectedLead(lead)}
                    className={`w-6 h-6 rounded flex items-center justify-center font-mono text-[11px] transition-colors ${
                      selectedLead === lead
                        ? "bg-brand-blue text-white font-bold"
                        : hasLeadData
                        ? "text-text-primary hover:text-brand-blue"
                        : "text-text-muted/60 hover:text-text-muted"
                    }`}
                    title={hasLeadData ? `Lead D+${lead} verified` : `Lead D+${lead} no observations yet`}
                  >
                    +{lead}
                  </button>
                );
              })}
            </div>
          </CardHeader>

          <CategoricalSkillChart
            scores={scores}
            leadDays={selectedLead}
            thresholdMm={64.5}
          />
        </Card>

        {/* Skill Matrix Exact Table */}
        <Card className="p-4">
          <CardHeader className="pb-2 mb-2">
            <CardTitle>Skill Summary Table (Lead D+{selectedLead})</CardTitle>
            <CardDescription>
              {scope === "held_out"
                ? "Formal 90-day held-out test evaluation against ground truth"
                : `Verified operational forecasts (${skillData?.verified_days_count ?? 0} days matched against ground truth)`}
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
                  <th className="p-2">CSI (≥64.5mm)</th>
                  <th className="p-2 text-right">N</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60 text-[11px]">
                {tableModels.map((modelKey) => {
                  const contItem = continuousScores.find(
                    (s) => s.lead_days === selectedLead && s.model === modelKey
                  );
                  const rainItem = heavyRainScores.find(
                    (s) => s.lead_days === selectedLead && s.model === modelKey
                  );

                  const isBlend = modelKey === "blend";
                  const nVal = contItem?.n ?? rainItem?.n ?? null;

                  return (
                    <tr
                      key={modelKey}
                      className={isBlend ? "bg-brand-blue/10 font-bold" : ""}
                    >
                      <td className="p-2 font-sans font-medium text-text-primary capitalize flex items-center gap-1.5">
                        {isBlend ? (
                          <>
                            <Sparkles className="w-3 h-3 text-brand-blue" />
                            <span>AAGAM Blend</span>
                          </>
                        ) : modelKey === "equal_mean" ? (
                          "Equal-Mean Baseline"
                        ) : (
                          modelKey.toUpperCase().replace("_", " ")
                        )}
                      </td>
                      <td className="p-2 text-text-primary">
                        {contItem?.mae !== undefined && contItem?.mae !== null
                          ? contItem.mae.toFixed(2)
                          : "—"}
                      </td>
                      <td className="p-2 text-text-secondary">
                        {contItem?.rmse !== undefined && contItem?.rmse !== null
                          ? contItem.rmse.toFixed(2)
                          : "—"}
                      </td>
                      <td className="p-2 text-text-secondary">
                        {contItem?.bias !== undefined && contItem?.bias !== null
                          ? (contItem.bias > 0 ? `+${contItem.bias.toFixed(2)}` : contItem.bias.toFixed(2))
                          : "—"}
                      </td>
                      <td className="p-2 text-brand-blue font-bold">
                        {rainItem?.csi !== undefined && rainItem?.csi !== null
                          ? rainItem.csi.toFixed(3)
                          : "—"}
                      </td>
                      <td className="p-2 text-right text-text-muted font-mono">
                        {nVal !== null ? nVal : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
};

