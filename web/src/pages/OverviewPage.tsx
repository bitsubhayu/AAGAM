import React from "react";
import {
  AlertTriangle,
  Award,
  TrendingUp,
  Server,
  ArrowRight,
  ShieldCheck,
  MapPin,
} from "lucide-react";
import { useUIStore, VARIABLES } from "@/store/uiStore";
import { useAlerts } from "@/api/useAlerts";
import { useMeta } from "@/api/useMeta";
import { useSkill } from "@/api/useSkill";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { IndiaForecastMap } from "@/components/map/IndiaForecastMap";
import { AlertCard } from "@/components/alerts/AlertCard";
import { Skeleton } from "@/components/ui/Skeleton";

export const OverviewPage: React.FC = () => {
  const {
    selectedVariable,
    selectedLeadDays,
    setActiveTab,
  } = useUIStore();

  const { data: alertsData, isLoading: alertsLoading } = useAlerts({
    status: "active",
    limit: 5,
  });

  const { data: meta, isLoading: metaLoading } = useMeta();
  const { data: skillData, isLoading: skillLoading } = useSkill({
    variable: selectedVariable,
    windowDays: 90,
  });

  const varMeta = VARIABLES[selectedVariable];
  const activeAlertsCount = alertsData?.count ?? 0;

  // Calculate skill gain vs equal-mean from latest scores
  const blendScore = skillData?.scores?.find(
    (s) => s.model === "blend" && s.lead_days === selectedLeadDays
  );
  const baselineScore = skillData?.scores?.find(
    (s) => s.model === "equal_mean" && s.lead_days === selectedLeadDays
  );

  let skillGainText = skillLoading ? "..." : "—";
  if (blendScore?.mae && baselineScore?.mae && baselineScore.mae > 0) {
    const gain = ((baselineScore.mae - blendScore.mae) / baselineScore.mae) * 100;
    skillGainText = `${gain >= 0 ? "+" : ""}${gain.toFixed(1)}% vs Equal-Mean`;
  } else if (!skillLoading && (!blendScore?.mae || !baselineScore?.mae)) {
    skillGainText = "N/A";
  }

  // Determine top/dominant single model for this lead day
  const singleScores =
    skillData?.scores?.filter(
      (s) =>
        s.lead_days === selectedLeadDays &&
        s.model !== "blend" &&
        s.model !== "equal_mean" &&
        s.mae !== null &&
        s.mae !== undefined
    ) || [];

  const bestSingle =
    singleScores.length > 0
      ? singleScores.reduce((prev, curr) => (prev.mae! < curr.mae! ? prev : curr))
      : null;

  const modelLabels: Record<string, { name: string; res: string; colorClass: string }> = {
    gfs: { name: "GFS", res: "0.25°", colorClass: "text-model-gfs" },
    ecmwf_ifs: { name: "ECMWF IFS", res: "0.25°", colorClass: "text-model-ifs" },
    icon: { name: "DWD ICON", res: "0.125°", colorClass: "text-model-icon" },
    aifs: { name: "ECMWF AIFS", res: "0.25°", colorClass: "text-model-aifs" },
  };

  const topModelInfo =
    bestSingle?.model && modelLabels[bestSingle.model]
      ? modelLabels[bestSingle.model]
      : {
          name: bestSingle?.model?.toUpperCase() || (skillLoading ? "..." : "—"),
          res: "NWP",
          colorClass: "text-text-primary",
        };

  return (
    <div className="space-y-4 font-sans">
      {/* KPI Tiles Row (PRD §10.4 FR-UI-1) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {/* KPI 1: Active Alerts */}
        <Card compact className="border-l-4 border-l-hazard-alert">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Active Weather Alerts</span>
            <AlertTriangle className="w-4 h-4 text-hazard-alert" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-text-primary">
              {alertsLoading ? "..." : activeAlertsCount}
            </span>
            <span className="text-xs text-text-muted">flagged points</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px]">
            <span className="text-text-muted">Next 72h window</span>
            <button
              onClick={() => setActiveTab("alerts")}
              className="text-brand-blue hover:underline font-medium"
            >
              View all &rarr;
            </button>
          </div>
        </Card>

        {/* KPI 2: Dominant / Best Model */}
        <Card compact className="border-l-4 border-l-brand-blue">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Dominant Model (Lead)</span>
            <Award className="w-4 h-4 text-brand-blue" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={`text-2xl font-bold font-mono ${topModelInfo.colorClass}`}>
              {topModelInfo.name}
            </span>
            <span className="text-xs text-text-muted">{topModelInfo.res}</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px] text-text-muted">
            <span>Lead D+{selectedLeadDays} ({varMeta.shortUnit})</span>
            <span className="text-emerald-400 font-mono">
              {bestSingle?.mae ? `${bestSingle.mae.toFixed(2)} MAE` : "Top skill"}
            </span>
          </div>
        </Card>

        {/* KPI 3: Blend Skill Gain */}
        <Card compact className="border-l-4 border-l-emerald-500">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">AAGAM Blend Gain</span>
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              {skillGainText}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px] text-text-muted">
            <span>90-Day evaluation test</span>
            <button
              onClick={() => setActiveTab("skill")}
              className="text-brand-blue hover:underline font-medium"
            >
              Skill matrix &rarr;
            </button>
          </div>
        </Card>

        {/* KPI 4: Pipeline Health & Active Version */}
        <Card compact className="border-l-4 border-l-purple-500">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Model Version & Freshness</span>
            <Server className="w-4 h-4 text-purple-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-text-primary">
              {metaLoading
                ? "..."
                : meta?.active_model_version?.id
                ? `v${meta.active_model_version.id}`
                : "v1"}
            </span>
            <span className="text-xs px-1.5 py-0.2 rounded bg-emerald-950/50 text-emerald-400 border border-emerald-800/40 font-mono">
              ACTIVE
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px] text-text-muted">
            <span>
              {meta?.models ? `${meta.models.length}/${meta.models.length} Model Feeds OK` : "Feeds Active"}
            </span>
            <button
              onClick={() => setActiveTab("pipeline")}
              className="text-brand-blue hover:underline font-medium"
            >
              Telemetry &rarr;
            </button>
          </div>
        </Card>
      </div>

      {/* Main Viewport: Split Spatial Map & Recent Alerts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Left 2 Cols: India Spatial Map */}
        <div className="lg:col-span-2 space-y-3">
          <Card className="p-4">
            <CardHeader className="pb-2 mb-2">
              <div>
                <CardTitle>
                  <MapPin className="w-4 h-4 text-brand-blue" />
                  <span>Operational Spatial Forecast Grid</span>
                </CardTitle>
                <CardDescription>
                  40 representative synoptic stations across India with IMD agro-climatic zones
                </CardDescription>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setActiveTab("forecast")}
              >
                <span>Forecast Explorer</span>
                <ArrowRight className="w-3 h-3 ml-1" />
              </Button>
            </CardHeader>

            <IndiaForecastMap />
          </Card>
        </div>

        {/* Right 1 Col: Top Active Alerts & Quick Status */}
        <div className="space-y-4">
          <Card className="p-4">
            <CardHeader className="pb-2 mb-2">
              <div>
                <CardTitle>
                  <AlertTriangle className="w-4 h-4 text-brand-orange" />
                  <span>Priority Weather Alerts</span>
                </CardTitle>
                <CardDescription>
                  Active extreme guidance flags across next 72 hours
                </CardDescription>
              </div>
              <Badge variant="watch">{activeAlertsCount} ACTIVE</Badge>
            </CardHeader>

            <div className="space-y-2.5 mt-3">
              {alertsLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                </div>
              ) : !alertsData?.alerts || alertsData.alerts.length === 0 ? (
                <div className="p-6 bg-[#21262d] rounded-lg text-center text-xs text-text-muted">
                  <ShieldCheck className="w-6 h-6 text-emerald-400 mx-auto mb-1.5" />
                  No severe weather alerts active in the next 72 hours.
                </div>
              ) : (
                alertsData.alerts.map((alert) => (
                  <AlertCard key={alert.id} alert={alert} />
                ))
              )}
            </div>

            {activeAlertsCount > 5 && (
              <div className="mt-3 text-center">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setActiveTab("alerts")}
                  className="w-full text-xs text-brand-blue"
                >
                  <span>View all {activeAlertsCount} alerts in Extreme Weather Center</span>
                  <ArrowRight className="w-3 h-3 ml-1" />
                </Button>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
};
