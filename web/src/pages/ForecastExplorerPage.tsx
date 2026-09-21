import React, { useState } from "react";
import {
  TrendingUp,
  Search,
  Sparkles,
  Copy,
  Check,
  AlertCircle,
  Eye,
  EyeOff,
} from "lucide-react";
import { useUIStore, VARIABLES } from "@/store/uiStore";
import { useForecast } from "@/api/useForecast";
import { useMeta } from "@/api/useMeta";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ForecastChart } from "@/components/charts/ForecastChart";
import { toast } from "sonner";

export const ForecastExplorerPage: React.FC = () => {
  const {
    selectedLocationSlug,
    setSelectedLocationSlug,
    selectedVariable,
    openAssistantWithPrompt,
  } = useUIStore();

  const { data: meta } = useMeta();
  const { data: forecast, isLoading, error } = useForecast(
    selectedLocationSlug,
    selectedVariable
  );

  const [searchTerm] = useState("");
  const [showEnvelope, setShowEnvelope] = useState(true);
  const [showThresholds, setShowThresholds] = useState(true);
  const [copied, setCopied] = useState(false);

  const [visibleModels, setVisibleModels] = useState({
    gfs: true,
    ecmwf_ifs: true,
    icon: true,
    aifs: true,
    blended: true,
  });

  const varMeta = VARIABLES[selectedVariable];
  const locations = meta?.locations || [];

  const filteredLocations = locations.filter(
    (loc) =>
      loc.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      loc.slug.toLowerCase().includes(searchTerm.toLowerCase()) ||
      loc.region.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const currentLocation = locations.find((l) => l.slug === selectedLocationSlug);

  const toggleModel = (m: keyof typeof visibleModels) => {
    setVisibleModels((prev) => ({ ...prev, [m]: !prev[m] }));
  };

  const copyTableAsCsv = () => {
    if (!forecast?.series) return;
    const headers = ["Valid Date", "Lead Days", "Blended", "GFS", "ECMWF IFS", "DWD ICON", "ECMWF AIFS", "Spread"];
    const rows = forecast.series.map((s) => [
      s.valid_date,
      s.lead_days,
      s.blended.toFixed(1),
      s.models?.gfs ?? "",
      s.models?.ecmwf_ifs ?? "",
      s.models?.icon ?? "",
      s.models?.aifs ?? "",
      s.spread.toFixed(1),
    ]);

    const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    navigator.clipboard.writeText(csvContent);
    setCopied(true);
    toast.success("Table copied to clipboard as CSV");
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-4 font-sans">
      {/* Controls Bar: Location Search & Model Toggles */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        {/* Search & Location Picker */}
        <div className="md:col-span-2 relative">
          <label className="block text-[11px] font-semibold text-text-muted mb-1">
            Station Location (40 Rep Points):
          </label>
          <div className="relative">
            <Search className="w-4 h-4 text-text-muted absolute left-3 top-2.5" />
            <select
              value={selectedLocationSlug}
              onChange={(e) => setSelectedLocationSlug(e.target.value)}
              className="w-full pl-9 pr-3 py-2 bg-[#161b22] border border-border rounded-md text-xs text-text-primary focus:ring-2 focus:ring-brand-blue/50 outline-none"
            >
              {filteredLocations.map((loc) => (
                <option key={loc.slug} value={loc.slug}>
                  {loc.name} ({loc.region} · {loc.terrain || "plain"})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Display Toggles */}
        <div className="md:col-span-2 flex items-end gap-2">
          <Button
            variant={showEnvelope ? "primary" : "secondary"}
            size="sm"
            onClick={() => setShowEnvelope(!showEnvelope)}
            className="text-xs"
          >
            {showEnvelope ? <Eye className="w-3.5 h-3.5 mr-1" /> : <EyeOff className="w-3.5 h-3.5 mr-1" />}
            <span>Uncertainty Envelope</span>
          </Button>

          <Button
            variant={showThresholds ? "secondary" : "outline"}
            size="sm"
            onClick={() => setShowThresholds(!showThresholds)}
            className="text-xs"
          >
            <span>IMD Thresholds</span>
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              openAssistantWithPrompt(
                `Analyze the multi-model spread for ${currentLocation?.name || selectedLocationSlug} across lead days 0 to 7.`
              )
            }
            className="ml-auto text-brand-blue border-brand-blue/30"
          >
            <Sparkles className="w-3.5 h-3.5 mr-1 text-brand-orange" />
            <span>Ask AAGAM</span>
          </Button>
        </div>
      </div>

      {/* Main Chart Card */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <TrendingUp className="w-4 h-4 text-brand-blue" />
              <span>Multi-Model Lead Time Evolution: {currentLocation?.name || selectedLocationSlug}</span>
              <Badge variant="outline">{currentLocation?.region || "INDIA"}</Badge>
            </CardTitle>
            <CardDescription>
              {varMeta.label} ({varMeta.unit}) · Valid Lead Days D0 through D7
            </CardDescription>
          </div>

          {/* Model Toggle Chips */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={() => toggleModel("blended")}
              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-all ${
                visibleModels.blended
                  ? "bg-brand-blue/20 text-brand-blue border-brand-blue"
                  : "bg-transparent text-text-muted border-border opacity-50"
              }`}
            >
              ● AAGAM Blend
            </button>
            <button
              onClick={() => toggleModel("gfs")}
              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-all ${
                visibleModels.gfs
                  ? "bg-blue-950/40 text-model-gfs border-blue-700"
                  : "bg-transparent text-text-muted border-border opacity-50"
              }`}
            >
              ● GFS
            </button>
            <button
              onClick={() => toggleModel("ecmwf_ifs")}
              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-all ${
                visibleModels.ecmwf_ifs
                  ? "bg-emerald-950/40 text-model-ifs border-emerald-700"
                  : "bg-transparent text-text-muted border-border opacity-50"
              }`}
            >
              ● ECMWF IFS
            </button>
            <button
              onClick={() => toggleModel("icon")}
              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-all ${
                visibleModels.icon
                  ? "bg-amber-950/40 text-model-icon border-amber-700"
                  : "bg-transparent text-text-muted border-border opacity-50"
              }`}
            >
              ● ICON
            </button>
            <button
              onClick={() => toggleModel("aifs")}
              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-all ${
                visibleModels.aifs
                  ? "bg-purple-950/40 text-model-aifs border-purple-700"
                  : "bg-transparent text-text-muted border-border opacity-50"
              }`}
            >
              ● AIFS (AI)
            </button>
          </div>
        </CardHeader>

        {isLoading ? (
          <div className="py-12 flex flex-col items-center justify-center">
            <Skeleton className="h-64 w-full" />
          </div>
        ) : error || !forecast?.series ? (
          <div className="py-12 text-center text-xs text-text-muted">
            <AlertCircle className="w-6 h-6 text-hazard-advisory mx-auto mb-2" />
            Unable to retrieve forecast data. Verify API connectivity.
          </div>
        ) : (
          <ForecastChart
            series={forecast.series}
            variable={selectedVariable}
            locationName={currentLocation?.name || selectedLocationSlug}
            showEnvelope={showEnvelope}
            showThresholds={showThresholds}
            visibleModels={visibleModels}
          />
        )}
      </Card>

      {/* Exact Values Table (PRD §10.4 FR-UI-2) */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>Exact Numerical Multi-Model Matrix</CardTitle>
            <CardDescription>
              Tabular values with lead time and multi-model agreement
            </CardDescription>
          </div>

          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={copyTableAsCsv}>
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400 mr-1" /> : <Copy className="w-3.5 h-3.5 mr-1" />}
              <span>{copied ? "Copied" : "Copy CSV"}</span>
            </Button>
          </div>
        </CardHeader>

        {forecast?.series && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead>
                <tr className="border-b border-border bg-[#161b22] text-text-muted font-mono">
                  <th className="p-2.5">Valid Date (IST)</th>
                  <th className="p-2.5">Lead</th>
                  <th className="p-2.5 text-brand-blue font-bold">AAGAM Blend</th>
                  <th className="p-2.5 text-model-gfs">GFS (NOAA)</th>
                  <th className="p-2.5 text-model-ifs">ECMWF IFS</th>
                  <th className="p-2.5 text-model-icon">DWD ICON</th>
                  <th className="p-2.5 text-model-aifs">ECMWF AIFS</th>
                  <th className="p-2.5">Spread (σ)</th>
                  <th className="p-2.5">Exceedance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60 font-mono text-[11px]">
                {forecast.series.map((s) => (
                  <tr key={s.valid_date} className="hover:bg-[#21262d]/50 transition-colors">
                    <td className="p-2.5 font-sans font-medium text-text-primary">
                      {s.valid_date}
                    </td>
                    <td className="p-2.5 text-text-secondary">+{s.lead_days}d</td>
                    <td className="p-2.5 text-brand-blue font-bold text-xs">
                      {s.blended.toFixed(1)} {varMeta.shortUnit}
                    </td>
                    <td className="p-2.5 text-text-secondary">
                      {s.models?.gfs !== undefined ? s.models.gfs.toFixed(1) : "—"}
                    </td>
                    <td className="p-2.5 text-text-secondary">
                      {s.models?.ecmwf_ifs !== undefined ? s.models.ecmwf_ifs.toFixed(1) : "—"}
                    </td>
                    <td className="p-2.5 text-text-secondary">
                      {s.models?.icon !== undefined ? s.models.icon.toFixed(1) : "—"}
                    </td>
                    <td className="p-2.5 text-text-secondary">
                      {s.models?.aifs !== undefined ? s.models.aifs.toFixed(1) : "—"}
                    </td>
                    <td className="p-2.5 text-text-muted">
                      {s.spread.toFixed(1)}
                    </td>
                    <td className="p-2.5">
                      {s.models_over_threshold > 0 ? (
                        <span className="text-hazard-advisory font-semibold">
                          {s.models_over_threshold}/4 over threshold
                        </span>
                      ) : (
                        <span className="text-text-muted">Below threshold</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};
