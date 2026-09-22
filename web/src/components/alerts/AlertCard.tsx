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
} from "lucide-react";
import type { AlertItem } from "@/api/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useAuthStore } from "@/auth/authStore";
import { useAcknowledgeAlert } from "@/api/useAlerts";
import { toast } from "sonner";
import { WhyFlaggedModal } from "./WhyFlaggedModal";

interface AlertCardProps {
  alert: AlertItem;
  onSelectEvent?: (eventId: number) => void;
}

export const AlertCard: React.FC<AlertCardProps> = ({ alert, onSelectEvent }) => {
  const { role } = useAuthStore();
  const ackMutation = useAcknowledgeAlert();
  const [whyModalOpen, setWhyModalOpen] = useState(false);

  const canAck = role === "forecaster" || role === "admin";
  const isAcknowledged = alert.status === "acknowledged";

  const getHazardIcon = () => {
    switch (alert.hazard) {
      case "heavy_rain":
      case "heavy_rain_3day":
        return <CloudRain className="w-4 h-4 text-blue-400" />;
      case "heatwave":
        return <Flame className="w-4 h-4 text-orange-400" />;
      case "high_wind":
        return <Wind className="w-4 h-4 text-cyan-400" />;
      default:
        return <AlertTriangle className="w-4 h-4 text-amber-400" />;
    }
  };

  const getUnit = () => {
    if (alert.hazard === "heavy_rain_3day") return "mm (3-day)";
    if (alert.hazard === "heavy_rain") return "mm/24h";
    if (alert.hazard === "heatwave") return "°C";
    if (alert.hazard === "high_wind") return "km/h";
    return "";
  };

  const handleAcknowledge = async () => {
    if (!canAck) {
      toast.error("Forecaster or Admin authorization required to acknowledge alerts.");
      return;
    }

    try {
      await ackMutation.mutateAsync(alert.id);
      toast.success(`Alert #${alert.id} for ${alert.location_name} acknowledged.`);
    } catch (err: any) {
      toast.error(`Failed to acknowledge alert: ${err.message}`);
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
        return "bg-blue-500/10 text-blue-400 border-blue-500/30";
      case "upgraded":
        return "bg-rose-500/10 text-rose-400 border-rose-500/30 font-bold";
      case "downgraded":
        return "bg-amber-500/10 text-amber-400 border-amber-500/30";
      case "cancelled":
        return "bg-zinc-500/10 text-zinc-400 border-zinc-500/30 line-through";
      default:
        return "bg-zinc-500/10 text-zinc-400 border-zinc-500/30";
    }
  };

  return (
    <>
      <div
        className={`p-3.5 rounded-lg border transition-all ${
          isAcknowledged
            ? "bg-[#161b22]/50 border-border/50 opacity-75"
            : "bg-[#161b22] border-border hover:border-text-muted/60"
        }`}
      >
        <div className="flex items-start justify-between gap-3">
          {/* Left: Hazard details */}
          <div className="space-y-1.5 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="p-1 bg-[#21262d] rounded border border-border">
                {getHazardIcon()}
              </div>
              <span className="font-semibold text-xs text-text-primary">
                {alert.location_name}
              </span>
              <Badge variant="outline">{alert.region}</Badge>
              <Badge variant={severityVariant} showIcon>
                {alert.severity.toUpperCase()}
              </Badge>
              {alert.lifecycle_state && (
                <span className={`text-[10px] uppercase font-mono px-1.5 py-0.5 rounded border ${getLifecycleBadgeClass(alert.lifecycle_state)}`}>
                  {alert.lifecycle_state}
                  {alert.previous_severity && alert.lifecycle_state !== "new" && ` (from ${alert.previous_severity})`}
                </span>
              )}
              {isAcknowledged && (
                <span className="flex items-center gap-1 text-[10px] text-emerald-400 font-mono">
                  <CheckCircle2 className="w-3 h-3" />
                  ACKNOWLEDGED
                </span>
              )}
            </div>

            <div className="flex items-center gap-4 text-xs text-text-secondary pt-0.5">
              <div>
                <span className="text-text-muted text-[11px]">Forecast: </span>
                <span className="font-mono font-bold text-text-primary text-sm">
                  {alert.value !== null && alert.value !== undefined ? alert.value.toFixed(1) : "—"} {getUnit()}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <Clock className="w-3 h-3 text-text-muted" />
                <span className="font-mono text-[11px]">
                  Valid: {alert.valid_date} (D+{alert.lead_days})
                </span>
              </div>
            </div>

            {/* Agreement chip & spread */}
            <div className="flex items-center gap-2 pt-1 flex-wrap">
              <span className="text-[10px] px-2 py-0.5 rounded bg-[#21262d] text-text-secondary border border-border font-mono">
                Agreement: {alert.models_over}/4 models exceed threshold
              </span>
              {alert.spread > 0 && (
                <span className="text-[10px] text-text-muted font-mono">
                  Spread σ: {alert.spread.toFixed(1)} {getUnit()}
                </span>
              )}
              {alert.rarity_label && (
                <span className="text-[10px] px-2 py-0.5 rounded bg-purple-500/15 text-purple-300 border border-purple-500/30 font-mono">
                  {alert.rarity_label}
                </span>
              )}
            </div>
          </div>

          {/* Right: Actions */}
          <div className="flex flex-col items-end gap-2 shrink-0">
            <div className="flex items-center gap-1.5">
              {alert.event_id && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onSelectEvent?.(alert.event_id!)}
                  className="text-brand-blue border-brand-blue/30 hover:bg-brand-blue/10 text-[11px] h-7 px-2"
                >
                  <Activity className="w-3 h-3 mr-1" />
                  <span>Event Detail</span>
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setWhyModalOpen(true)}
                className="text-text-muted hover:text-text-primary text-[11px] h-7 px-2"
              >
                <HelpCircle className="w-3.5 h-3.5 mr-1 text-brand-blue" />
                <span>Why Flagged</span>
              </Button>
            </div>

            {!isAcknowledged && (
              <Button
                variant={canAck ? "secondary" : "outline"}
                size="sm"
                onClick={handleAcknowledge}
                disabled={!canAck || ackMutation.isPending}
                className="text-xs h-7 px-2.5"
                title={canAck ? "Acknowledge alert" : "Forecaster or Admin permission required"}
              >
                <Check className="w-3 h-3 mr-1 text-emerald-400" />
                <span>{canAck ? "Acknowledge" : "Viewer (Read)"}</span>
              </Button>
            )}
          </div>
        </div>
      </div>

      <WhyFlaggedModal
        isOpen={whyModalOpen}
        onClose={() => setWhyModalOpen(false)}
        alert={alert}
      />
    </>
  );
};
