import React, { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { useArtifact } from "@/api/useArtifact";
import { FileCode, AlertCircle, ChevronLeft, ChevronRight, Download } from "lucide-react";
import { toast } from "sonner";

interface ArtifactViewerModalProps {
  isOpen: boolean;
  onClose: () => void;
  artifactId: string | null;
}

export const ArtifactViewerModal: React.FC<ArtifactViewerModalProps> = ({
  isOpen,
  onClose,
  artifactId,
}) => {
  const [offset, setOffset] = useState<number>(0);
  const limit = 25;

  const { data: artifact, isLoading, error } = useArtifact(artifactId, offset, limit);

  const handleCopyJson = () => {
    if (!artifact) return;
    navigator.clipboard.writeText(JSON.stringify(artifact.data, null, 2));
    toast.success("Artifact records copied to clipboard as JSON");
  };

  const records = artifact?.data || [];
  const total = artifact?.total_records || 0;
  const columns = records.length > 0 ? Object.keys(records[0]) : [];

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={
        <div className="flex items-center gap-2">
          <FileCode className="w-4 h-4 text-brand-blue" />
          <span>Assistant Stored Artifact: {artifactId || "—"}</span>
        </div>
      }
      description="Paginated inspection of full assistant data results (PRD §8.2, §12 — role: owner/admin)"
      maxWidth="lg"
    >
      <div className="space-y-3 text-xs font-sans">
        {isLoading ? (
          <div className="space-y-2 py-4">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        ) : error ? (
          <div className="p-6 bg-[#161b22] rounded border border-border text-center space-y-2">
            <AlertCircle className="w-6 h-6 text-hazard-advisory mx-auto" />
            <p className="font-semibold text-text-primary">Unable to load artifact</p>
            <p className="text-text-muted text-[11px] max-w-sm mx-auto">
              {(error as any)?.message ||
                "Access restricted to artifact owner or system administrator (PRD §12)."}
            </p>
          </div>
        ) : !artifact || records.length === 0 ? (
          <div className="p-6 bg-[#161b22] rounded border border-border text-center text-text-muted">
            No stored records found for artifact ID: {artifactId}
          </div>
        ) : (
          <>
            {/* Header Telemetry */}
            <div className="flex items-center justify-between flex-wrap gap-2 p-2.5 bg-[#21262d] rounded border border-border text-[11px]">
              <div className="flex items-center gap-3">
                <span className="text-text-muted">
                  Total Records:{" "}
                  <strong className="text-text-primary font-mono">{total.toLocaleString()}</strong>
                </span>
                <span className="text-text-muted">
                  Offset: <span className="font-mono text-text-secondary">{offset}</span>
                </span>
                <span className="text-text-muted">
                  Limit: <span className="font-mono text-text-secondary">{limit}</span>
                </span>
              </div>
              <Button variant="outline" size="sm" onClick={handleCopyJson} className="h-6 text-[10px]">
                <Download className="w-3 h-3 mr-1" />
                <span>Copy JSON</span>
              </Button>
            </div>

            {/* Records Table */}
            <div className="overflow-x-auto max-h-72 border border-border rounded">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-border bg-[#161b22] text-text-muted font-mono sticky top-0">
                    {columns.map((col) => (
                      <th key={col} className="p-2 capitalize">
                        {col.replace(/_/g, " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60 font-mono text-[11px]">
                  {records.map((row, idx) => (
                    <tr key={idx} className="hover:bg-[#21262d]/50">
                      {columns.map((col) => (
                        <td key={col} className="p-2 text-text-secondary">
                          {typeof row[col] === "number"
                            ? row[col].toFixed(2)
                            : String(row[col] ?? "—")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            <div className="flex items-center justify-between pt-1 text-xs">
              <span className="text-text-muted text-[11px]">
                Showing {offset + 1}–{Math.min(offset + limit, total)} of {total}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={offset <= 0}
                  onClick={() => setOffset((prev) => Math.max(0, prev - limit))}
                  className="h-7 px-2 text-xs"
                >
                  <ChevronLeft className="w-3.5 h-3.5 mr-1" />
                  <span>Prev</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={offset + limit >= total}
                  onClick={() => setOffset((prev) => prev + limit)}
                  className="h-7 px-2 text-xs"
                >
                  <span>Next</span>
                  <ChevronRight className="w-3.5 h-3.5 ml-1" />
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};
