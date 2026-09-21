import React from "react";
import {
  Shield,
  Clock,
  Database,
  ExternalLink,
} from "lucide-react";
import { useAuthStore } from "@/auth/authStore";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export const SettingsPage: React.FC = () => {
  const { role, demoProfile, signOut } = useAuthStore();

  return (
    <div className="space-y-4 font-sans max-w-4xl">
      {/* Active Profile Card */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Shield className="w-4 h-4 text-brand-blue" />
              <span>Operational Authentication & Role Context</span>
            </CardTitle>
            <CardDescription>
              Role-Based Access Control enforced at PostgreSQL RLS and FastAPI layers
            </CardDescription>
          </div>
          <Badge
            variant={role === "admin" ? "alert" : role === "forecaster" ? "watch" : "normal"}
          >
            {role.toUpperCase()}
          </Badge>
        </CardHeader>

        <div className="p-3 bg-[#21262d] rounded-lg border border-border space-y-2 text-xs">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <span className="text-text-muted text-[11px] block">Active User Persona:</span>
              <span className="font-semibold text-text-primary">
                {demoProfile?.name || "Authenticated Operator"}
              </span>
            </div>
            <div>
              <span className="text-text-muted text-[11px] block">Designation / Role:</span>
              <span className="text-text-secondary">
                {demoProfile?.title || "Operational Duty User"}
              </span>
            </div>
          </div>
          <div>
            <span className="text-text-muted text-[11px] block">Organization:</span>
            <span className="text-text-secondary">
              {demoProfile?.organization || "Ministry of Earth Sciences (MoES)"}
            </span>
          </div>
        </div>

        <div className="mt-3 flex justify-end">
          <Button variant="outline" size="sm" onClick={() => signOut()}>
            Reset / Sign Out
          </Button>
        </div>
      </Card>

      {/* System Settings & Timezone */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Clock className="w-4 h-4 text-emerald-400" />
              <span>Timezone & Accumulation Standards</span>
            </CardTitle>
            <CardDescription>
              Authoritative meteorological conventions implemented in AAGAM
            </CardDescription>
          </div>
        </CardHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <div className="p-3 bg-[#21262d] rounded border border-border space-y-1">
            <span className="font-semibold text-text-primary block">Display Timezone</span>
            <span className="font-mono text-brand-blue font-bold text-sm block">
              Asia/Kolkata (IST · UTC+05:30)
            </span>
            <p className="text-[11px] text-text-muted">
              All dates and timestamps rendered in the dashboard reflect Indian Standard Time.
            </p>
          </div>

          <div className="p-3 bg-[#21262d] rounded border border-border space-y-1">
            <span className="font-semibold text-text-primary block">Rainfall Accumulation Window</span>
            <span className="font-mono text-emerald-400 font-bold text-sm block">
              08:30 IST to 08:30 IST (24 Hours)
            </span>
            <p className="text-[11px] text-text-muted">
              Matches standard IMD synoptic rain-gauge observational windows (03:00 UTC to 03:00 UTC).
            </p>
          </div>
        </div>
      </Card>

      {/* Statutory Attribution & Compliance (PRD §10.4 FR-UI-9 & §13) */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Database className="w-4 h-4 text-purple-400" />
              <span>Data Attribution & Licensing Notice</span>
            </CardTitle>
            <CardDescription>
              Compliance with open scientific datasets and MoES / IMD terms of use
            </CardDescription>
          </div>
        </CardHeader>

        <div className="space-y-3 text-xs text-text-secondary leading-relaxed">
          <div className="p-3 bg-[#21262d] rounded border border-border">
            <div className="flex items-center justify-between font-semibold text-text-primary">
              <span>1. Open-Meteo API (NWP Model Data)</span>
              <a
                href="https://open-meteo.com/"
                target="_blank"
                rel="noreferrer"
                className="text-brand-blue flex items-center gap-1 hover:underline text-[11px]"
              >
                <span>open-meteo.com</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <p className="mt-1 text-text-muted text-[11px]">
              Weather forecast data sourced under{" "}
              <strong>Creative Commons Attribution 4.0 International (CC BY 4.0)</strong> license
              from Open-Meteo. Includes GFS (NOAA), ECMWF IFS 0.25°, DWD ICON, and ECMWF AIFS (AI model).
            </p>
          </div>

          <div className="p-3 bg-[#21262d] rounded border border-border">
            <div className="flex items-center justify-between font-semibold text-text-primary">
              <span>2. India Meteorological Department (Ground Truth)</span>
              <a
                href="https://www.imdpune.gov.in/"
                target="_blank"
                rel="noreferrer"
                className="text-brand-blue flex items-center gap-1 hover:underline text-[11px]"
              >
                <span>imdpune.gov.in</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            </div>
            <p className="mt-1 text-text-muted text-[11px]">
              Rainfall ground truth verification data derived from IMD 0.25° gridded daily rainfall
              datasets (Pai et al.). Heatwave criteria strictly adhere to official IMD thresholds.
            </p>
          </div>

          <div className="p-3 bg-amber-950/20 rounded border border-amber-800/40 text-amber-200 text-[11px]">
            <strong>Important Operational Notice:</strong> AAGAM is an automated AI-Grid
            assimilation and multi-model post-processing decision support tool developed for SIH
            2026 Problem Statement 26081 (MoES / NCMRWF). Guidance produced is for operational
            situational awareness and does not supersede statutory public weather warnings.
          </div>
        </div>
      </Card>
    </div>
  );
};
