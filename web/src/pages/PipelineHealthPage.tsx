import React, { useState } from "react";
import {
  Server,
  RotateCcw,
  AlertCircle,
  Activity,
} from "lucide-react";
import { usePipelineStatus } from "@/api/usePipeline";
import { useAuthStore } from "@/auth/authStore";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { PipelineRunsTable } from "@/components/pipeline/PipelineRunsTable";
import { ModelActivationModal } from "@/components/pipeline/ModelActivationModal";
import { Skeleton } from "@/components/ui/Skeleton";

export const PipelineHealthPage: React.FC = () => {
  const { role } = useAuthStore();
  const { data: pipeline, isLoading, error } = usePipelineStatus();
  const [activationModalOpen, setActivationModalOpen] = useState(false);

  const isAdmin = role === "admin";
  const activeVer = pipeline?.active_model_version;
  const runs = pipeline?.last_runs || [];

  const successfulRuns = runs.filter((r) => r.status?.toLowerCase() === "success").length;
  const totalEstCalls = runs.reduce((acc, r) => acc + (r.api_calls_est ?? 0), 0);

  return (
    <div className="space-y-4 font-sans">
      {/* Top Header Card */}
      <div className="bg-[#161b22] p-4 rounded-lg border border-border flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-500/10 border border-purple-500/30 rounded-lg text-purple-400">
            <Server className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
              <span>Pipeline Health & Operational Telemetry</span>
              <Badge variant="normal">OPERATIONAL</Badge>
            </h2>
            <p className="text-xs text-text-muted mt-0.5">
              Scheduled GitHub Actions 6-hourly ingestion, blending cycles & weekly auto-retrain
            </p>
          </div>
        </div>

        {/* Admin Rollback Action */}
        <div>
          <Button
            variant={isAdmin ? "primary" : "secondary"}
            size="sm"
            onClick={() => setActivationModalOpen(true)}
            disabled={!isAdmin}
            title={isAdmin ? "Activate / Rollback model" : "Admin role required"}
          >
            <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
            <span>{isAdmin ? "Activate / Rollback Model" : "Admin Only (Rollback)"}</span>
          </Button>
        </div>
      </div>

      {/* Telemetry KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <Card compact>
          <span className="text-[11px] font-medium text-text-muted">Active Model Version</span>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-xl font-bold font-mono text-brand-blue">
              {isLoading ? "..." : activeVer?.id ? `v${activeVer.id}` : "v1"}
            </span>
            <span className="text-[10px] text-emerald-400 font-mono">REGULARIZED</span>
          </div>
          <p className="text-[10px] text-text-muted mt-1 truncate font-mono">
            {activeVer?.storage_path || "Active production weights"}
          </p>
        </Card>

        <Card compact>
          <span className="text-[11px] font-medium text-text-muted">Pipeline Success Rate</span>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-xl font-bold font-mono text-emerald-400">
              {runs.length > 0 ? `${Math.round((successfulRuns / runs.length) * 100)}%` : "—"}
            </span>
            <span className="text-[10px] text-text-muted">
              {runs.length > 0 ? `(${successfulRuns}/${runs.length} cycles)` : "No recorded cycles"}
            </span>
          </div>
          <p className="text-[10px] text-text-muted mt-1">
            {runs.length > 0 && successfulRuns === runs.length
              ? "Zero dropped blending cycles"
              : "Operational cycle monitoring"}
          </p>
        </Card>

        <Card compact>
          <span className="text-[11px] font-medium text-text-muted">Est. Daily API Calls</span>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-xl font-bold font-mono text-text-primary">
              {totalEstCalls > 0 ? `${Math.round(totalEstCalls)} / 10,000` : "— / 10,000"}
            </span>
            <span className="text-[10px] text-emerald-400 font-mono">
              {totalEstCalls > 0
                ? `${((totalEstCalls / 10000) * 100).toFixed(1)}% of cap`
                : "Free tier cap"}
            </span>
          </div>
          <p className="text-[10px] text-text-muted mt-1">Open-Meteo non-commercial quota</p>
        </Card>

        <Card compact>
          <span className="text-[11px] font-medium text-text-muted">Database Storage Pooler</span>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-xl font-bold font-mono text-text-primary">
              Port 6543
            </span>
            <span className="text-[10px] text-brand-blue font-mono">Transaction Pool</span>
          </div>
          <p className="text-[10px] text-text-muted mt-1">statement_cache_size=0 active</p>
        </Card>
      </div>

      {/* Execution Runs Table */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Activity className="w-4 h-4 text-brand-blue" />
              <span>Pipeline Execution Log (Latest 20 Ingestion & Blending Cycles)</span>
            </CardTitle>
            <CardDescription>
              Telemetry metrics recorded to Supabase PostgreSQL pipeline_runs table
            </CardDescription>
          </div>
        </CardHeader>

        {isLoading ? (
          <div className="py-8">
            <Skeleton className="h-48 w-full" />
          </div>
        ) : error ? (
          <div className="py-8 text-center text-xs text-text-muted">
            <AlertCircle className="w-6 h-6 text-hazard-advisory mx-auto mb-2" />
            Unable to fetch pipeline execution telemetry.
          </div>
        ) : (
          <PipelineRunsTable runs={runs} />
        )}
      </Card>

      {/* Admin Activation Modal */}
      <ModelActivationModal
        isOpen={activationModalOpen}
        onClose={() => setActivationModalOpen(false)}
        currentActiveVersionId={activeVer?.id}
      />
    </div>
  );
};
