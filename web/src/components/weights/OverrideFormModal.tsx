import React, { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { useCreateWeightOverride } from "@/api/useWeights";
import { toast } from "sonner";
import { Sliders, Shield, AlertCircle } from "lucide-react";

interface OverrideFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  variable: string;
  region: string;
  season: string;
  leadDays: number;
  initialWeights?: Record<string, number>;
}

export const OverrideFormModal: React.FC<OverrideFormModalProps> = ({
  isOpen,
  onClose,
  variable,
  region,
  season,
  leadDays,
  initialWeights = { gfs: 0.25, ecmwf_ifs: 0.25, icon: 0.25, aifs: 0.25 },
}) => {
  const [weights, setWeights] = useState<Record<string, number>>(initialWeights);
  const [reason, setReason] = useState<string>("");
  const [expiresHours, setExpiresHours] = useState<number>(24);
  const createMutation = useCreateWeightOverride();

  // Normalize weights so they always sum strictly to 1.0
  const handleSliderChange = (model: string, newVal: number) => {
    const updated = { ...weights, [model]: newVal };
    const sum = Object.values(updated).reduce((acc, v) => acc + v, 0);

    if (sum === 0) return;

    // Renormalize other models proportionately
    const normalized: Record<string, number> = {};
    const otherKeys = Object.keys(updated).filter((k) => k !== model);
    const remainder = Math.max(0, 1.0 - newVal);
    const otherSum = otherKeys.reduce((acc, k) => acc + updated[k], 0);

    normalized[model] = Math.round(newVal * 1000) / 1000;

    otherKeys.forEach((k) => {
      if (otherSum === 0) {
        normalized[k] = Math.round((remainder / otherKeys.length) * 1000) / 1000;
      } else {
        normalized[k] = Math.round(((updated[k] / otherSum) * remainder) * 1000) / 1000;
      }
    });

    // Clean up rounding error so sum is precisely 1.0
    const total = Object.values(normalized).reduce((acc, v) => acc + v, 0);
    const diff = 1.0 - total;
    if (otherKeys.length > 0) {
      normalized[otherKeys[0]] = Math.round((normalized[otherKeys[0]] + diff) * 1000) / 1000;
    }

    setWeights(normalized);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (createMutation.isPending) return;

    if (reason.trim().length < 10) {
      toast.error("Audit reason must be at least 10 characters long.");
      return;
    }

    const timeoutId = setTimeout(() => {
      createMutation.reset();
      toast.error("Override submission timed out after 15 seconds. Please try again.");
    }, 15000);

    try {
      await createMutation.mutateAsync({
        variable,
        region,
        season,
        lead_days: leadDays,
        weights,
        reason: reason.trim(),
        expires_hours: expiresHours,
      });

      clearTimeout(timeoutId);
      toast.success("Audited weight override created successfully.");
      onClose();
    } catch (err: any) {
      clearTimeout(timeoutId);
      createMutation.reset();
      const msg = err?.response?.data?.detail?.message || err?.message || "An error occurred.";
      toast.error(`Failed to submit override: ${msg}`);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <Sliders className="w-4 h-4 text-brand-blue" />
          <span>Create Forecaster Weight Override</span>
        </div>
      }
      description={`Region: ${region} · Lead Day: D+${leadDays} · Season: ${season}`}
      maxWidth="md"
    >
      <form onSubmit={handleSubmit} className="space-y-4 text-xs font-sans">
        {/* Sliders */}
        <div className="space-y-3 p-3 bg-[#F0EDE7] rounded-lg border border-[rgba(26,23,18,0.10)]">
          <span className="font-semibold text-text-primary block">
            Adjust Model Contribution (Must sum to 100%):
          </span>

          {Object.entries(weights).map(([model, val]) => (
            <div key={model} className="space-y-1">
              <div className="flex justify-between font-mono text-[11px]">
                <span className="uppercase text-text-secondary font-bold">{model}</span>
                <span className="text-text-primary">{(val * 100).toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={val}
                onChange={(e) => handleSliderChange(model, parseFloat(e.target.value))}
                className="w-full accent-brand-blue cursor-pointer"
              />
            </div>
          ))}
        </div>

        {/* Reason Input */}
        <div className="space-y-1">
          <label className="font-semibold text-text-primary block">
            Mandatory Meteorological Justification (min 10 chars):
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. ECMWF IFS significantly overpredicting convective moisture across coastal Odisha..."
            rows={3}
            className="w-full p-2.5 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-md text-text-primary text-xs focus:ring-2 focus:ring-brand-blue/50 outline-none"
            required
          />
          <div className="flex justify-between text-[10px] text-text-muted">
            <span>Logged in immutable audit trail with user identity</span>
            <span className={reason.length < 10 ? "text-hazard-alert" : "text-emerald-400 font-mono"}>
              {reason.length} / 10 min characters
            </span>
          </div>
        </div>

        {/* Expiry Selector */}
        <div className="space-y-1">
          <label className="font-semibold text-text-primary block">Override Duration:</label>
          <select
            value={expiresHours}
            onChange={(e) => setExpiresHours(parseInt(e.target.value, 10))}
            className="w-full p-2 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-md text-text-primary text-xs outline-none"
          >
            <option value={12}>12 Hours (Single Duty Cycle)</option>
            <option value={24}>24 Hours (Full Diurnal Cycle)</option>
            <option value={48}>48 Hours (Synoptic Episode)</option>
            <option value={72}>72 Hours (Extended Active Episode)</option>
          </select>
        </div>

        {/* Audit Notice */}
        <div className="p-2.5 bg-amber-950/20 rounded border border-amber-800/40 text-amber-200/90 text-[11px] flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-hazard-advisory shrink-0 mt-0.5" />
          <p>
            Overrides alter the blended guidance for operational forecasters and duty officers while
            preserving the official baseline algorithm in audit reports.
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-[rgba(26,23,18,0.09)]">
          <Button
            variant="ghost"
            size="sm"
            type="button"
            onClick={onClose}
            disabled={createMutation.isPending}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            isLoading={createMutation.isPending}
            disabled={reason.trim().length < 10 || createMutation.isPending}
          >
            <Shield className="w-3.5 h-3.5 mr-1" />
            <span>{createMutation.isPending ? "Submitting..." : "Submit Audited Override"}</span>
          </Button>
        </div>
      </form>
    </Modal>
  );
};
