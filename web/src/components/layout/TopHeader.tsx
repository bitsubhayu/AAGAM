import React, { useState } from "react";
import {
  CloudRain,
  Thermometer,
  Wind,
  Clock,
  Sparkles,
  Shield,
  ChevronDown,
  CheckCircle2,
} from "lucide-react";
import { useUIStore } from "@/store/uiStore";
import { useAuthStore, DEMO_PROFILES, type UserRole } from "@/auth/authStore";
import { useMeta } from "@/api/useMeta";
import { useHealth } from "@/api/useHealth";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";

export const TopHeader: React.FC = () => {
  const {
    selectedVariable,
    setSelectedVariable,
    selectedLeadDays,
    setSelectedLeadDays,
    isAssistantOpen,
    setAssistantOpen,
  } = useUIStore();

  const { role, setDemoRole } = useAuthStore();
  const { data: meta } = useMeta();
  const { data: health } = useHealth();
  const [roleModalOpen, setRoleModalOpen] = useState(false);

  const formatIST = (isoString?: string) => {
    if (!isoString) return "Recent (06:00 UTC)";
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString("en-IN", {
        timeZone: "Asia/Kolkata",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }) + " IST";
    } catch {
      return isoString;
    }
  };

  const activeVersionStr = meta?.active_model_version?.id
    ? `v${meta.active_model_version.id}`
    : (meta ? "v1" : "...");

  return (
    <header className="border-b border-border bg-surface px-4 py-2.5 flex items-center justify-between gap-4 sticky top-0 z-40">
      {/* Left: Branding & SIH Context */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="p-1.5 bg-blue-500/10 border border-blue-500/30 rounded-md text-brand-blue">
          <CloudRain className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-bold tracking-tight text-text-primary">
              AAGAM
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#21262d] text-text-muted border border-border font-mono">
              SIH 26081 · NCMRWF
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-950/40 text-blue-300 border border-blue-800/50 font-mono">
              {activeVersionStr}
            </span>
          </div>
          <p className="text-[11px] text-text-muted hidden md:block">
            Adaptive AI-Grid Assimilation Model · Multi-Model Ensemble
          </p>
        </div>
      </div>

      {/* Center: Variable & Lead Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Variable Selector */}
        <div className="flex items-center bg-[#21262d] p-0.5 rounded-md border border-border">
          <button
            onClick={() => setSelectedVariable("rain_mm")}
            className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
              selectedVariable === "rain_mm"
                ? "bg-brand-blue text-white shadow-xs"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <CloudRain className="w-3.5 h-3.5" />
            <span>Rainfall</span>
          </button>
          <button
            onClick={() => setSelectedVariable("tmax_c")}
            className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
              selectedVariable === "tmax_c"
                ? "bg-brand-blue text-white shadow-xs"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <Thermometer className="w-3.5 h-3.5" />
            <span>Max Temp</span>
          </button>
          <button
            onClick={() => setSelectedVariable("wind_max_kmh")}
            className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors ${
              selectedVariable === "wind_max_kmh"
                ? "bg-brand-blue text-white shadow-xs"
                : "text-text-secondary hover:text-text-primary"
            }`}
          >
            <Wind className="w-3.5 h-3.5" />
            <span>Peak Wind</span>
          </button>
        </div>

        {/* Lead Day Picker (0-7) */}
        <div className="hidden lg:flex items-center gap-1 bg-[#21262d] p-0.5 rounded-md border border-border text-xs">
          <span className="px-2 text-[10px] uppercase tracking-wider text-text-muted font-medium">
            Lead
          </span>
          {[0, 1, 2, 3, 4, 5, 6, 7].map((lead) => (
            <button
              key={lead}
              onClick={() => setSelectedLeadDays(lead)}
              className={`w-6 h-6 rounded flex items-center justify-center font-mono text-xs transition-colors ${
                selectedLeadDays === lead
                  ? "bg-brand-blue text-white font-bold"
                  : "text-text-secondary hover:text-text-primary hover:bg-[#30363d]"
              }`}
            >
              +{lead}
            </button>
          ))}
        </div>
      </div>

      {/* Right: Freshness, Role Switcher & Assistant Trigger */}
      <div className="flex items-center gap-2.5 shrink-0">
        {/* Freshness Badge */}
        <div className="hidden sm:flex items-center gap-1.5 px-2 py-1 bg-[#21262d] rounded border border-border text-[11px] text-text-muted font-mono">
          <Clock className="w-3 h-3 text-emerald-400" />
          <span>{formatIST(meta?.last_run?.started_at)}</span>
        </div>

        {/* Health status dot */}
        <div
          title={
            health?.supabase_connected
              ? "API & Supabase Connected (AWS Mumbai)"
              : "Connecting..."
          }
          className="flex items-center gap-1 px-2 py-1 bg-[#21262d] rounded border border-border text-[11px]"
        >
          <div
            className={`w-2 h-2 rounded-full ${
              health?.supabase_connected ? "bg-emerald-400 animate-pulse" : "bg-yellow-400"
            }`}
          />
          <span className="text-[10px] font-mono text-text-muted hidden md:inline">
            {health?.supabase_connected ? "ONLINE" : "SYNCING"}
          </span>
        </div>

        {/* Demo Role Switcher Button */}
        <button
          onClick={() => setRoleModalOpen(true)}
          className="flex items-center gap-1.5 px-2.5 py-1 bg-[#21262d] hover:bg-[#30363d] rounded border border-border text-xs transition-colors"
        >
          <Shield className="w-3.5 h-3.5 text-brand-blue" />
          <span className="capitalize font-semibold text-text-primary">{role}</span>
          <ChevronDown className="w-3 h-3 text-text-muted" />
        </button>

        {/* Assistant Drawer Button */}
        <Button
          variant={isAssistantOpen ? "primary" : "secondary"}
          size="sm"
          onClick={() => setAssistantOpen(!isAssistantOpen)}
          className="relative"
        >
          <Sparkles className="w-3.5 h-3.5 text-brand-orange" />
          <span className="hidden sm:inline">Assistant</span>
        </Button>
      </div>

      {/* Role Switcher Modal */}
      <Modal
        isOpen={roleModalOpen}
        onClose={() => setRoleModalOpen(false)}
        title="Duty Role & RBAC Switcher"
        description="Select an operational persona to simulate role-based authorization constraints across AAGAM."
        maxWidth="md"
      >
        <div className="space-y-3">
          {(["viewer", "forecaster", "admin"] as UserRole[]).map((r) => {
            const p = DEMO_PROFILES[r];
            const isCurrent = role === r;
            return (
              <div
                key={r}
                onClick={() => {
                  setDemoRole(r);
                  setRoleModalOpen(false);
                }}
                className={`p-3 rounded-lg border cursor-pointer transition-all flex items-start justify-between ${
                  isCurrent
                    ? "bg-brand-blue/10 border-brand-blue"
                    : "bg-[#21262d] border-border hover:border-text-muted"
                }`}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-text-primary">{p.name}</span>
                    <Badge
                      variant={r === "admin" ? "alert" : r === "forecaster" ? "watch" : "normal"}
                    >
                      {r.toUpperCase()}
                    </Badge>
                  </div>
                  <p className="text-xs text-text-secondary mt-0.5">{p.title}</p>
                  <p className="text-[10px] text-text-muted">{p.organization}</p>
                  <div className="mt-2 text-[10px] text-text-muted font-mono">
                    {r === "viewer" && "Permissions: Read-only dashboards, skill tables, CSV export"}
                    {r === "forecaster" && "Permissions: Read + Acknowledge alerts + Audited weight overrides"}
                    {r === "admin" && "Permissions: Full access + Model activation & 1-click rollback"}
                  </div>
                </div>
                {isCurrent && <CheckCircle2 className="w-4 h-4 text-brand-blue shrink-0 mt-1" />}
              </div>
            );
          })}
        </div>
      </Modal>
    </header>
  );
};
