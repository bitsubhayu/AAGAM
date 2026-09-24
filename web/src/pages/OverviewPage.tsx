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
import { TypewriterGreeting } from "@/components/ui/TypewriterGreeting";
import { extractFirstName } from "@/utils/greeting";
import { fetchMySubscription } from "@/api/client";
import type { Subscription } from "@/api/types";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuthStore } from "@/auth/authStore";

export const OverviewPage: React.FC = () => {
  const { profile, user } = useAuthStore();
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
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);

  // Phase 11 Get Alerts / Subscription state
  const [isGetAlertsOpen, setIsGetAlertsOpen] = useState<boolean>(false);
  const [mySubscription, setMySubscription] = useState<Subscription | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(() => localStorage.getItem("aagam_user_email"));

  useEffect(() => {
    const email = localStorage.getItem("aagam_user_email") || user?.email;
    const token = localStorage.getItem("aagam_auth_token");
    if (token && email) {
      fetchMySubscription()
        .then((sub) => setMySubscription(sub))
        .catch(() => {});
    }
  }, [isGetAlertsOpen, user?.email]);

  useEffect(() => {
    try {
      localStorage.setItem("aagam_alert_window", selectedWindow);
    } catch {}
  }, [selectedWindow]);

  const { data: alertsData, isLoading: alertsLoading } = useAlerts({
    window: selectedWindow,
    hazard: hazardFilter !== "ALL" ? hazardFilter : undefined,
    region: regionFilter !== "ALL" ? regionFilter : undefined,
    severity: severityFilter !== "ALL" ? severityFilter : undefined,
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

  // Authoritative severity counts computed over complete dataset before LIMIT (Task 5)
  const advisoryCount = alertsData?.severity_counts?.advisory ?? 0;
  const watchCount = alertsData?.severity_counts?.watch ?? 0;
  const alertCount = alertsData?.severity_counts?.alert ?? 0;

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
    skillGainText = `${gain >= 0 ? "+" : ""}${gain.toFixed(1)}%`;
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

  const modelLabels: Record<string, { name: string; res: string; badgeVariant: "gfs" | "ifs" | "icon" | "aifs" }> = {
    gfs: { name: "GFS", res: "0.25°", badgeVariant: "gfs" },
    ecmwf_ifs: { name: "ECMWF IFS", res: "0.25°", badgeVariant: "ifs" },
    icon: { name: "DWD ICON", res: "0.125°", badgeVariant: "icon" },
    aifs: { name: "ECMWF AIFS", res: "0.25°", badgeVariant: "aifs" },
  };

  const topModelInfo =
    bestSingle?.model && modelLabels[bestSingle.model]
      ? modelLabels[bestSingle.model]
      : {
          name: bestSingle?.model?.toUpperCase() || (skillLoading ? "..." : "—"),
          res: "NWP",
          badgeVariant: "neutral" as const,
        };

  const getEmptyStateMessage = () => {
    switch (selectedWindow) {
      case "upcoming_2d": return "No alerts in the next 2 days.";
      case "upcoming_3d": return "No alerts in the next 3 days.";
      case "upcoming_7d": return "No alerts in the next 7 days.";
      case "past_24h": return "No alerts recorded in the last 24 hours.";
      case "past_7d": return "No alerts recorded in the last 7 days.";
      default: return "No alerts matching current filters.";
    }
  };

  const handleOpenEvent = (eventId: number) => {
    setSelectedEventId(eventId);
    setDrawerOpen(true);
  };

  const selectClass =
    "bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-full px-3 py-1.5 text-xs text-text-primary outline-none focus:ring-2 focus:ring-accent/30 transition-colors hover:bg-white cursor-pointer";

  return (
    <div className="space-y-5 font-sans animate-fade-in">
      {/* Typewriter Greeting + Date Stamp */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <TypewriterGreeting />
          <p className="text-sm text-text-muted">
            {new Date().toLocaleDateString("en-IN", {
              weekday: "long",
              day: "numeric",
              month: "long",
              year: "numeric",
              timeZone: "Asia/Kolkata",
            })}{" "}
            · Last blended{" "}
            {meta?.last_run?.started_at
              ? new Date(meta.last_run.started_at).toLocaleTimeString("en-IN", {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Asia/Kolkata",
                  hour12: false,
                }) + " IST"
              : "—"}
            {meta?.active_model_version?.id ? ` · model v${meta.active_model_version.id}` : ""}
          </p>
        </div>
        {/* Primary CTA — Get Alerts pill */}
        <Button
          variant="primary"
          size="lg"
          onClick={() => setIsGetAlertsOpen(true)}
          className="shrink-0"
        >
          <Bell className="w-4 h-4" />
          <span>{userEmail ? "Your Alerts" : "Get Alerts"}</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </Button>
      </div>

      {/* KPI Tiles — Bento Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {/* KPI 1: Active Alerts */}
        <Card compact>
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-medium text-text-muted">Weather Alerts</span>
            <div className="p-1.5 bg-accent-soft rounded-full">
              <AlertTriangle className="w-3.5 h-3.5 text-accent" />
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold font-mono text-text-primary tabular-nums">
              {alertsLoading ? "…" : activeAlertsCount}
            </span>
            <span className="text-xs text-text-muted">active</span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#FDF3DC] text-[#7A5C00] font-mono font-semibold">
                {advisoryCount} Moderate
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#FEE9D6] text-[#7A3300] font-mono font-semibold">
                {watchCount} High
              </span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-accent-soft text-accent font-mono font-bold">
                {alertCount} Severe
              </span>
            </div>
            <button
              onClick={() => setActiveTab("alerts")}
              className="text-[11px] text-accent hover:underline font-semibold"
            >
              View all →
            </button>
          </div>
        </Card>

        {/* KPI 2: Top Single Model */}
        <Card compact>
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-medium text-text-muted">Top Single Model</span>
            <div className="p-1.5 bg-[#EBF2FD] rounded-full">
              <Award className="w-3.5 h-3.5 text-brand-blue" />
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-text-primary tabular-nums">
              {topModelInfo.name}
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-[11px] text-text-muted">D+{selectedLeadDays} {varMeta?.shortUnit || ""}</span>
            <button
              onClick={() => setActiveTab("weights")}
              className="text-[11px] text-brand-blue hover:underline font-semibold"
            >
              Weights →
            </button>
          </div>
        </Card>

        {/* KPI 3: Blend Skill */}
        <Card compact>
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-medium text-text-muted">Blend vs Equal-Mean</span>
            <div className="p-1.5 bg-[#E4F5EE] rounded-full">
              <TrendingUp className="w-3.5 h-3.5 text-hazard-normal" />
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-hazard-normal tabular-nums">
              {skillGainText}
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <span className="text-[11px] text-text-muted">Held-out test block</span>
            <button
              onClick={() => setActiveTab("skill")}
              className="text-[11px] text-hazard-normal hover:underline font-semibold"
            >
              Skill Curves →
            </button>
          </div>
        </Card>

        {/* KPI 4: Ingest Status */}
        <Card compact>
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-medium text-text-muted">Ingest Status</span>
            <div className="p-1.5 bg-[#E4F5EE] rounded-full">
              <Server className="w-3.5 h-3.5 text-hazard-normal" />
            </div>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-hazard-normal tabular-nums">
              {metaLoading ? "…" : meta?.last_run?.status?.toUpperCase() || "OK"}
            </span>
            <span className="text-xs text-text-muted font-mono">
              {meta?.models ? `${meta.models.length}/${meta.models.length}` : "4/4"}
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between flex-wrap gap-1">
            <span className="text-[11px] text-text-secondary font-mono font-medium">
              {meta?.active_model_version?.id
                ? (meta.active_model_version.previous_version_id && meta.active_model_version.previous_version_id !== meta.active_model_version.id
                    ? `Current version switched: V${meta.active_model_version.previous_version_id} → V${meta.active_model_version.id}`
                    : `Current version V${meta.active_model_version.id}`)
                : "Current version V1"}
            </span>
            <button
              onClick={() => setActiveTab("pipeline")}
              className="text-[11px] text-hazard-normal hover:underline font-semibold"
            >
              Health →
            </button>
          </div>
        </Card>
      </div>

      {/* Main Content: Map (2 cols) + Alerts (1 col) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
        {/* Left 2 Cols: Map */}
        <div className="lg:col-span-2 space-y-4">
          <Card className="p-5">
            <CardHeader className="pb-3 mb-3">
              <div>
                <CardTitle className="text-base">
                  <MapPin className="w-4 h-4 text-accent" />
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
                <ArrowRight className="w-3 h-3" />
              </Button>
            </CardHeader>
            <IndiaForecastMap />
          </Card>
        </div>

        {/* Right 1 Col: Alerts */}
        <div className="space-y-4">
          <Card className="p-5">
            <CardHeader className="pb-3 mb-3">
              <div>
                <CardTitle>
                  <AlertTriangle className="w-4 h-4 text-accent" />
                  <span>Weather Alerts & Events</span>
                </CardTitle>
                <CardDescription>
                  Public hazard guidance calibrated to IMD criteria
                </CardDescription>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant="alert">{activeAlertsCount} ACTIVE</Badge>
              </div>
            </CardHeader>

            {/* Subscriber greeting */}
            {userEmail && mySubscription?.active && (
              <div className="mb-3 p-3 rounded-[14px] bg-[#E8F5EF] border border-[#3D9970]/20 text-xs text-text-primary flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bell className="w-3.5 h-3.5 text-hazard-normal" />
                  <span>
                    Hi, <strong className="font-semibold text-hazard-normal">{extractFirstName(profile?.display_name || user?.user_metadata?.display_name) || "Subscriber"}</strong>{" "}
                    — alerts for your {mySubscription.location_ids.length} saved location(s).
                  </span>
                </div>
                <button
                  onClick={() => setIsGetAlertsOpen(true)}
                  className="text-[11px] text-hazard-normal underline hover:text-hazard-normal/80 font-semibold ml-2 shrink-0"
                >
                  Manage
                </button>
              </div>
            )}

            {/* Window & Severity Pills */}
            <div className="space-y-2.5">
              <div className="flex items-center justify-between text-[11px] text-text-muted">
                <span className="flex items-center gap-1 font-medium">
                  <Clock className="w-3 h-3 text-accent" />
                  <span>Window:</span>
                </span>
                <div className="flex items-center gap-1">
                  <span className="px-1.5 py-0.5 rounded-full bg-[#FDF3DC] text-[#7A5C00] text-[10px] font-mono font-semibold">
                    {advisoryCount} Moderate
                  </span>
                  <span className="px-1.5 py-0.5 rounded-full bg-[#FEE9D6] text-[#7A3300] text-[10px] font-mono font-semibold">
                    {watchCount} High
                  </span>
                  <span className="px-1.5 py-0.5 rounded-full bg-accent-soft text-accent text-[10px] font-mono font-bold">
                    {alertCount} Severe
                  </span>
                </div>
              </div>

              {/* Window toggle pills */}
              <div className="flex flex-wrap gap-1.5">
                <span className="text-[10px] text-text-muted uppercase font-semibold self-center px-1">Upcoming:</span>
                {(["upcoming_2d", "upcoming_3d", "upcoming_7d"] as const).map((w) => (
                  <button
                    key={w}
                    onClick={() => setSelectedWindow(w)}
                    className={`px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 ${
                      selectedWindow === w
                        ? "bg-accent text-white shadow-pill"
                        : "bg-[#F0EDE7] text-text-muted hover:text-text-primary hover:bg-white"
                    }`}
                    title={w === "upcoming_7d" ? "Next 7 days (Default)" : undefined}
                  >
                    {w === "upcoming_2d" ? "2d" : w === "upcoming_3d" ? "3d" : "7d"}
                  </button>
                ))}
                <span className="text-[10px] text-text-muted uppercase font-semibold self-center px-1 ml-1">Past:</span>
                {(["past_24h", "past_7d"] as const).map((w) => (
                  <button
                    key={w}
                    onClick={() => setSelectedWindow(w)}
                    className={`px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 ${
                      selectedWindow === w
                        ? "bg-accent text-white shadow-pill"
                        : "bg-[#F0EDE7] text-text-muted hover:text-text-primary hover:bg-white"
                    }`}
                  >
                    {w === "past_24h" ? "24h" : "7d"}
                  </button>
                ))}
              </div>

              {/* Filters Row */}
              <div className="grid grid-cols-3 gap-1.5 text-[11px]">
                <select
                  value={hazardFilter}
                  onChange={(e) => setHazardFilter(e.target.value)}
                  className={selectClass}
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
                  className={selectClass}
                >
                  <option value="ALL">All Regions</option>
                  <option value="NORTH">North</option>
                  <option value="SOUTH">South</option>
                  <option value="EAST_NE">East/NE</option>
                  <option value="WEST">West</option>
                  <option value="CENTRAL">Central</option>
                </select>

                <select
                  value={severityFilter}
                  onChange={(e) => setSeverityFilter(e.target.value)}
                  className={selectClass}
                >
                  <option value="ALL">All Levels</option>
                  <option value="advisory">Moderate</option>
                  <option value="watch">High</option>
                  <option value="alert">Severe</option>
                </select>
              </div>
            </div>

            {/* Alerts List / Empty State */}
            <div className="space-y-2 mt-3 max-h-[500px] overflow-y-auto pr-0.5">
              {!alertsLoading && rawAlerts.length > 0 && activeAlertsCount > rawAlerts.length && (
                <div className="text-[11px] text-text-muted px-1 flex items-center justify-between">
                  <span>Showing {rawAlerts.length} of {activeAlertsCount} alerts</span>
                  <button
                    onClick={() => setActiveTab("alerts")}
                    className="text-accent hover:underline text-[11px] font-medium"
                  >
                    View all in Center →
                  </button>
                </div>
              )}
              {alertsLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                  <Skeleton className="h-16 w-full" />
                </div>
              ) : rawAlerts.length === 0 ? (
                <div className="p-6 bg-[#F5F2EC] rounded-[16px] text-center text-xs text-text-muted space-y-1">
                  <ShieldCheck className="w-6 h-6 text-hazard-normal mx-auto mb-1.5" />
                  <div className="font-semibold text-text-secondary">{getEmptyStateMessage()}</div>
                  <div className="text-[11px]">All 40 synoptic stations currently within normal thresholds.</div>
                </div>
              ) : (
                rawAlerts.map((alert) => (
                  <AlertCard
                    key={alert.event_id ? `event-${alert.event_id}-${alert.id}` : `alert-${alert.id}`}
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
                  className="w-full text-xs text-accent"
                >
                  <span>View full history in Extreme Weather Center</span>
                  <ArrowRight className="w-3 h-3" />
                </Button>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Alert Event Detail Drawer */}
      <AlertEventDetailDrawer
        eventId={selectedEventId}
        isOpen={drawerOpen}
        onClose={() => {
          setDrawerOpen(false);
          setSelectedEventId(null);
        }}
      />

      {/* Get Alerts / Subscription Dialog */}
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
