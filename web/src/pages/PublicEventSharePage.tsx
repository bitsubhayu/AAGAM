import React from "react";
import {
  AlertTriangle,
  CloudRain,
  Flame,
  Wind,
  Calendar,
  MapPin,
  Activity,
  Info,
  HelpCircle,
  ExternalLink,
  ShieldCheck,
  Share2,
  Copy,
  Send,
  ArrowLeft,
  CheckCircle2,
  XCircle,
  Sparkles,
} from "lucide-react";
import { useAlertEvent } from "@/api/useAlerts";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

interface PublicEventSharePageProps {
  eventId: number;
  onNavigateHome?: () => void;
}

export const PublicEventSharePage: React.FC<PublicEventSharePageProps> = ({
  eventId,
  onNavigateHome,
}) => {
  const { data, isLoading, error } = useAlertEvent(eventId);

  const event = data?.event;
  const childAlerts = data?.alerts || [];
  const lifecycleHistory = data?.lifecycle_history || [];

  const getHazardIcon = (hazard?: string) => {
    switch (hazard) {
      case "heavy_rain":
      case "heavy_rain_3day":
        return <CloudRain className="w-6 h-6 text-blue-400" />;
      case "heatwave":
        return <Flame className="w-6 h-6 text-orange-400" />;
      case "high_wind":
        return <Wind className="w-6 h-6 text-cyan-400" />;
      default:
        return <AlertTriangle className="w-6 h-6 text-amber-400" />;
    }
  };

  const getSeverityVariant = (sev?: string): "alert" | "watch" | "advisory" => {
    if (sev === "alert") return "alert";
    if (sev === "watch") return "watch";
    return "advisory";
  };

  const handleCopyLink = () => {
    const url = `${window.location.origin}/alerts/e/${eventId}`;
    navigator.clipboard.writeText(url);
    toast.success("Permanent event URL copied to clipboard!");
  };

  const handleCopyText = () => {
    if (data?.share_text) {
      navigator.clipboard.writeText(data.share_text);
      toast.success("Share text copied to clipboard!");
    }
  };

  return (
    <div className="min-h-screen bg-canvas text-text-primary flex flex-col font-sans select-text">
      {/* Top Banner */}
      <header className="border-b border-[rgba(26,23,18,0.10)] bg-surface/90 backdrop-blur sticky top-0 z-40 px-4 py-3">
        <div className="max-w-4xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-brand-teal/20 border border-brand-teal/40 flex items-center justify-center font-mono font-bold text-brand-teal text-sm">
              AG
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-sm text-text-primary tracking-wide">
                  AAGAM
                </span>
                <span className="text-[11px] text-text-muted hidden sm:inline">
                  Adaptive AI-Grid Assimilation Model
                </span>
              </div>
              <p className="text-[10px] text-brand-teal font-mono">
                Official Incident Verification &amp; Decision Support
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (onNavigateHome) {
                  onNavigateHome();
                } else {
                  window.location.href = "/";
                }
              }}
              className="text-xs h-8 gap-1.5"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Live Workstation</span>
            </Button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto p-4 sm:p-6 space-y-6">
        {/* Decision Support Disclaimer */}
        <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-300 text-xs flex items-start gap-2.5">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="space-y-0.5">
            <span className="font-bold uppercase tracking-wider text-[10px] block">
              Decision Support Notice (PRD §10.5)
            </span>
            <p className="text-[11px] text-amber-200/90 leading-relaxed">
              AAGAM provides multi-model numerical guidance calibrated to IMD thresholds. This is not an official government warning. Refer to the official India Meteorological Department portal for statutory warnings.
            </p>
          </div>
        </div>

        {isLoading ? (
          <div className="p-12 text-center text-text-muted animate-pulse space-y-3">
            <div className="h-6 w-48 bg-[#F0EDE7] rounded mx-auto" />
            <div className="h-24 bg-[#F0EDE7] rounded" />
            <div className="h-32 bg-[#F0EDE7] rounded" />
          </div>
        ) : error || !event ? (
          <div className="p-8 text-center bg-rose-500/10 border border-rose-500/30 rounded-lg text-rose-400 space-y-2">
            <AlertTriangle className="w-8 h-8 mx-auto" />
            <h3 className="text-sm font-bold">Alert Event Not Found</h3>
            <p className="text-xs text-text-muted">
              Event #{eventId} does not exist or could not be loaded.
            </p>
          </div>
        ) : (
          <>
            {/* Event Primary Hero Card */}
            <div className="p-5 bg-surface border border-[rgba(26,23,18,0.10)] rounded-xl shadow-lg space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[rgba(26,23,18,0.07)] pb-4">
                <div className="flex items-center gap-3">
                  <div className="p-3 bg-[#F0EDE7] rounded-xl border border-[rgba(26,23,18,0.10)]">
                    {getHazardIcon(event.hazard)}
                  </div>
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h2 className="text-base font-bold text-text-primary">
                        Alert Event #{event.id}
                      </h2>
                      <Badge variant={getSeverityVariant(event.severity_peak)} showIcon>
                        {event.severity_peak.toUpperCase()}
                      </Badge>
                      <Badge variant="outline" className="capitalize text-[11px]">
                        {event.status}
                      </Badge>
                    </div>
                    <p className="text-xs text-text-muted mt-1 flex items-center gap-1.5 flex-wrap">
                      <MapPin className="w-3.5 h-3.5 text-brand-blue" />
                      <span className="font-semibold text-text-secondary">
                        {event.location_name}
                      </span>
                      <span>({event.region})</span>
                      <span>•</span>
                      <span className="capitalize font-medium">
                        {event.hazard.replace("_", " ")}
                      </span>
                    </p>
                  </div>
                </div>

                {/* Outcome Badge */}
                <div className="flex items-center gap-2 self-start sm:self-center">
                  <span className="text-[11px] text-text-muted font-mono">Verification:</span>
                  {event.outcome === "hit" ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 font-mono text-xs font-bold uppercase">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Hit (Verified)
                    </span>
                  ) : event.outcome === "false_alarm" ? (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-rose-500/15 border border-rose-500/30 text-rose-400 font-mono text-xs font-bold uppercase">
                      <XCircle className="w-3.5 h-3.5" />
                      False Alarm
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] text-text-muted font-mono text-xs capitalize">
                      {event.outcome}
                    </span>
                  )}
                </div>
              </div>

              {/* Grid Summary */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
                <div className="p-2.5 bg-[#F0EDE7]/60 rounded-lg border border-[rgba(26,23,18,0.07)]">
                  <span className="text-[10px] text-text-muted block uppercase">Valid Window</span>
                  <span className="font-mono text-xs font-semibold text-text-primary">
                    {event.start_date === event.end_date
                      ? event.start_date
                      : `${event.start_date} → ${event.end_date}`}
                  </span>
                </div>
                <div className="p-2.5 bg-[#F0EDE7]/60 rounded-lg border border-[rgba(26,23,18,0.07)]">
                  <span className="text-[10px] text-text-muted block uppercase">Peak Intensity</span>
                  <span className="font-mono text-xs font-semibold text-text-primary">
                    {event.value_peak !== null && event.value_peak !== undefined ? event.value_peak : "—"}
                  </span>
                </div>
                <div className="p-2.5 bg-[#F0EDE7]/60 rounded-lg border border-[rgba(26,23,18,0.07)]">
                  <span className="text-[10px] text-text-muted block uppercase">First Detected</span>
                  <span className="font-mono text-xs font-semibold text-text-primary">
                    {event.first_detected_at ? new Date(event.first_detected_at).toLocaleDateString() : "—"}
                  </span>
                </div>
                <div className="p-2.5 bg-[#F0EDE7]/60 rounded-lg border border-[rgba(26,23,18,0.07)]">
                  <span className="text-[10px] text-text-muted block uppercase">Verified Date</span>
                  <span className="font-mono text-xs font-semibold text-text-primary">
                    {event.verified_at ? new Date(event.verified_at).toLocaleDateString() : "Pending"}
                  </span>
                </div>
              </div>
            </div>

            {/* Feature G: How Unusual (Local Extremeness) */}
            {(data?.rarity_context || data?.rarity_label || childAlerts.some((a) => a.rarity_label)) && (
              <div className="p-5 bg-gradient-to-br from-[#1b2333]/80 to-[#161b22] border border-brand-blue/30 rounded-xl shadow-lg space-y-2.5">
                <div className="flex items-center justify-between border-b border-[rgba(26,23,18,0.07)] pb-2.5">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-brand-blue" />
                    <h3 className="text-sm font-bold text-text-primary">
                      How unusual (Local Extremeness)
                    </h3>
                  </div>
                  <span className="text-[10px] text-brand-blue/90 uppercase font-mono tracking-wider font-semibold bg-brand-blue/10 px-2 py-0.5 rounded border border-brand-blue/20">
                    15+ Year Climatology
                  </span>
                </div>

                <div className="pt-1 space-y-1.5">
                  <p className="text-sm font-semibold text-text-primary">
                    {data?.rarity_context || `Also unusual for this location — ${data?.rarity_label || childAlerts.find((a) => a.rarity_label)?.rarity_label}`}
                  </p>
                  <p className="text-xs text-text-muted leading-relaxed">
                    Evaluated against the station&apos;s historical day-of-year distribution (±7-day window) across qualifying years of truth observations.
                  </p>
                </div>
              </div>
            )}

            {/* Feature C: What this means */}
            {data?.guidance && (
              <div className="p-5 bg-surface border border-[rgba(26,23,18,0.10)] rounded-xl shadow-lg space-y-3">
                <div className="flex items-center justify-between border-b border-[rgba(26,23,18,0.07)] pb-2.5">
                  <div className="flex items-center gap-2">
                    <HelpCircle className="w-5 h-5 text-emerald-400" />
                    <h3 className="text-sm font-bold text-text-primary">
                      What this means (Hazard Guidance)
                    </h3>
                  </div>
                  <span className="text-[10px] text-text-muted uppercase font-mono tracking-wider">
                    Official IMD Calibrated
                  </span>
                </div>

                <div className="space-y-3 pt-1">
                  <h4 className="text-sm font-semibold text-text-primary">
                    {data.guidance.headline}
                  </h4>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    {data.guidance.body}
                  </p>

                  {data.guidance.precautions && data.guidance.precautions.length > 0 && (
                    <div className="space-y-1.5 pt-1">
                      <span className="text-[11px] font-semibold text-text-muted uppercase tracking-wider block">
                        Actionable Precautions:
                      </span>
                      <ul className="space-y-1.5 text-xs text-text-secondary list-disc list-inside">
                        {data.guidance.precautions.map((p, idx) => (
                          <li key={idx} className="leading-relaxed">
                            {p}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="pt-3 border-t border-border/40 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <a
                      href={data.guidance.official_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-brand-blue hover:underline inline-flex items-center gap-1.5 font-semibold"
                    >
                      <span>Open Official IMD Warning Portal (GIS)</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                    <span className="text-[11px] text-text-muted font-mono">
                      Source: {data.guidance.source}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Feature A: Track Record */}
            {data?.track_record && (
              <div className="p-5 bg-surface border border-[rgba(26,23,18,0.10)] rounded-xl shadow-lg space-y-3">
                <div className="flex items-center justify-between border-b border-[rgba(26,23,18,0.07)] pb-2.5">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-5 h-5 text-brand-teal" />
                    <h3 className="text-sm font-bold text-text-primary">
                      180-Day Historical Track Record
                    </h3>
                  </div>
                  <span className="text-[10px] text-text-muted font-mono">
                    Region: {event.region} • Trailing 180 Days
                  </span>
                </div>

                {!data.track_record.applicable ? (
                  <div className="p-3 bg-[#F0EDE7] rounded-lg border border-[rgba(26,23,18,0.10)] text-xs text-text-muted">
                    {data.track_record.summary_text}
                  </div>
                ) : data.track_record.low_sample ? (
                  <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-300 text-xs space-y-1">
                    <div className="font-semibold flex items-center gap-1.5">
                      <AlertTriangle className="w-4 h-4" />
                      <span>Low Historical Sample Count (n &lt; 5)</span>
                    </div>
                    <p className="text-[11px] text-amber-200/80">
                      {data.track_record.summary_text} ({data.track_record.n} historical alerts evaluated in the last 180 days).
                    </p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <p className="text-xs text-text-primary font-medium">
                        {data.track_record.summary_text}
                      </p>
                      <span className="text-xl font-bold font-mono text-emerald-400">
                        {data.track_record.hit_rate !== null && data.track_record.hit_rate !== undefined
                          ? `${(data.track_record.hit_rate * 100).toFixed(0)}% Hit Rate`
                          : "—"}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-xs font-mono text-text-muted">
                      <span className="px-2.5 py-1 rounded bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)]">
                        Hits: {data.track_record.hits}
                      </span>
                      <span className="px-2.5 py-1 rounded bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)]">
                        False Alarms: {data.track_record.false_alarms}
                      </span>
                      <span className="px-2.5 py-1 rounded bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)]">
                        Total Evaluated (n): {data.track_record.n}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Feature F: Public Share Action Card */}
            <div className="p-5 bg-surface border border-[rgba(26,23,18,0.10)] rounded-xl shadow-lg space-y-3">
              <div className="flex items-center justify-between border-b border-[rgba(26,23,18,0.07)] pb-2.5">
                <div className="flex items-center gap-2">
                  <Share2 className="w-5 h-5 text-brand-orange" />
                  <h3 className="text-sm font-bold text-text-primary">
                    Share This Alert Event
                  </h3>
                </div>
                <span className="text-[10px] text-text-muted">
                  Permanent Public Link
                </span>
              </div>

              <p className="text-xs text-text-secondary leading-relaxed">
                This public page can be viewed by anyone without an account or login. Use the verified permalink or pre-formatted WhatsApp share text below.
              </p>

              <div className="flex flex-wrap items-center gap-3 pt-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleCopyLink}
                  className="text-xs h-8 gap-1.5"
                >
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy Link</span>
                </Button>

                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleCopyText}
                  className="text-xs h-8 gap-1.5"
                >
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy Briefing Text</span>
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
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium rounded-md bg-emerald-600 hover:bg-emerald-500 text-white h-8 transition-colors"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>Share on WhatsApp</span>
                </a>
              </div>
            </div>

            {/* Lifecycle Timeline */}
            <div className="p-5 bg-surface border border-[rgba(26,23,18,0.10)] rounded-xl shadow-lg space-y-3">
              <div className="flex items-center justify-between border-b border-[rgba(26,23,18,0.07)] pb-2.5">
                <div className="flex items-center gap-2">
                  <Activity className="w-5 h-5 text-brand-blue" />
                  <h3 className="text-sm font-bold text-text-primary">
                    Event Lifecycle Timeline
                  </h3>
                </div>
                <span className="text-[10px] text-text-muted font-mono">
                  {lifecycleHistory.length} Transitions
                </span>
              </div>

              {lifecycleHistory.length === 0 ? (
                <p className="text-xs text-text-muted py-2">
                  No recorded lifecycle state changes.
                </p>
              ) : (
                <div className="relative pl-6 space-y-3 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-border">
                  {lifecycleHistory.map((node, i) => (
                    <div key={i} className="relative">
                      <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-brand-blue border border-brand-blue" />
                      <div className="p-3 rounded bg-[#F0EDE7]/60 border border-[rgba(26,23,18,0.10)] flex items-center justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-xs uppercase text-text-primary">
                              {node.lifecycle_state}
                            </span>
                            <Badge variant={getSeverityVariant(node.severity)} className="text-[10px] py-0">
                              {node.severity}
                            </Badge>
                            {node.previous_severity && (
                              <span className="text-[11px] text-text-muted">
                                from {node.previous_severity}
                              </span>
                            )}
                          </div>
                          <span className="text-[11px] text-text-muted font-mono block mt-1">
                            Valid: {node.valid_date} • Value: {node.value ?? "—"}
                          </span>
                        </div>
                        <span className="text-[10px] text-text-muted font-mono">
                          {new Date(node.issue_time).toLocaleTimeString([], {
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Why Flagged (Meteorological Rules) */}
            <div className="p-5 bg-surface border border-[rgba(26,23,18,0.10)] rounded-xl shadow-lg space-y-3">
              <div className="flex items-center gap-2 border-b border-[rgba(26,23,18,0.07)] pb-2.5">
                <Info className="w-5 h-5 text-brand-orange" />
                <h3 className="text-sm font-bold text-text-primary">
                  Why Flagged (Meteorological Rules & Consensus)
                </h3>
              </div>

              <div className="space-y-3 pt-1">
                {childAlerts.map((alert) => (
                  <div key={alert.id} className="p-3 bg-[#F0EDE7]/60 rounded-lg border border-[rgba(26,23,18,0.10)] space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Calendar className="w-4 h-4 text-text-muted" />
                        <span className="font-bold text-text-primary font-mono text-xs">
                          {alert.valid_date}
                        </span>
                        <span className="text-text-muted text-xs">
                          (Lead D+{alert.lead_days})
                        </span>
                      </div>
                      <Badge variant={getSeverityVariant(alert.severity)}>
                        {alert.severity}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs pt-1">
                      <div className="bg-surface p-2 rounded border border-[rgba(26,23,18,0.07)]">
                        <span className="text-text-muted block text-[10px]">Consensus Value</span>
                        <span className="font-bold font-mono text-text-primary">{alert.value ?? "—"}</span>
                      </div>
                      <div className="bg-surface p-2 rounded border border-[rgba(26,23,18,0.07)]">
                        <span className="text-text-muted block text-[10px]">Model Agreement</span>
                        <span className="font-bold font-mono text-text-primary">
                          {alert.models_over} / 4 models
                        </span>
                      </div>
                      <div className="bg-surface p-2 rounded border border-[rgba(26,23,18,0.07)]">
                        <span className="text-text-muted block text-[10px]">Spread</span>
                        <span className="font-bold font-mono text-text-primary">±{alert.spread ?? "—"}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
};
