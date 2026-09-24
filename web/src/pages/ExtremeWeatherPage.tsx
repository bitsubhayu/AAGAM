import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Search,
} from "lucide-react";
import { useAlerts } from "@/api/useAlerts";
import { AlertCard } from "@/components/alerts/AlertCard";
import { AlertEventDetailDrawer } from "@/components/alerts/AlertEventDetailDrawer";
import { Skeleton } from "@/components/ui/Skeleton";

export const ExtremeWeatherPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<string>("active");
  const [hazardFilter, setHazardFilter] = useState<string>("ALL");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [maxLead, setMaxLead] = useState<number>(3); // 72h default per PRD §10.4
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);

  const { data: alertsData, isLoading, error } = useAlerts({
    status: statusFilter,
    hazard: hazardFilter,
    severity: severityFilter,
    search: searchQuery.trim() || undefined,
    maxLeadDays: maxLead,
    limit: 100,
  });

  const alerts = alertsData?.alerts || [];

  return (
    <div className="space-y-4 font-sans animate-fade-in">
      {/* Page Header & Filter Controls */}
      <div className="bg-surface p-4 rounded-card shadow-card border border-[rgba(26,23,18,0.07)] space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-accent-soft rounded-full">
              <AlertTriangle className="w-4 h-4 text-accent" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-text-primary">
                Extreme Weather Center
              </h2>
              <p className="text-xs text-text-muted">
                Early hazard detection calibrated to official IMD meteorological thresholds
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted">Status:</span>
            <div className="flex items-center bg-[#F0EDE7] p-0.5 rounded-full border border-[rgba(26,23,18,0.09)]">
              {(["active", "acknowledged", "all"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`px-3 py-1 rounded-full text-xs font-semibold capitalize transition-all duration-150 ${
                    statusFilter === s
                      ? "bg-accent text-white shadow-pill"
                      : "text-text-muted hover:text-text-primary"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Filter Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2.5 pt-2.5 border-t border-[rgba(26,23,18,0.07)] text-xs">
          {/* Search */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-text-muted absolute left-3 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search station or region..."
              className="w-full pl-8 pr-3 py-2 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-full text-text-primary outline-none focus:ring-2 focus:ring-accent/30 text-xs"
            />
          </div>

          {/* Hazard Filter */}
          <select
            value={hazardFilter}
            onChange={(e) => setHazardFilter(e.target.value)}
            className="w-full px-3 py-2 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-full text-text-primary outline-none cursor-pointer focus:ring-2 focus:ring-accent/30"
          >
            <option value="ALL">All Hazard Types</option>
            <option value="heavy_rain">Heavy Rainfall (≥ 64.5 mm)</option>
            <option value="heavy_rain_3day">3-Day Heavy Rain (≥ p90)</option>
            <option value="heatwave">Heatwave Criteria</option>
            <option value="high_wind">High Wind / Gale</option>
            <option value="high_uncertainty">High Uncertainty / Spread</option>
          </select>

          {/* Severity Filter */}
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="w-full px-3 py-2 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-full text-text-primary outline-none cursor-pointer focus:ring-2 focus:ring-accent/30"
          >
            <option value="ALL">All Severity Levels</option>
            <option value="advisory">Moderate (Advisory) — Only</option>
            <option value="watch">High (Watch) — Only</option>
            <option value="alert">Severe (Alert) — Only</option>
          </select>

          {/* Lead Window */}
          <select
            value={maxLead}
            onChange={(e) => setMaxLead(parseInt(e.target.value, 10))}
            className="w-full px-3 py-2 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-full text-text-primary outline-none cursor-pointer focus:ring-2 focus:ring-accent/30 font-mono"
          >
            <option value={1}>Within Next 24 Hours (D+1)</option>
            <option value={2}>Within Next 48 Hours (D+2)</option>
            <option value={3}>Within Next 72 Hours (D+3 - Default)</option>
            <option value={5}>Within Next 5 Days (D+5)</option>
            <option value={7}>Full 7-Day Lead Window</option>
          </select>
        </div>
      </div>

      {/* Alert Cards Feed */}
      <div className="space-y-3">
        {isLoading ? (
          <div className="space-y-2.5">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        ) : error ? (
          <div className="p-8 bg-surface rounded-card shadow-card border border-[rgba(26,23,18,0.07)] text-center text-xs text-text-muted">
            <AlertTriangle className="w-8 h-8 text-hazard-advisory mx-auto mb-2" />
            Failed to retrieve extreme weather alerts.
          </div>
        ) : alerts.length === 0 ? (
          <div className="p-12 bg-surface rounded-card shadow-card border border-[rgba(26,23,18,0.07)] text-center text-xs text-text-muted space-y-2">
            <CheckCircle2 className="w-10 h-10 text-hazard-normal mx-auto" />
            <p className="text-sm font-semibold text-text-primary">
              No extreme weather alert events matching current filter criteria.
            </p>
            <p className="max-w-md mx-auto text-[11px]">
              Multi-model ensemble consensus indicates normal meteorological parameters across the
              selected forecast lead window.
            </p>
          </div>
        ) : (
          <div className="space-y-2.5">
            <div className="flex items-center justify-between text-xs text-text-muted px-1">
              <span>
                Showing {alerts.length}
                {alertsData?.count !== undefined && alertsData.count > alerts.length
                  ? ` of ${alertsData.count}`
                  : ""}{" "}
                active alert events
              </span>
              <span className="font-mono text-[11px]">IMD Threshold Grounded</span>
            </div>
            {alerts.map((alert) => (
              <AlertCard
                key={alert.event_id ? `event-${alert.event_id}-${alert.id}` : `alert-${alert.id}`}
                alert={alert}
                onSelectEvent={(eventId) => setSelectedEventId(eventId)}
              />
            ))}
          </div>
        )}
      </div>

      <AlertEventDetailDrawer
        eventId={selectedEventId}
        isOpen={selectedEventId !== null}
        onClose={() => setSelectedEventId(null)}
      />
    </div>
  );
};
