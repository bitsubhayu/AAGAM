import React, { useState } from "react";
import {
  CloudRain,
  Flame,
  Wind,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  Clock,
  Check,
  Activity,
  XCircle,
  Loader2,
} from "lucide-react";
import type { AlertItem } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useAuthStore } from "@/auth/authStore";
import { useAcknowledgeAlert, useCancelAlert } from "@/api/useAlerts";
import { toast } from "sonner";
import { WhyFlaggedModal } from "./WhyFlaggedModal";

interface AlertCardProps {
  alert: AlertItem;
  onSelectEvent?: (eventId: number) => void;
}

export const AlertCard: React.FC<AlertCardProps> = ({ alert, onSelectEvent }) => {
  const { role } = useAuthStore();
  const ackMutation = useAcknowledgeAlert();
  const cancelMutation = useCancelAlert();
  const [whyModalOpen, setWhyModalOpen] = useState(false);
  const [ackConfirmOpen, setAckConfirmOpen] = useState(false);

  const canAck = role === "forecaster" || role === "coordinator";
  const isAcknowledged = alert.status === "acknowledged";
  const isCancelled = alert.status === "cancelled" || alert.lifecycle_state === "cancelled";

  const getHazardIcon = () => {
    switch (alert.hazard) {
      case "heavy_rain":
      case "heavy_rain_3day":
        return <CloudRain className="w-4 h-4 text-brand-blue" />;
      case "heatwave":
        return <Flame className="w-4 h-4 text-hazard-watch" />;
      case "high_wind":
        return <Wind className="w-4 h-4 text-[#4FA37A]" />;
      default:
        return <AlertTriangle className="w-4 h-4 text-hazard-advisory" />;
    }
  };

  const getUnit = () => {
    if (alert.hazard === "heavy_rain_3day") return "mm (3-day)";
    if (alert.hazard === "heavy_rain") return "mm/24h";
    if (alert.hazard === "heatwave") return "°C";
    if (alert.hazard === "high_wind") return "km/h";
    return "";
  };

  const formatIST = (isoString?: string | null) => {
    if (!isoString) return "";
    try {
      const d = new Date(isoString);
      return (
        d.toLocaleDateString("en-IN", {
          day: "2-digit",
          month: "short",
          year: "numeric",
          timeZone: "Asia/Kolkata",
        }) +
        " " +
        d.toLocaleTimeString("en-IN", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: "Asia/Kolkata",
        }) +
        " IST"
      );
    } catch {
      return isoString;
    }
  };

  const getSeverityLabel = (sev: string) => {
    switch (sev) {
      case "alert":
        return "Severe";
      case "watch":
        return "High";
      case "advisory":
        return "Moderate";
      default:
        return sev ? sev.charAt(0).toUpperCase() + sev.slice(1) : "Moderate";
    }
  };

  const handleAcknowledgeClick = () => {
    if (!canAck) {
      toast.error("Forecaster or Forecaster Coordinator authorization required to acknowledge alerts.");
      return;
    }
    setAckConfirmOpen(true);
  };

  const handleConfirmAcknowledge = async () => {
    try {
      await ackMutation.mutateAsync(alert.id);
      setAckConfirmOpen(false);
      toast.success(`Alert #${alert.id} for ${alert.location_name} acknowledged.`);
    } catch (err: any) {
      toast.error(`Failed to acknowledge alert: ${err.message || "Unknown error"}`);
    }
  };

  const handleCancel = async () => {
    if (!canAck) {
      toast.error("Forecaster or Coordinator authorization required to cancel alerts.");
      return;
    }
    if (!confirm(`Are you sure you want to cancel Alert #${alert.id} for ${alert.location_name}? The alert record will remain visible in audit logs as cancelled.`)) {
      return;
    }
    try {
      await cancelMutation.mutateAsync(alert.id);
      toast.success(`Alert #${alert.id} has been cancelled.`);
    } catch (err: any) {
      toast.error(err.message || "Failed to cancel alert");
    }
  };

  const severityVariant =
    alert.severity === "alert"
      ? "alert"
      : alert.severity === "watch"
      ? "watch"
      : "advisory";

  const getLifecycleBadgeClass = (state?: string) => {
    switch (state) {
      case "new":
        return "bg-[#EBF2FD] text-brand-blue border border-brand-blue/25";
      case "upgraded":
        return "bg-accent-soft text-accent border border-accent/30 font-bold";
      case "downgraded":
        return "bg-[#FDF3DC] text-[#7A5C00] border border-[#D9A441]/30";
      case "cancelled":
        return "bg-red-50 text-red-800 border border-red-200";
      default:
        return "bg-[#F0EDE7] text-text-muted border border-[rgba(26,23,18,0.10)]";
    }
  };

  return (
    <>
      <div
        className={`p-3.5 sm:p-4 rounded-[16px] border transition-all duration-150 ${
          isCancelled
            ? "bg-[#FAF7F5] border-red-200/70 opacity-90 shadow-none"
            : isAcknowledged
            ? "bg-[#F5F2EC] border-[rgba(26,23,18,0.07)] opacity-75"
            : "bg-surface border-[rgba(26,23,18,0.09)] hover:border-accent/30 hover:shadow-card"
        }`}
      >
        {/* Responsive Container: flex-col on mobile/tablet, flex-row on desktop */}
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3 min-w-0">
          {/* Main Details (Full width on mobile/tablet) */}
          <div className="space-y-2 flex-1 min-w-0">
            {/* Header / Hazard & Status Badges */}
            <div className="flex items-center gap-1.5 sm:gap-2 flex-wrap min-w-0">
              <div className="p-1.5 bg-[#F0EDE7] rounded-full shrink-0">
                {getHazardIcon()}
              </div>
              <span className="font-semibold text-xs sm:text-sm text-text-primary truncate max-w-[200px]" title={alert.location_name}>
                {alert.location_name}
              </span>
              <Badge variant="outline" className="shrink-0">{alert.region}</Badge>
              <Badge variant={severityVariant} showIcon className="shrink-0">
                {alert.severity.toUpperCase()}
              </Badge>
              {isCancelled ? (
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded-full bg-red-100 text-red-800 border border-red-200 font-bold flex items-center gap-1 shrink-0 whitespace-nowrap">
                  <XCircle className="w-3 h-3 text-red-700 shrink-0" />
                  <span>CANCELLED</span>
                </span>
              ) : (
                alert.lifecycle_state && (
                  <span className={`text-[10px] uppercase font-mono px-2 py-0.5 rounded-full shrink-0 whitespace-nowrap ${getLifecycleBadgeClass(alert.lifecycle_state)}`}>
                    {alert.lifecycle_state}
                    {alert.previous_severity && alert.lifecycle_state !== "new" && ` (from ${alert.previous_severity})`}
                  </span>
                )
              )}
              {isAcknowledged && !isCancelled && (
                <span className="inline-flex items-center gap-1 text-[10px] font-bold font-mono px-2 py-0.5 rounded-full bg-emerald-50 text-hazard-normal border border-emerald-200/60 shrink-0 whitespace-nowrap">
                  <CheckCircle2 className="w-3 h-3 text-emerald-600 shrink-0" />
                  <span>ACKNOWLEDGED</span>
                </span>
              )}
            </div>

            {/* Authoritative Cancellation Notice */}
            {isCancelled && (
              <div className="text-[11px] text-red-800 bg-red-50/90 px-2.5 py-1.5 rounded-lg border border-red-200/60 font-medium flex items-center gap-1.5 my-1">
                <XCircle className="w-3.5 h-3.5 text-red-700 shrink-0" />
                <span className="break-words">
                  Cancelled by <strong>{alert.cancelled_by_name || "Authorized Forecaster"}</strong>
                  {alert.cancelled_at ? ` · ${formatIST(alert.cancelled_at)}` : ""}
                </span>
              </div>
            )}

            {/* Main Forecast & Valid details row with deliberate wrapping */}
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-text-secondary pt-0.5 min-w-0">
              <div className="flex items-center gap-1.5 shrink-0 whitespace-nowrap">
                <span className="text-text-muted text-[11px]">Forecast:</span>
                <span className={`font-mono font-bold text-sm tabular-nums ${isCancelled ? "text-text-secondary line-through" : "text-text-primary"}`}>
                  {alert.value !== null && alert.value !== undefined ? alert.value.toFixed(1) : "—"} {getUnit()}
                </span>
              </div>
              <div className="flex items-center gap-1 shrink-0 whitespace-nowrap">
                <Clock className="w-3.5 h-3.5 text-text-muted shrink-0" />
                <span className="font-mono text-[11px] text-text-secondary">
                  Valid: <strong className="text-text-primary font-medium">{alert.valid_date}</strong> (D+{alert.lead_days})
                </span>
              </div>
            </div>

            {/* Agreement chip & spread */}
            <div className="flex items-center gap-2 pt-0.5 flex-wrap min-w-0">
              <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-[#F0EDE7] text-text-secondary border border-[rgba(26,23,18,0.09)] font-mono whitespace-nowrap shrink-0">
                Agreement: {alert.models_over}/4 models exceed threshold
              </span>
              {alert.spread > 0 && (
                <span className="text-[10px] text-text-muted font-mono whitespace-nowrap shrink-0">
                  Spread σ: {alert.spread.toFixed(1)} {getUnit()}
                </span>
              )}
              {alert.rarity_label && (
                <span className="text-[10px] px-2.5 py-0.5 rounded-full bg-[#F0EBFD] text-[#8B6FD9] border border-[#8B6FD9]/25 font-mono whitespace-nowrap shrink-0">
                  {alert.rarity_label}
                </span>
              )}
            </div>
          </div>

          {/* Action Controls: below details on mobile/tablet, aligned right on desktop */}
          <div className="flex flex-wrap md:flex-col md:items-end justify-start md:justify-center gap-2 pt-2.5 md:pt-0 border-t md:border-t-0 border-[rgba(26,23,18,0.06)] shrink-0 w-full md:w-auto">
            <div className="flex flex-wrap items-center gap-1.5">
              {alert.event_id && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onSelectEvent?.(alert.event_id!)}
                  className="text-brand-blue border-brand-blue/30 hover:bg-[#EBF2FD] text-[11px] h-7 px-2.5 whitespace-nowrap"
                >
                  <Activity className="w-3 h-3 mr-1" />
                  <span>Event Detail</span>
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setWhyModalOpen(true)}
                className="text-text-muted hover:text-text-primary text-[11px] h-7 px-2.5 whitespace-nowrap"
              >
                <HelpCircle className="w-3.5 h-3.5 mr-1 text-brand-blue" />
                <span>Why Flagged</span>
              </Button>
            </div>

            {!isCancelled && (
              <div className="flex flex-wrap items-center gap-1.5">
                {!isAcknowledged && (
                  <Button
                    variant={canAck ? "secondary" : "outline"}
                    size="sm"
                    onClick={handleAcknowledgeClick}
                    disabled={!canAck || ackMutation.isPending}
                    className="text-xs h-7 px-2.5 whitespace-nowrap"
                    title={canAck ? "Acknowledge alert" : "Forecaster or Forecaster Coordinator permission required"}
                  >
                    <Check className="w-3 h-3 mr-1 text-hazard-normal" />
                    <span>{canAck ? "Acknowledge" : "Public (Read Only)"}</span>
                  </Button>
                )}

                {canAck && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleCancel}
                    disabled={cancelMutation.isPending}
                    className="text-xs h-7 px-2 text-hazard-alert hover:bg-red-50 border-red-200 whitespace-nowrap"
                    title="Cancel Alert (keeps audit record visible)"
                  >
                    <XCircle className="w-3 h-3 mr-1 text-hazard-alert" />
                    <span>Cancel</span>
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Two-step Operational Acknowledge Confirmation Dialog */}
      <Modal
        isOpen={ackConfirmOpen}
        onClose={() => {
          if (!ackMutation.isPending) {
            setAckConfirmOpen(false);
          }
        }}
        title="Acknowledge Alert?"
        maxWidth="md"
      >
        <div className="space-y-4 text-text-primary">
          <p className="text-xs text-text-secondary leading-relaxed">
            Are you sure you want to acknowledge the alert for{" "}
            <strong className="text-text-primary font-semibold">{alert.location_name}</strong>?
          </p>

          <div className="p-3 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-lg text-xs space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-text-muted">Location:</span>
              <span className="font-medium text-text-primary">{alert.location_name} ({alert.region})</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-text-muted">Hazard:</span>
              <span className="font-medium text-text-primary capitalize">{alert.hazard.replace(/_/g, " ")}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-text-muted">Severity:</span>
              <Badge variant={severityVariant} showIcon>
                {getSeverityLabel(alert.severity)} ({alert.severity.toUpperCase()})
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-text-muted">Valid:</span>
              <span className="font-mono font-medium text-text-primary">{alert.valid_date} (D+{alert.lead_days})</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-text-muted">Forecast Value:</span>
              <span className="font-mono font-bold text-text-primary">
                {alert.value !== null && alert.value !== undefined ? alert.value.toFixed(1) : "—"} {getUnit()}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-[rgba(26,23,18,0.07)]">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setAckConfirmOpen(false)}
              disabled={ackMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={handleConfirmAcknowledge}
              disabled={ackMutation.isPending}
              className="bg-accent text-surface-dark hover:bg-accent/90 font-medium min-w-[160px] flex items-center justify-center gap-1.5"
            >
              {ackMutation.isPending ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Acknowledging...</span>
                </>
              ) : (
                <>
                  <Check className="w-3.5 h-3.5" />
                  <span>Confirm Acknowledge</span>
                </>
              )}
            </Button>
          </div>
        </div>
      </Modal>

      <WhyFlaggedModal
        isOpen={whyModalOpen}
        onClose={() => setWhyModalOpen(false)}
        alert={alert}
      />
    </>
  );
};

