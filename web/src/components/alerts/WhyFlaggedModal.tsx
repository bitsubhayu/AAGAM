import React from "react";
import { Modal } from "@/components/ui/Modal";
import type { AlertItem } from "@/api/types";
import { Info, ShieldAlert, CheckCircle2 } from "lucide-react";

interface WhyFlaggedModalProps {
  isOpen: boolean;
  onClose: () => void;
  alert: AlertItem;
}

export const WhyFlaggedModal: React.FC<WhyFlaggedModalProps> = ({
  isOpen,
  onClose,
  alert,
}) => {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-brand-orange" />
          <span>Alert Rule Diagnostic: {alert.location_name}</span>
        </div>
      }
      description={`Valid Date: ${alert.valid_date} (Lead Day ${alert.lead_days})`}
      maxWidth="md"
    >
      <div className="space-y-4 text-xs font-sans">
        {/* Triggered Rule */}
        <div className="p-3 bg-[#F0EDE7] rounded-lg border border-[rgba(26,23,18,0.10)] space-y-2">
          <div className="flex items-center gap-1.5 text-text-primary font-semibold">
            <Info className="w-3.5 h-3.5 text-brand-blue" />
            <span>Triggered Decision Rule</span>
          </div>
          <div className="text-text-secondary leading-relaxed font-mono text-[11px]">
            {typeof alert.rule === "object" && alert.rule !== null ? (
              <div className="space-y-1.5 pt-1">
                {Object.entries(alert.rule).map(([k, v]) => (
                  <div
                    key={k}
                    className="flex items-start justify-between gap-2 border-b border-[rgba(26,23,18,0.06)] pb-1 last:border-b-0"
                  >
                    <span className="text-text-muted capitalize font-sans">
                      {k.replace(/_/g, " ")}:
                    </span>
                    <span className="text-text-primary font-medium text-right break-all">
                      {typeof v === "object" ? JSON.stringify(v) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p>{String(alert.rule || "Multi-model ensemble consensus rule")}</p>
            )}
          </div>
        </div>

        {/* Multi-Model Exceedance Metrics */}
        <div className="space-y-2">
          <span className="font-semibold text-text-primary block">
            Multi-Model Agreement Breakdown:
          </span>
          <div className="grid grid-cols-2 gap-2">
            <div className="p-2.5 bg-surface rounded border border-[rgba(26,23,18,0.10)]">
              <span className="text-text-muted text-[11px] block">Models Exceeding Rule:</span>
              <span className="font-mono text-base font-bold text-text-primary">
                {alert.models_over ?? "—"} / 4
              </span>
            </div>
            <div className="p-2.5 bg-surface rounded border border-[rgba(26,23,18,0.10)]">
              <span className="text-text-muted text-[11px] block">Model Spread (σ):</span>
              <span className="font-mono text-base font-bold text-text-primary">
                {alert.spread != null ? Number(alert.spread).toFixed(1) : "—"}
              </span>
            </div>
          </div>
        </div>

        {/* IMD Ground Truth & Decision Support Context */}
        <div className="p-3 bg-blue-950/20 rounded border border-blue-800/40 text-blue-200/90 text-[11px] space-y-1">
          <span className="font-bold flex items-center gap-1">
            <CheckCircle2 className="w-3.5 h-3.5 text-blue-400" />
            Operational Notice
          </span>
          <p>
            This flag is generated using official India Meteorological Department (IMD)
            meteorological thresholds. AAGAM provides automated AI-NWP decision-support guidance
            and does not replace official statutory warnings issued by IMD/MoES.
          </p>
        </div>
      </div>
    </Modal>
  );
};
