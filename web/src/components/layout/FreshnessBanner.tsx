import React from "react";
import { AlertTriangle } from "lucide-react";
import { useMeta } from "@/api/useMeta";

export const FreshnessBanner: React.FC = () => {
  const { data: meta } = useMeta();

  if (!meta?.last_run?.started_at) return null;

  const startedAt = new Date(meta.last_run.started_at);
  const now = new Date();
  const diffHours = (now.getTime() - startedAt.getTime()) / (1000 * 60 * 60);

  // If data is older than 9 hours, show stale data banner per PRD §10.4 / §10.7
  if (diffHours <= 9) return null;

  return (
    <div className="bg-amber-950/80 border-b border-amber-800/80 px-4 py-2 flex items-center justify-between text-xs text-amber-200">
      <div className="flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-hazard-advisory shrink-0" />
        <span>
          <strong>Stale Forecast Advisory:</strong> Last pipeline cycle was completed{" "}
          <span className="font-mono">{Math.round(diffHours)} hours ago</span> (
          {startedAt.toLocaleTimeString("en-IN", {
            timeZone: "Asia/Kolkata",
            hour: "2-digit",
            minute: "2-digit",
          })}{" "}
          IST). Operational forecasts are normally refreshed every 6 hours.
        </span>
      </div>
      <span className="text-[10px] px-2 py-0.5 rounded bg-amber-900/60 border border-amber-700/60 font-mono">
        DATA &gt; 9H OLD
      </span>
    </div>
  );
};
