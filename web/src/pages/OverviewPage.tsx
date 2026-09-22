import React, { useState, useEffect } from "react";
import {
  AlertTriangle,
  Award,
  TrendingUp,
  Server,
  ArrowRight,
  ShieldCheck,
  MapPin,
  Clock,
  Bell,
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
import { AlertEventDetailDrawer } from "@/components/alerts/AlertEventDetailDrawer";
import { GetAlertsDialog } from "@/components/alerts/GetAlertsDialog";
import { fetchMySubscription } from "@/api/client";
import type { Subscription } from "@/api/types";
import { Skeleton } from "@/components/ui/Skeleton";

export const OverviewPage: React.FC = () => {
  const {
    selectedVariable,
    selectedLeadDays,
    setActiveTab,
  } = useUIStore();

  // Selected window with local storage client-side persistence (PRD §10.4 FR-UI-1)
  const [selectedWindow, setSelectedWindow] = useState<string>(() => {
    try {
      return localStorage.getItem("aagam_alert_window") || "upcoming_7d";
    } catch {
      return "upcoming_7d";
    }
  });

  const [hazardFilter, setHazardFilter] = useState<string>("ALL");
  const [regionFilter, setRegionFilter] = useState<string>("ALL");
  const [minSeverityFilter, setMinSeverityFilter] = useState<string>("ALL");
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);

  // Phase 11 Get Alerts / Subscription state
  const [isGetAlertsOpen, setIsGetAlertsOpen] = useState<boolean>(false);
  const [mySubscription, setMySubscription] = useState<Subscription | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(() => localStorage.getItem("aagam_user_email"));

  useEffect(() => {
    const email = localStorage.getItem("aagam_user_email");
    const token = localStorage.getItem("aagam_auth_token");
    if (token && email) {
      fetchMySubscription()
        .then((sub) => setMySubscription(sub))
        .catch(() => {});
    }
  }, [isGetAlertsOpen]);

  useEffect(() => {
    try {
      localStorage.setItem("aagam_alert_window", selectedWindow);
    } catch {}
  }, [selectedWindow]);

  const { data: alertsData, isLoading: alertsLoading } = useAlerts({
    window: selectedWindow,
    hazard: hazardFilter !== "ALL" ? hazardFilter : undefined,
    region: regionFilter !== "ALL" ? regionFilter : undefined,
    minSeverity: minSeverityFilter !== "ALL" ? minSeverityFilter : undefined,
    limit: 20,
  });

  const { data: meta, isLoading: metaLoading } = useMeta();
  const { data: skillData, isLoading: skillLoading } = useSkill({
    variable: selectedVariable,
    windowDays: 90,
  });

  const varMeta = VARIABLES[selectedVariable];
  const activeAlertsCount = alertsData?.count ?? 0;
  const rawAlerts = alertsData?.alerts || [];

  // Severity counts
  const advisoryCount = rawAlerts.filter((a) => a.severity === "advisory").length;
  const watchCount = rawAlerts.filter((a) => a.severity === "watch").length;
  const alertCount = rawAlerts.filter((a) => a.severity === "alert").length;

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

  const getEmptyStateMessage = () => {
    switch (selectedWindow) {
      case "upcoming_2d":
        return "No alerts in the next 2 days.";
      case "upcoming_3d":
        return "No alerts in the next 3 days.";
      case "upcoming_7d":
        return "No alerts in the next 7 days.";
      case "past_24h":
        return "No alerts recorded in the last 24 hours.";
      case "past_7d":
        return "No alerts recorded in the last 7 days.";
      default:
        return "No alerts matching current filters.";
    }
  };

  const handleOpenEvent = (eventId: number) => {
    setSelectedEventId(eventId);
    setDrawerOpen(true);
  };

  return (
    <div className="space-y-4 font-sans">
      {/* KPI Tiles Row (PRD §10.4 FR-UI-1) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {/* KPI 1: Active Alerts */}
        <Card compact className="border-l-4 border-l-hazard-alert">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Weather Alerts Window</span>
            <AlertTriangle className="w-4 h-4 text-hazard-alert" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-text-primary">
              {alertsLoading ? "..." : activeAlertsCount}
            </span>
            <span className="text-xs text-text-muted">flagged points</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px]">
            <span className="text-text-muted capitalize">{selectedWindow.replace("_", " ")}</span>
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
            <span className="text-xs font-medium text-text-muted">Top Single Model</span>
            <Award className="w-4 h-4 text-brand-blue" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={`text-2xl font-bold font-mono ${topModelInfo.colorClass}`}>
              {topModelInfo.name}
            </span>
            <span className="text-xs text-text-muted">{topModelInfo.res}</span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px]">
            <span className="text-text-muted">D+{selectedLeadDays} ({varMeta?.shortUnit || ""}) lead error</span>
            <button
              onClick={() => setActiveTab("weights")}
              className="text-brand-blue hover:underline font-medium"
            >
              Weights &rarr;
            </button>
          </div>
        </Card>

        {/* KPI 3: Ensemble Skill Gain */}
        <Card compact className="border-l-4 border-l-emerald-500">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Blend Performance</span>
            <TrendingUp className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              {skillGainText}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px]">
            <span className="text-text-muted">Held-out test block</span>
            <button
              onClick={() => setActiveTab("skill")}
              className="text-brand-blue hover:underline font-medium"
            >
              Skill Curves &rarr;
            </button>
          </div>
        </Card>

        {/* KPI 4: Ingestion / System Health */}
        <Card compact className="border-l-4 border-l-emerald-400">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-muted">Ingest Status</span>
            <Server className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              {metaLoading ? "..." : meta?.last_run?.status?.toUpperCase() || "OK"}
            </span>
            <span className="text-xs text-text-muted font-mono">
              {meta?.models ? `${meta.models.length}/${meta.models.length} sources` : "4/4 sources"}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between text-[11px]">
            <span className="text-text-muted font-mono">
              v{meta?.active_model_version?.id ? `${meta.active_model_version.id}` : "prod"}
            </span>
            <button
              onClick={() => setActiveTab("pipeline")}
              className="text-brand-blue hover:underline font-medium"
            >
              Health &rarr;
            </button>
          </div>
        </Card>
      </div>

      {/* Main Content Grid: Map (2 Cols) + Home Alerts Section (1 Col) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        {/* Left 2 Cols: Interactive Map with Lead & Variable Controls */}
        <div className="lg:col-span-2 space-y-4">
          <Card className="p-4">
            <CardHeader className="pb-3 border-b border-border">
              <div>
                <CardTitle className="text-base flex items-center gap-2">
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

        {/* Right 1 Col: Upgraded Public Home Alerts Section (PRD §10.4 FR-UI-1) */}
        <div className="space-y-4">
          <Card className="p-4">
            <CardHeader className="pb-2 mb-2">
              <div>
                <CardTitle>
                  <AlertTriangle className="w-4 h-4 text-brand-orange" />
                  <span>Weather Alerts & Events</span>
                </CardTitle>
                <CardDescription>
                  Public hazard guidance calibrated to IMD criteria
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setIsGetAlertsOpen(true)}
                  className="text-xs h-7 gap-1 border-teal-500/40 text-teal-400 hover:bg-teal-500/10"
                >
                  <Bell className="w-3 h-3" />
                  <span>{userEmail ? "Your Alerts" : "Get Alerts"}</span>
                </Button>
                <Badge variant="watch">{activeAlertsCount} TOTAL</Badge>
              </div>
            </CardHeader>

            {/* Personalized Subscriber Greeting (PRD §10.4) */}
            {userEmail && mySubscription?.active && (
              <div className="mx-4 mt-2 p-2.5 rounded-lg bg-[#3FD0B4]/10 border border-[#3FD0B4]/30 text-xs text-[#E7EDF3] flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bell className="w-3.5 h-3.5 text-[#3FD0B4]" />
                  <span>
                    Hi, <strong className="font-semibold text-[#3FD0B4]">{userEmail.split("@")[0]}</strong> &mdash; showing alerts for your {mySubscription.location_ids.length} saved location(s).
                  </span>
                </div>
                <button
                  onClick={() => setIsGetAlertsOpen(true)}
                  className="text-[11px] text-[#3FD0B4] underline hover:text-[#3FD0B4]/80 font-medium ml-2 shrink-0"
                >
                  Manage
                </button>
              </div>
            )}

            {/* Upcoming / Past Window Toggle */}
            <div className="space-y-2 pt-1 border-t border-border/60">
              <div className="flex items-center justify-between text-[11px] text-text-muted">
                <span className="flex items-center gap-1 font-medium">
                  <Clock className="w-3 h-3 text-brand-blue" />
                  <span>Window:</span>
                </span>
                <div className="flex items-center gap-1">
                  <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 text-[10px] font-mono">
                    {advisoryCount} Adv
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400 border border-orange-500/30 text-[10px] font-mono">
                    {watchCount} Wat
                  </span>
                  <span className="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/30 text-[10px] font-mono font-bold">
                    {alertCount} Alt
                  </span>
                </div>
              </div>

              {/* Toggle Buttons */}
              <div className="grid grid-cols-2 gap-1.5 bg-[#161b22] p-1 rounded border border-border text-xs">
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-text-muted uppercase font-mono px-1">Upcoming:</span>
                  {(["upcoming_2d", "upcoming_3d", "upcoming_7d"] as const).map((w) => (
                    <button
                      key={w}
                      onClick={() => setSelectedWindow(w)}
                      className={`flex-1 py-1 px-1 rounded text-[11px] font-medium transition-colors ${
                        selectedWindow === w
                          ? "bg-brand-blue text-white"
                          : "text-text-muted hover:text-text-secondary bg-[#21262d]"
                      }`}
                      title={w === "upcoming_7d" ? "Next 7 days (Default)" : undefined}
                    >
                      {w === "upcoming_2d" ? "2d" : w === "upcoming_3d" ? "3d" : "7d (Def)"}
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-1 border-l border-border/60 pl-1.5">
                  <span className="text-[10px] text-text-muted uppercase font-mono px-1">Past:</span>
                  {(["past_24h", "past_7d"] as const).map((w) => (
                    <button
                      key={w}
                      onClick={() => setSelectedWindow(w)}
                      className={`flex-1 py-1 px-1 rounded text-[11px] font-medium transition-colors ${
                        selectedWindow === w
                          ? "bg-brand-blue text-white"
                          : "text-text-muted hover:text-text-secondary bg-[#21262d]"
                      }`}
                    >
                      {w === "past_24h" ? "24h" : "7d"}
                    </button>
                  ))}
                </div>
              </div>

              {/* Filters Row */}
              <div className="grid grid-cols-3 gap-1.5 text-[11px] pt-1">
                <select
                  value={hazardFilter}
                  onChange={(e) => setHazardFilter(e.target.value)}
                  className="bg-[#21262d] border border-border rounded px-1.5 py-1 text-text-primary outline-none"
                >
                  <option value="ALL">All Hazards</option>
                  <option value="heavy_rain">Rain</option>
                  <option value="heatwave">Heat</option>
                  <option value="high_wind">Wind</option>
                  <option value="high_uncertainty">Spread</option>
                </select>

                <select
                  value={regionFilter}
                  onChange={(e) => setRegionFilter(e.target.value)}
                  className="bg-[#21262d] border border-border rounded px-1.5 py-1 text-text-primary outline-none"
                >
                  <option value="ALL">All Regions</option>
                  <option value="NORTH">North</option>
                  <option value="SOUTH">South</option>
                  <option value="EAST_NE">East/NE</option>
                  <option value="WEST">West</option>
                  <option value="CENTRAL">Central</option>
                </select>

                <select
                  value={minSeverityFilter}
                  onChange={(e) => setMinSeverityFilter(e.target.value)}
                  className="bg-[#21262d] border border-border rounded px-1.5 py-1 text-text-primary outline-none"
                >
                  <option value="ALL">All Levels</option>
                  <option value="advisory">Advisory+</option>
                  <option value="watch">Watch+</option>
                  <option value="alert">Alert Only</option>
                </select>
              </div>
            </div>

            {/* Alerts List / Calm Empty State */}
            <div className="space-y-2.5 mt-3 max-h-[500px] overflow-y-auto pr-0.5">
              {alertsLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                </div>
              ) : rawAlerts.length === 0 ? (
                <div className="p-6 bg-[#21262d] rounded-lg text-center text-xs text-text-muted space-y-1">
                  <ShieldCheck className="w-6 h-6 text-emerald-400 mx-auto mb-1.5" />
                  <div className="font-medium text-text-secondary">{getEmptyStateMessage()}</div>
                  <div className="text-[11px]">All 40 synoptic stations currently within normal thresholds.</div>
                </div>
              ) : (
                rawAlerts.map((alert) => (
                  <AlertCard
                    key={alert.id}
                    alert={alert}
                    onSelectEvent={handleOpenEvent}
                  />
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
                  <span>View full history in Extreme Weather Center</span>
                  <ArrowRight className="w-3 h-3 ml-1" />
                </Button>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Phase 10 Alert Event Detail Drawer */}
      <AlertEventDetailDrawer
        eventId={selectedEventId}
        isOpen={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setSelectedEventId(null);
        }}
      />

      {/* Phase 11 Get Alerts / Subscription Dialog */}
      <GetAlertsDialog
        isOpen={isGetAlertsOpen}
        onClose={() => setIsGetAlertsOpen(false)}
        onSubscriptionUpdated={(sub) => {
          setMySubscription(sub);
          setUserEmail(localStorage.getItem("aagam_user_email"));
        }}
      />
    </div>
  );
};
