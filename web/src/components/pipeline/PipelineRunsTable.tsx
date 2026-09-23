import React from "react";
import type { PipelineJobRun } from "@/api/types";
import { Badge } from "@/components/ui/Badge";

interface PipelineRunsTableProps {
  runs: PipelineJobRun[];
}

export const PipelineRunsTable: React.FC<PipelineRunsTableProps> = ({ runs }) => {
  const formatTime = (iso?: string) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return (
        d.toLocaleDateString("en-IN", {
          timeZone: "Asia/Kolkata",
          month: "short",
          day: "numeric",
        }) +
        " " +
        d.toLocaleTimeString("en-IN", {
          timeZone: "Asia/Kolkata",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        })
      );
    } catch {
      return iso;
    }
  };

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full text-xs text-left border-collapse">
        <thead>
          <tr className="border-b border-[rgba(26,23,18,0.10)] bg-surface text-text-muted">
            <th className="p-2.5 font-medium">Job Pipeline</th>
            <th className="p-2.5 font-medium">Status</th>
            <th className="p-2.5 font-medium">Started (IST)</th>
            <th className="p-2.5 font-medium">Rows Written</th>
            <th className="p-2.5 font-medium">API Calls Est.</th>
            <th className="p-2.5 font-medium">Telemetry Message</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {runs.map((r) => {
            const isSuccess =
              r.status?.toLowerCase() === "success" ||
              r.status?.toLowerCase() === "completed";
            const isFailed = r.status?.toLowerCase() === "failed";

            return (
              <tr key={r.id} className="hover:bg-[#F0EDE7]/50 transition-colors">
                <td className="p-2.5 font-semibold text-text-primary">
                  {r.job}
                </td>
                <td className="p-2.5">
                  <Badge variant={isSuccess ? "normal" : isFailed ? "alert" : "watch"}>
                    {r.status?.toUpperCase() || "PENDING"}
                  </Badge>
                </td>
                <td className="p-2.5 font-mono text-[11px] text-text-secondary">
                  {formatTime(r.started_at)}
                </td>
                <td className="p-2.5 font-mono text-text-secondary">
                  {r.rows_written !== undefined && r.rows_written !== null
                    ? r.rows_written.toLocaleString()
                    : "—"}
                </td>
                <td className="p-2.5 font-mono text-text-secondary">
                  {r.api_calls_est !== undefined && r.api_calls_est !== null
                    ? Math.round(r.api_calls_est)
                    : "—"}
                </td>
                <td className="p-2.5 text-text-muted max-w-xs truncate text-[11px]">
                  {r.message || "Execution completed cleanly"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
