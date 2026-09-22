import React from "react";
import {
  X,
  AlertTriangle,
  CloudRain,
  Flame,
  Wind,
  Calendar,
  MapPin,
  Activity,
  Info,
  Check,
  HelpCircle,
  ExternalLink,
  ShieldCheck,
  Share2,
  Copy,
  Send,
  Sparkles,
} from "lucide-react";
import { useAlertEvent, useAcknowledgeAlertEvent } from "@/api/useAlerts";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useAuthStore } from "@/auth/authStore";
import { toast } from "sonner";

interface AlertEventDetailDrawerProps {
  eventId: number | null;
  isOpen: boolean;
  onClose: () => void;
}

export const AlertEventDetailDrawer: React.FC<AlertEventDetailDrawerProps> = ({
  eventId,
  isOpen,
  onClose,
}) => {
  const { role } = useAuthStore();
  const { data, isLoading, error } = useAlertEvent(isOpen ? eventId : null);
  const ackMutation = useAcknowledgeAlertEvent();

  if (!isOpen) return null;

  const event = data?.event;
  const childAlerts = data?.alerts || [];
  const lifecycleHistory = data?.lifecycle_history || [];

  const hasActiveAlerts = childAlerts.some((a) => a.status === "active");
  const isFullyAcknowledged = childAlerts.length > 0 && childAlerts.every((a) => a.status === "acknowledged");
  const canAck = (role === "forecaster" || role === "admin") && event?.status === "active" && hasActiveAlerts;

  const getHazardIcon = (hazard?: string) => {
    switch (hazard) {
      case "heavy_rain":
      case "heavy_rain_3day":
        return <CloudRain className="w-5 h-5 text-blue-400" />;
      case "heatwave":
        return <Flame className="w-5 h-5 text-orange-400" />;
      case "high_wind":
        return <Wind className="w-5 h-5 text-cyan-400" />;
      default:
        return <AlertTriangle className="w-5 h-5 text-amber-400" />;
    }
  };

  const getSeverityVariant = (sev?: string): "alert" | "watch" | "advisory" => {
    if (sev === "alert") return "alert";
    if (sev === "watch") return "watch";
    return "advisory";
  };

  const handleAcknowledge = async () => {
    if (!eventId || !canAck) return;
    try {
      await ackMutation.mutateAsync(eventId);
      toast.success(`Alert Event #${eventId} acknowledged.`);
    } catch (err: any) {
      toast.error(`Failed to acknowledge event: ${err.message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-in fade-in">
      <div className="relative w-full max-w-xl h-full bg-[#161b22] border-l border-border flex flex-col shadow-2xl overflow-hidden font-sans">
        {/* Drawer Header */}
        <div className="p-4 border-b border-border flex items-start justify-between gap-3 bg-[#0d1117]/80">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-[#21262d] rounded-lg border border-border">
              {getHazardIcon(event?.hazard)}
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-bold text-text-primary">
                  {event ? `Alert Event #${event.id}` : "Alert Event Detail"}
                </h3>
                {event && (
                  <>
                    <Badge variant={getSeverityVariant(event.severity_peak)} showIcon>
                      {event.severity_peak.toUpperCase()}
                    </Badge>
                    <Badge variant="outline" className="capitalize text-[11px]">
                      {event.status}
                    </Badge>
                    {isFullyAcknowledged && (
                      <span className="text-[10px] font-medium text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-1.5 py-0.5 rounded flex items-center gap-1">
                        <Check className="w-3 h-3" />
                        <span>Acknowledged</span>
                      </span>
                    )}
                  </>
                )}
              </div>
              <p className="text-xs text-text-muted mt-0.5 flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5 text-brand-blue" />
                <span>{event?.location_name || "..."} ({event?.region})</span>
                <span>•</span>
                <span className="capitalize">{event?.hazard.replace("_", " ")}</span>
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-text-muted hover:text-text-primary hover:bg-[#21262d] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Drawer Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-5 text-xs">
          {isLoading ? (
            <div className="space-y-4 animate-pulse">
              <div className="h-20 bg-[#21262d] rounded-lg" />
              <div className="h-32 bg-[#21262d] rounded-lg" />
              <div className="h-40 bg-[#21262d] rounded-lg" />
            </div>
          ) : error || !event ? (
            <div className="p-6 text-center text-rose-400 bg-rose-500/10 border border-rose-500/30 rounded-lg">
              Failed to load alert event details.
            </div>
          ) : (
            <>
              {/* Event Overview Card */}
              <div className="p-3.5 bg-[#21262d]/70 rounded-lg border border-border grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                <div>
                  <span className="text-[11px] text-text-muted block">Duration</span>
                  <span className="font-semibold text-text-primary font-mono text-xs">
                    {event.start_date === event.end_date
                      ? event.start_date
                      : `${event.start_date} → ${event.end_date}`}
                  </span>
                </div>
                <div>
                  <span className="text-[11px] text-text-muted block">Peak Intensity</span>
                  <span className="font-semibold text-text-primary font-mono text-xs">
                    {event.value_peak !== null && event.value_peak !== undefined ? event.value_peak : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-[11px] text-text-muted block">First Detected</span>
                  <span className="font-semibold text-text-primary font-mono text-xs">
                    {event.first_detected_at ? new Date(event.first_detected_at).toLocaleDateString() : "—"}
                  </span>
                </div>
                <div>
                  <span className="text-[11px] text-text-muted block">Outcome</span>
                  <span className="font-semibold font-mono text-xs capitalize text-emerald-400">
                    {event.outcome}
                  </span>
                </div>
              </div>

              {/* 1. Lifecycle Strip (PRD §10.4 FR-UI-5) */}
              <div className="space-y-2.5">
                <div className="flex items-center gap-1.5 text-text-primary font-semibold text-xs border-b border-border/60 pb-1.5">
                  <Activity className="w-4 h-4 text-brand-blue" />
                  <span>Lifecycle Timeline</span>
                </div>

                {lifecycleHistory.length === 0 ? (
                  <div className="p-3 bg-[#21262d]/40 rounded border border-border text-text-muted text-[11px]">
                    No recorded lifecycle transitions yet.
                  </div>
                ) : (
                  <div className="relative pl-6 space-y-3 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-border">
                    {lifecycleHistory.map((node, i) => {
                      const isLatest = i === 0;
                      return (
                        <div key={i} className="relative group">
                          <div
                            className={`absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full border ${
                              isLatest
                                ? "bg-brand-blue border-brand-blue ring-4 ring-brand-blue/20"
                                : "bg-[#21262d] border-text-muted"
                            }`}
                          />
                          <div className="p-2.5 rounded bg-[#21262d]/50 border border-border/80 flex items-center justify-between gap-2">
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-bold text-text-primary uppercase text-[11px]">
                                  {node.lifecycle_state}
                                </span>
                                <Badge variant={getSeverityVariant(node.severity)} className="text-[10px] py-0">
                                  {node.severity}
                                </Badge>
                                {node.previous_severity && (
                                  <span className="text-[10px] text-text-muted">
                                    from {node.previous_severity}
                                  </span>
                                )}
                              </div>
                              <span className="text-[10px] text-text-muted font-mono block mt-0.5">
                                Valid: {node.valid_date} • Value: {node.value ?? "—"}
                              </span>
                            </div>
                            <span className="text-[10px] text-text-muted font-mono whitespace-nowrap">
                              {new Date(node.issue_time).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* 2. Why Flagged (PRD §10.4 FR-UI-5) */}
              <div className="space-y-2.5">
                <div className="flex items-center gap-1.5 text-text-primary font-semibold text-xs border-b border-border/60 pb-1.5">
                  <Info className="w-4 h-4 text-brand-orange" />
                  <span>Why Flagged (Meteorological Rules & Consensus)</span>
                </div>

                {childAlerts.map((alert) => (
                  <div key={alert.id} className="p-3 bg-[#21262d]/60 rounded-lg border border-border space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Calendar className="w-3.5 h-3.5 text-text-muted" />
                        <span className="font-bold text-text-primary font-mono">{alert.valid_date}</span>
                        <span className="text-text-muted text-[11px]">(Lead D+{alert.lead_days})</span>
                      </div>
                      <Badge variant={getSeverityVariant(alert.severity)} className="text-[10px]">
                        {alert.severity}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-[11px] pt-1">
                      <div className="bg-[#161b22] p-2 rounded border border-border/60">
                        <span className="text-text-muted block text-[10px]">Consensus Value</span>
                        <span className="font-bold text-text-primary font-mono">{alert.value ?? "—"}</span>
                      </div>
                      <div className="bg-[#161b22] p-2 rounded border border-border/60">
                        <span className="text-text-muted block text-[10px]">Model Agreement</span>
                        <span className="font-bold text-text-primary font-mono">
                          {alert.models_over} / 4 models
                        </span>
                      </div>
                      <div className="bg-[#161b22] p-2 rounded border border-border/60">
                        <span className="text-text-muted block text-[10px]">Forecast Spread</span>
                        <span className="font-bold text-text-primary font-mono">±{alert.spread ?? "—"}</span>
                      </div>
                    </div>

                    {alert.rule && (
                      <div className="p-2 bg-[#161b22] rounded border border-border/60 text-[11px] font-mono text-text-secondary space-y-1">
                        <div className="text-[10px] text-text-muted uppercase">Rule Evaluation:</div>
                        {typeof alert.rule === "object" ? (
                          <ul className="space-y-0.5 list-disc list-inside">
                            {Object.entries(alert.rule).map(([k, v]) => (
                              <li key={k}>
                                <span className="text-text-muted">{k}:</span> {JSON.stringify(v)}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <div>{String(alert.rule)}</div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* 3. How Unusual (PRD §10.4 FR-UI-5, Feature G - Climatology & Local Extremeness) */}
              {(data?.rarity_context || data?.rarity_label || childAlerts.some((a) => a.rarity_label)) && (
                <div className="space-y-2.5 p-3.5 bg-gradient-to-br from-[#1b2333]/80 to-[#161b22] rounded-lg border border-brand-blue/30 shadow-sm">
                  <div className="flex items-center justify-between border-b border-border/60 pb-2">
                    <div className="flex items-center gap-1.5 text-text-primary font-semibold text-xs">
                      <Sparkles className="w-4 h-4 text-brand-blue" />
                      <span>How unusual (Local Extremeness)</span>
                    </div>
                    <span className="text-[10px] text-brand-blue/90 uppercase tracking-wider font-mono font-semibold bg-brand-blue/10 px-1.5 py-0.5 rounded border border-brand-blue/20">
                      15+ Year Climatology
                    </span>
                  </div>

                  <div className="pt-1 space-y-1.5">
                    <p className="text-xs font-semibold text-text-primary flex items-center gap-2">
                      <span>{data?.rarity_context || `Also unusual for this location — ${data?.rarity_label || childAlerts.find((a) => a.rarity_label)?.rarity_label}`}</span>
                    </p>
                    <p className="text-[11px] text-text-muted leading-relaxed">
                      Evaluated against the station&apos;s historical day-of-year distribution (±7-day window) across qualifying years of truth observations.
                    </p>
                  </div>
                </div>
              )}

              {/* 4. What This Means (PRD §10.4 FR-UI-5, Feature C) */}
              {data?.guidance && (
                <div className="space-y-2.5 p-3.5 bg-[#21262d]/50 rounded-lg border border-border">
                  <div className="flex items-center justify-between border-b border-border/60 pb-2">
                    <div className="flex items-center gap-1.5 text-text-primary font-semibold text-xs">
                      <HelpCircle className="w-4 h-4 text-emerald-400" />
                      <span>What this means</span>
                    </div>
                    <span className="text-[10px] text-text-muted uppercase tracking-wider font-mono">
                      IMD Calibrated
                    </span>
                  </div>

                  <div className="space-y-2 pt-1">
                    <h4 className="text-xs font-bold text-text-primary">
                      {data.guidance.headline}
                    </h4>
                    <p className="text-[11px] text-text-secondary leading-relaxed">
                      {data.guidance.body}
                    </p>

                    {data.guidance.precautions && data.guidance.precautions.length > 0 && (
                      <div className="space-y-1 pt-1">
                        <span className="text-[10px] font-semibold text-text-muted uppercase tracking-wider block">
                          Recommended Precautions:
                        </span>
                        <ul className="space-y-1 text-[11px] text-text-secondary list-disc list-inside">
                          {data.guidance.precautions.map((p, idx) => (
                            <li key={idx} className="leading-normal">
                              {p}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <div className="pt-2 border-t border-border/40 flex items-center justify-between">
                      <a
                        href={data.guidance.official_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[11px] text-brand-blue hover:underline inline-flex items-center gap-1 font-medium"
                      >
                        <span>Official IMD Warning Portal (GIS)</span>
                        <ExternalLink className="w-3 h-3" />
                      </a>
                      <span className="text-[10px] text-text-muted">
                        Decision support, not official warning
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* 5. Track Record (PRD §10.4 FR-UI-5, Feature A) */}
              {data?.track_record && (
                <div className="space-y-2.5 p-3.5 bg-[#21262d]/50 rounded-lg border border-border">
                  <div className="flex items-center justify-between border-b border-border/60 pb-2">
                    <div className="flex items-center gap-1.5 text-text-primary font-semibold text-xs">
                      <ShieldCheck className="w-4 h-4 text-brand-teal" />
                      <span>Historical Track Record (180 Days)</span>
                    </div>
                    <span className="text-[10px] text-text-muted font-mono">
                      Region: {event.region}
                    </span>
                  </div>

                  {!data.track_record.applicable ? (
                    <div className="p-2.5 rounded bg-[#161b22] border border-border/60 text-text-muted text-[11px]">
                      {data.track_record.summary_text}
                    </div>
                  ) : data.track_record.low_sample ? (
                    <div className="p-2.5 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300 text-[11px] space-y-1">
                      <div className="font-semibold flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>Early Sample Data (n &lt; 5)</span>
                      </div>
                      <p className="text-[10px] text-amber-200/80">
                        {data.track_record.summary_text} (Evaluated {data.track_record.n} past events in last 180 days).
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="flex items-baseline justify-between">
                        <span className="text-xs text-text-primary font-medium">
                          {data.track_record.summary_text}
                        </span>
                        <span className="text-base font-bold font-mono text-emerald-400">
                          {data.track_record.hit_rate !== null && data.track_record.hit_rate !== undefined
                            ? `${(data.track_record.hit_rate * 100).toFixed(0)}%`
                            : "—"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] font-mono text-text-muted">
                        <span className="px-2 py-0.5 rounded bg-[#161b22] border border-border">
                          Hits: {data.track_record.hits}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-[#161b22] border border-border">
                          False Alarms: {data.track_record.false_alarms}
                        </span>
                        <span className="px-2 py-0.5 rounded bg-[#161b22] border border-border">
                          Total (n): {data.track_record.n}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* 6. Share (PRD §10.4 FR-UI-5, Feature F) */}
              <div className="space-y-2 p-3.5 bg-[#21262d]/50 rounded-lg border border-border">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5 text-text-primary font-semibold text-xs">
                    <Share2 className="w-4 h-4 text-brand-orange" />
                    <span>Share Alert Event (Public URL)</span>
                  </div>
                  <span className="text-[10px] text-text-muted">
                    No login required
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const url = `${window.location.origin}/alerts/e/${event.id}`;
                      navigator.clipboard.writeText(url);
                      toast.success("Permanent event link copied to clipboard!");
                    }}
                    className="text-xs h-7 gap-1"
                  >
                    <Copy className="w-3 h-3" />
                    <span>Copy Link</span>
                  </Button>

                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      if (data?.share_text) {
                        navigator.clipboard.writeText(data.share_text);
                        toast.success("Share text copied to clipboard!");
                      }
                    }}
                    className="text-xs h-7 gap-1"
                  >
                    <Copy className="w-3 h-3" />
                    <span>Copy Text</span>
                  </Button>

                  <a
                    href={`https://api.whatsapp.com/send?text=${encodeURIComponent(
                      data?.share_text
                        ? data.share_text.replace(
                            `/alerts/e/${event.id}`,
                            `${window.location.origin}/alerts/e/${event.id}`
                          )
                        : `${window.location.origin}/alerts/e/${event.id}`
                    )}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-md bg-emerald-600/80 hover:bg-emerald-600 text-white h-7 transition-colors"
                  >
                    <Send className="w-3 h-3" />
                    <span>Share on WhatsApp</span>
                  </a>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Drawer Footer / Forecaster Actions */}
        <div className="p-3.5 border-t border-border bg-[#0d1117]/80 flex items-center justify-between gap-3">
          <span className="text-[11px] text-text-muted">
            Decision support calibrated to IMD thresholds.
          </span>
          <div className="flex items-center gap-2">
            {isFullyAcknowledged && (
              <span className="text-xs text-emerald-400 font-medium flex items-center gap-1 mr-2">
                <Check className="w-3.5 h-3.5" />
                <span>Acknowledged</span>
              </span>
            )}
            {canAck && (
              <Button
                size="sm"
                variant="outline"
                onClick={handleAcknowledge}
                disabled={ackMutation.isPending}
                className="text-xs text-emerald-400 border-emerald-500/40 hover:bg-emerald-500/10"
              >
                <Check className="w-3.5 h-3.5 mr-1" />
                <span>{ackMutation.isPending ? "Acknowledging..." : "Acknowledge Event"}</span>
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onClose} className="text-xs">
              Close
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
