import React, { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Search,
} from "lucide-react";
import { useAlerts } from "@/api/useAlerts";
import { AlertCard } from "@/components/alerts/AlertCard";
import { Skeleton } from "@/components/ui/Skeleton";

export const ExtremeWeatherPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<string>("active");
  const [hazardFilter, setHazardFilter] = useState<string>("ALL");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [maxLead, setMaxLead] = useState<number>(3); // 72h default per PRD §10.4
  const [searchQuery, setSearchQuery] = useState("");

  const { data: alertsData, isLoading, error } = useAlerts({
    status: statusFilter,
    hazard: hazardFilter,
    minSeverity: severityFilter,
    maxLeadDays: maxLead,
    limit: 100,
  });

  const alerts = alertsData?.alerts || [];

  const filteredAlerts = alerts.filter(
    (a) =>
      a.location_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      a.region.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-4 font-sans">
      {/* Page Header & Filter Controls */}
      <div className="bg-[#161b22] p-3.5 rounded-lg border border-border space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <div className="p-1.5 bg-orange-500/10 border border-orange-500/30 rounded text-brand-orange">
              <AlertTriangle className="w-4 h-4 text-hazard-watch" />
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
            <div className="flex items-center bg-[#21262d] p-0.5 rounded border border-border">
              {(["active", "acknowledged", "all"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`px-2.5 py-1 rounded text-xs font-medium capitalize transition-colors ${
                    statusFilter === s
                      ? "bg-brand-blue text-white"
                      : "text-text-muted hover:text-text-secondary"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Filter Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-2.5 pt-2 border-t border-border/60 text-xs">
          {/* Search */}
          <div className="relative">
            <Search className="w-3.5 h-3.5 text-text-muted absolute left-2.5 top-2.5" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search station or region..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#21262d] border border-border rounded text-text-primary outline-none focus:ring-1 focus:ring-brand-blue"
            />
          </div>

          {/* Hazard Filter */}
          <div>
            <select
              value={hazardFilter}
              onChange={(e) => setHazardFilter(e.target.value)}
              className="w-full px-2.5 py-1.5 bg-[#21262d] border border-border rounded text-text-primary outline-none"
            >
              <option value="ALL">All Hazard Types</option>
              <option value="heavy_rain">Heavy Rainfall (≥ 64.5 mm)</option>
              <option value="heavy_rain_3day">3-Day Heavy Rain (≥ p90)</option>
              <option value="heatwave">Heatwave Criteria</option>
              <option value="high_wind">High Wind / Gale</option>
            </select>
          </div>

          {/* Severity Filter */}
          <div>
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="w-full px-2.5 py-1.5 bg-[#21262d] border border-border rounded text-text-primary outline-none"
            >
              <option value="ALL">All Severity Levels</option>
              <option value="alert">Alert (Severe)</option>
              <option value="watch">Watch (High)</option>
              <option value="advisory">Advisory (Moderate)</option>
            </select>
          </div>

          {/* Lead Window */}
          <div>
            <select
              value={maxLead}
              onChange={(e) => setMaxLead(parseInt(e.target.value, 10))}
              className="w-full px-2.5 py-1.5 bg-[#21262d] border border-border rounded text-text-primary outline-none font-mono"
            >
              <option value={1}>Within Next 24 Hours (D+1)</option>
              <option value={2}>Within Next 48 Hours (D+2)</option>
              <option value={3}>Within Next 72 Hours (D+3 - Default)</option>
              <option value={5}>Within Next 5 Days (D+5)</option>
              <option value={7}>Full 7-Day Lead Window</option>
            </select>
          </div>
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
          <div className="p-8 bg-[#161b22] border border-border rounded-lg text-center text-xs text-text-muted">
            <AlertTriangle className="w-8 h-8 text-hazard-advisory mx-auto mb-2" />
            Failed to retrieve extreme weather alerts.
          </div>
        ) : filteredAlerts.length === 0 ? (
          <div className="p-12 bg-[#161b22] border border-border rounded-lg text-center text-xs text-text-muted space-y-2">
            <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto" />
            <p className="text-sm font-semibold text-text-primary">
              No extreme weather flags matching current filter criteria.
            </p>
            <p className="max-w-md mx-auto text-[11px]">
              Multi-model ensemble consensus indicates normal meteorological parameters across the
              selected forecast lead window.
            </p>
          </div>
        ) : (
          <div className="space-y-2.5">
            <div className="flex items-center justify-between text-xs text-text-muted px-1">
              <span>Showing {filteredAlerts.length} hazard alerts</span>
              <span className="font-mono text-[11px]">IMD Threshold Grounded</span>
            </div>
            {filteredAlerts.map((alert) => (
              <AlertCard key={alert.id} alert={alert} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
