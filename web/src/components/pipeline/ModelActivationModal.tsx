import React, { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { useActivateModel } from "@/api/usePipeline";
import { toast } from "sonner";
import { AlertCircle, RotateCcw, CheckCircle2 } from "lucide-react";

interface ModelActivationModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentActiveVersionId?: number;
}

export const ModelActivationModal: React.FC<ModelActivationModalProps> = ({
  isOpen,
  onClose,
  currentActiveVersionId,
}) => {
  const [customTargetId, setCustomTargetId] = useState<string | null>(null);
  const activateMutation = useActivateModel();

  const targetId =
    customTargetId !== null
      ? customTargetId
      : currentActiveVersionId !== undefined
      ? String(currentActiveVersionId)
      : "";

  const handleClose = () => {
    setCustomTargetId(null);
    onClose();
  };

  const handleActivate = async () => {
    const numericId = parseInt(targetId, 10);
    if (!targetId.trim() || isNaN(numericId) || numericId <= 0) {
      toast.error("Please enter a valid numeric model version ID.");
      return;
    }

    try {
      await activateMutation.mutateAsync(numericId);
      toast.success(`Model version #${numericId} successfully activated.`);
      handleClose();
    } catch (err: any) {
      toast.error(`Model activation failed: ${err.message}`);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <RotateCcw className="w-4 h-4 text-brand-blue" />
          <span>Admin Model Version Rollback & Activation</span>
        </div>
      }
      description="Change active weights matrix and model parameters in PostgreSQL (PRD §12, Admin only)"
      maxWidth="md"
    >
      <div className="space-y-4 text-xs font-sans">
        <div className="p-3 bg-[#21262d] rounded-lg border border-border space-y-2">
          <label className="font-semibold text-text-primary block">
            Target Model Version ID:
          </label>
          <input
            type="number"
            value={targetId}
            onChange={(e) => setCustomTargetId(e.target.value)}
            placeholder={currentActiveVersionId ? String(currentActiveVersionId) : "e.g. 1"}
            className="w-full p-2 bg-[#161b22] border border-border rounded text-text-primary font-mono text-sm"
          />
          <p className="text-[11px] text-text-muted">
            Current active version ID: <span className="font-mono text-brand-blue">#{currentActiveVersionId ?? "N/A"}</span>
          </p>
        </div>

        <div className="p-3 bg-red-950/20 rounded border border-red-800/40 text-red-200 text-[11px] flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-hazard-alert shrink-0 mt-0.5" />
          <p>
            Activating a model version atomically flushes the in-memory Redis/API weights cache
            and immediately updates live blending formulas across all 40 meteorological locations.
          </p>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
          <Button variant="ghost" size="sm" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={handleActivate}
            isLoading={activateMutation.isPending}
          >
            <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
            <span>Confirm & Activate</span>
          </Button>
        </div>
      </div>
    </Modal>
  );
};
