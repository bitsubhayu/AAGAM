import React from "react";
import { Loader2, Server } from "lucide-react";

interface WakingUpBannerProps {
  isWakingUp: boolean;
  secondsElapsed: number;
}

export const WakingUpBanner: React.FC<WakingUpBannerProps> = ({
  isWakingUp,
  secondsElapsed,
}) => {
  if (!isWakingUp) return null;

  return (
    <div className="bg-blue-950/80 border-b border-blue-800/80 px-4 py-2 flex items-center justify-between text-xs text-blue-200">
      <div className="flex items-center gap-2">
        <Loader2 className="w-4 h-4 text-brand-blue animate-spin shrink-0" />
        <span>
          <strong>Backend Waking Up:</strong> Connecting to cloud API instance... (
          {secondsElapsed}s elapsed). Render free-tier cold starts may take up to 45 seconds.
        </span>
      </div>
      <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded bg-blue-900/60 border border-blue-700/60 font-mono">
        <Server className="w-3 h-3" />
        COLD START RESUME
      </span>
    </div>
  );
};
