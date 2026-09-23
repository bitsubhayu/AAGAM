import React, { useState, useEffect } from "react";
import {
  CloudRain,
  Thermometer,
  Wind,
  Clock,
  Shield,
  LogIn,
} from "lucide-react";
import { useUIStore, type WeatherVariable } from "@/store/uiStore";
import { useAuthStore } from "@/auth/authStore";
import { useMeta } from "@/api/useMeta";
import { useHealth } from "@/api/useHealth";
import { AnimatedAssistantButton } from "@/components/ui/AnimatedAssistantButton";

export const TopHeader: React.FC = () => {
  const {
    selectedVariable,
    setSelectedVariable,
    selectedLeadDays,
    setSelectedLeadDays,
    isAssistantOpen,
    setAssistantOpen,
  } = useUIStore();

  const { role } = useAuthStore();
  const { data: meta } = useMeta();
  const { data: health } = useHealth();

  // Part 8: Real browser clock showing actual Indian Standard Time (Asia/Kolkata)
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30000);
    return () => clearInterval(timer);
  }, []);

  const currentIST =
    new Intl.DateTimeFormat("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(now) + " IST";

  const formatIST = (isoString?: string) => {
    if (!isoString) return "Recent";
    try {
      const d = new Date(isoString);
      return (
        d.toLocaleTimeString("en-IN", {
          timeZone: "Asia/Kolkata",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }) + " IST"
      );
    } catch {
      return isoString;
    }
  };

  const variableItems = [
    { id: "rain_mm", label: "Rainfall", icon: CloudRain },
    { id: "tmax_c", label: "Max Temp", icon: Thermometer },
    { id: "wind_max_kmh", label: "Peak Wind", icon: Wind },
  ];

  return (
    <header className="border-b border-[rgba(26,23,18,0.09)] bg-surface px-4 py-2.5 flex items-center justify-between gap-3 sticky top-0 z-40 shadow-[0_1px_0_rgba(26,23,18,0.06)]">
      {/* Left: AAGAM Branding without SIH/NCMRWF/version badge (Part 9) */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-pill text-white rounded-full shadow-pill select-none">
          <CloudRain className="w-3.5 h-3.5 opacity-90" />
          <span className="text-sm font-bold tracking-tight">AAGAM</span>
        </div>
      </div>

      {/* Center: Variable & Lead Controls */}
      <div className="flex items-center gap-2.5 flex-1 justify-center flex-wrap">
        {/* Variable Selector — pill group */}
        <div className="flex items-center bg-[#F0EDE7] p-0.5 rounded-full border border-[rgba(26,23,18,0.09)]">
          {variableItems.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setSelectedVariable(id as WeatherVariable)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all duration-150 ${
                selectedVariable === id
                  ? "bg-pill text-white shadow-pill"
                  : "text-text-secondary hover:text-text-primary hover:bg-white/60"
              }`}
            >
              <Icon className="w-3 h-3" />
              <span>{label}</span>
            </button>
          ))}
        </div>

        {/* Lead Day Picker (0..7 without +0) (Part 7) */}
        <div className="hidden lg:flex items-center gap-0.5 bg-[#F0EDE7] p-0.5 rounded-full border border-[rgba(26,23,18,0.09)]">
          <span className="px-2 text-[10px] uppercase tracking-wider text-text-muted font-semibold">
            Lead
          </span>
          {[0, 1, 2, 3, 4, 5, 6, 7].map((lead) => (
            <button
              key={lead}
              onClick={() => setSelectedLeadDays(lead)}
              className={`w-6 h-6 rounded-full flex items-center justify-center font-mono text-xs transition-all duration-150 ${
                selectedLeadDays === lead
                  ? "bg-pill text-white shadow-pill font-bold"
                  : "text-text-secondary hover:text-text-primary hover:bg-white/60"
              }`}
            >
              {lead}
            </button>
          ))}
        </div>
      </div>

      {/* Right: Real Clock, Freshness, Role, Assistant */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Real browser clock (Part 8) */}
        <div
          title="Current Indian Standard Time (Asia/Kolkata)"
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[#F0EDE7] rounded-full border border-[rgba(26,23,18,0.09)] text-[11px] text-text-primary font-mono"
        >
          <Clock className="w-3 h-3 text-brand-blue" />
          <span className="font-semibold">{currentIST}</span>
        </div>

        {/* Pipeline Last Blended separate timestamp (Part 8) */}
        {meta?.last_run?.started_at && (
          <div
            title="Latest blending pipeline run"
            className="hidden xl:flex items-center gap-1 px-2.5 py-1.5 bg-[#F0EDE7] rounded-full border border-[rgba(26,23,18,0.09)] text-[10px] text-text-muted font-mono"
          >
            <span>Last run:</span>
            <span className="text-text-secondary">{formatIST(meta.last_run.started_at)}</span>
          </div>
        )}

        {/* Health dot */}
        <div
          title={
            health?.supabase_connected
              ? "API & Supabase Connected"
              : "Connecting…"
          }
          className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[#F0EDE7] rounded-full border border-[rgba(26,23,18,0.09)]"
        >
          <div
            className={`w-2 h-2 rounded-full ${
              health?.supabase_connected
                ? "bg-hazard-normal animate-pulse"
                : "bg-[#D9A441]"
            }`}
          />
          <span className="text-[10px] font-mono text-text-muted hidden sm:inline">
            {health?.supabase_connected ? "ONLINE" : "SYNCING"}
          </span>
        </div>

        {/* Role Presentation (Part 15: Public, Forecaster, Forecaster Coordinator) */}
        {role === "coordinator" ? (
          <div
            title="Authenticated Forecaster Coordinator"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[#F0EDE7] rounded-full border border-accent/40 text-xs font-semibold text-accent"
          >
            <Shield className="w-3.5 h-3.5 text-accent" />
            <span>Forecaster Coordinator</span>
          </div>
        ) : role === "forecaster" ? (
          <div
            title="Authenticated Forecaster"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[#F0EDE7] rounded-full border border-[rgba(26,23,18,0.09)] text-xs font-semibold text-brand-blue"
          >
            <Shield className="w-3.5 h-3.5 text-brand-blue" />
            <span>Forecaster</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-[#F0EDE7] rounded-full border border-[rgba(26,23,18,0.09)] text-xs text-text-secondary">
              <span>Public</span>
            </div>
            <button
              onClick={() => {
                const target = document.querySelector('button[data-tab="settings"]') as HTMLButtonElement;
                if (target) {
                  target.click();
                } else {
                  window.location.hash = "#settings";
                }
              }}
              className="hidden sm:flex items-center gap-1 px-2.5 py-1.5 bg-pill text-white rounded-full text-xs font-medium hover:opacity-90 transition-opacity shadow-pill"
              title="Forecaster Login & Registration"
            >
              <LogIn className="w-3 h-3" />
              <span>Forecaster Portal</span>
            </button>
          </div>
        )}

        {/* Animated Assistant Button */}
        <AnimatedAssistantButton
          isOpen={isAssistantOpen}
          onClick={() => setAssistantOpen(!isAssistantOpen)}
        />
      </div>
    </header>
  );
};
