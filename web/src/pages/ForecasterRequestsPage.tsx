import React, { useState, useEffect } from "react";
import {
  UserCheck,
  Clock,
  Mail,
  Building,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  Award,
  Sparkles,
  ShieldAlert,
} from "lucide-react";
import { useAuthStore } from "@/auth/authStore";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  fetchForecasterRequests,
  approveForecasterRequest,
  rejectForecasterRequest,
  fetchForecasters,
  promoteCoordinator,
  type ForecasterItem,
} from "@/api/client";
import type { ForecasterAccessRequestItem } from "@/api/types";
import { toast } from "sonner";

export const ForecasterRequestsPage: React.FC = () => {
  const { role, user } = useAuthStore();
  const [requests, setRequests] = useState<ForecasterAccessRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("pending");

  // Forecaster directory & Coordinator promotion state
  const [forecasters, setForecasters] = useState<ForecasterItem[]>([]);
  const [loadingForecasters, setLoadingForecasters] = useState(false);
  const [promotingId, setPromotingId] = useState<string | null>(null);

  const loadRequests = async () => {
    try {
      setLoading(true);
      const data = await fetchForecasterRequests(statusFilter === "all" ? undefined : statusFilter);
      setRequests(data);
    } catch (err: any) {
      toast.error(err.message || "Failed to load forecaster access requests");
    } finally {
      setLoading(false);
    }
  };

  const loadForecasters = async () => {
    try {
      setLoadingForecasters(true);
      const data = await fetchForecasters();
      setForecasters(data);
    } catch (err: any) {
      console.warn("Failed to load forecasters directory:", err);
    } finally {
      setLoadingForecasters(false);
    }
  };

  useEffect(() => {
    if (role === "coordinator") {
      loadRequests();
      loadForecasters();
    }
  }, [role, statusFilter]);

  if (role !== "coordinator") {
    return (
      <div className="p-8 max-w-xl mx-auto text-center space-y-3 font-sans">
        <ShieldAlert className="w-10 h-10 text-hazard-alert mx-auto" />
        <h2 className="text-base font-bold text-text-primary">Coordinator Privilege Required</h2>
        <p className="text-xs text-text-muted">
          The Forecaster Requests governance panel is strictly restricted to authenticated Forecaster Coordinators.
        </p>
      </div>
    );
  }

  const handleApprove = async (req: ForecasterAccessRequestItem) => {
    try {
      setProcessingId(req.id);
      const resp = await approveForecasterRequest(req.id);
      toast.success(resp.message || `Approved forecaster access for ${req.name}`);
      await loadRequests();
      await loadForecasters();
    } catch (err: any) {
      toast.error(err.message || "Failed to approve access request");
    } finally {
      setProcessingId(null);
    }
  };

  const handleReject = async (req: ForecasterAccessRequestItem) => {
    if (!confirm(`Are you sure you want to decline the forecaster request from ${req.name}?`)) {
      return;
    }
    try {
      setProcessingId(req.id);
      const resp = await rejectForecasterRequest(req.id);
      toast.success(resp.message || `Declined request for ${req.name}`);
      await loadRequests();
    } catch (err: any) {
      toast.error(err.message || "Failed to reject access request");
    } finally {
      setProcessingId(null);
    }
  };

  const handlePromote = async (targetId: string, targetName: string) => {
    if (!confirm(`Are you sure you want to promote ${targetName} to Forecaster Coordinator?`)) {
      return;
    }
    try {
      setPromotingId(targetId);
      await promoteCoordinator(targetId);
      toast.success(`${targetName} promoted to Forecaster Coordinator!`);
      await loadForecasters();
    } catch (err: any) {
      toast.error(err.message || "Failed to promote user to coordinator");
    } finally {
      setPromotingId(null);
    }
  };

  const formatIST = (isoString?: string | null) => {
    if (!isoString) return "—";
    try {
      const d = new Date(isoString);
      return (
        d.toLocaleDateString("en-IN", {
          day: "2-digit",
          month: "short",
          year: "numeric",
          timeZone: "Asia/Kolkata",
        }) +
        " " +
        d.toLocaleTimeString("en-IN", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
          timeZone: "Asia/Kolkata",
        }) +
        " IST"
      );
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-6 font-sans max-w-5xl animate-fade-in pb-12">
      {/* Header Card */}
      <Card className="p-4">
        <CardHeader className="pb-3 mb-2 border-b border-[rgba(26,23,18,0.06)]">
          <div>
            <CardTitle>
              <UserCheck className="w-4 h-4 text-accent" />
              <span>Forecaster Requests</span>
            </CardTitle>
            <CardDescription>
              Governance panel for reviewing and approving Forecaster access requests and promoting verified Forecasters
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                loadRequests();
                loadForecasters();
              }}
              disabled={loading}
              className="text-xs flex items-center gap-1.5"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </Button>
          </div>
        </CardHeader>

        {/* Filter bar */}
        <div className="flex items-center gap-2 text-xs pt-1">
          <span className="text-text-muted text-[11px] font-medium">Status Filter:</span>
          {["pending", "approved", "all"].map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
                statusFilter === status
                  ? "bg-accent text-white shadow-pill font-semibold"
                  : "bg-[#F0EDE7] text-text-secondary hover:text-text-primary"
              }`}
            >
              {status === "all"
                ? "All Requests"
                : status.charAt(0).toUpperCase() + status.slice(1)}
            </button>
          ))}
        </div>
      </Card>

      {/* Requests List Card */}
      <Card className="p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
            Access Requests ({requests.length})
          </h3>
        </div>

        {loading ? (
          <div className="py-12 text-center text-xs text-text-muted">
            <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-accent" />
            Loading access requests…
          </div>
        ) : requests.length === 0 ? (
          <div className="py-12 text-center text-xs text-text-muted bg-[#FAF9F5] rounded-lg border border-[rgba(26,23,18,0.06)]">
            <CheckCircle2 className="w-6 h-6 text-emerald-600 mx-auto mb-2 opacity-60" />
            <p className="font-medium text-text-primary">No {statusFilter} access requests found</p>
            <p className="text-[11px] text-text-muted mt-1">
              New forecaster applicants will appear here when they submit access requests.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-[rgba(26,23,18,0.06)] border border-[rgba(26,23,18,0.08)] rounded-lg overflow-hidden bg-white">
            {requests.map((req) => {
              const isPending = req.status === "pending";
              const isApproved = req.status === "approved";
              const isBusy = processingId === req.id;

              return (
                <div
                  key={req.id}
                  className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 text-xs hover:bg-[#FAF9F5] transition-colors"
                >
                  <div className="space-y-1.5 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm text-text-primary">{req.name}</span>
                      <Badge
                        variant={
                          isPending ? "watch" : isApproved ? "normal" : "alert"
                        }
                      >
                        {req.status.toUpperCase()}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-text-muted">
                      <div className="flex items-center gap-1.5">
                        <Mail className="w-3.5 h-3.5 text-text-muted shrink-0" />
                        <span className="font-mono text-text-primary font-medium">{req.email}</span>
                      </div>
                      {req.institution && (
                        <div className="flex items-center gap-1.5">
                          <Building className="w-3.5 h-3.5 text-text-muted shrink-0" />
                          <span>{req.institution}</span>
                        </div>
                      )}
                      <div className="flex items-center gap-1.5">
                        <Clock className="w-3.5 h-3.5 text-text-muted shrink-0" />
                        <span>Submitted: {formatIST(req.created_at)}</span>
                      </div>
                      {req.reviewed_at && (
                        <div className="flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-text-muted shrink-0" />
                          <span>
                            Reviewed by {req.reviewer_name || "Coordinator"} on {formatIST(req.reviewed_at)}
                          </span>
                        </div>
                      )}
                    </div>

                    {req.reason && (
                      <p className="text-[11px] text-text-secondary bg-[#F0EDE7]/60 p-2 rounded mt-1.5 border border-[rgba(26,23,18,0.06)]">
                        <span className="font-semibold text-text-primary">Justification: </span>
                        {req.reason}
                      </p>
                    )}
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {isPending ? (
                      <>
                        <Button
                          size="sm"
                          disabled={isBusy}
                          onClick={() => handleApprove(req)}
                          className="bg-accent text-white hover:bg-accent/90 text-xs font-medium flex items-center gap-1"
                        >
                          {isBusy ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
                          ) : (
                            <CheckCircle2 className="w-3.5 h-3.5 mr-1" />
                          )}
                          <span>Approve Forecaster Access</span>
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={isBusy}
                          onClick={() => handleReject(req)}
                          className="text-xs text-hazard-alert hover:bg-red-50 border-red-200"
                        >
                          <XCircle className="w-3.5 h-3.5 mr-1 text-hazard-alert" />
                          <span>Decline</span>
                        </Button>
                      </>
                    ) : (
                      <span className="text-[11px] text-text-muted italic px-2 py-1 bg-[#F0EDE7] rounded">
                        {isApproved ? "Approved as Forecaster" : "Declined"}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Verified Forecaster Directory & Coordinator Promotion */}
      <Card className="p-4">
        <CardHeader className="pb-3 mb-2 border-b border-[rgba(26,23,18,0.06)]">
          <div>
            <CardTitle>
              <Award className="w-4 h-4 text-brand-orange" />
              <span>Promote Forecaster to Coordinator</span>
            </CardTitle>
            <CardDescription>
              Coordinators can promote existing verified Forecasters to Coordinator. Public users cannot be promoted directly. Self-promotion is disallowed.
            </CardDescription>
          </div>
        </CardHeader>

        {loadingForecasters ? (
          <div className="py-6 text-center text-xs text-text-muted">
            <Loader2 className="w-4 h-4 animate-spin mx-auto mb-1.5 text-accent" />
            Loading forecasters directory…
          </div>
        ) : forecasters.length === 0 ? (
          <div className="py-6 text-center text-xs text-text-muted">
            No registered forecasters found.
          </div>
        ) : (
          <div className="divide-y divide-[rgba(26,23,18,0.06)] border border-[rgba(26,23,18,0.08)] rounded-lg overflow-hidden bg-white">
            {forecasters.map((f) => {
              const isCurrentCoordinator = f.role === "coordinator";
              const isSelf = f.id === user?.id;

              return (
                <div
                  key={f.id}
                  className="p-3 flex items-center justify-between gap-3 text-xs hover:bg-[#FAF9F5] transition-colors"
                >
                  <div>
                    <div className="font-semibold text-text-primary flex items-center gap-1.5">
                      <span>{f.name || f.email || f.id.slice(0, 8)}</span>
                      {isCurrentCoordinator && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 font-medium">
                          Coordinator
                        </span>
                      )}
                      {isSelf && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-800 font-medium">
                          You
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] text-text-muted font-mono">
                      {f.email} {f.org ? `· ${f.org}` : ""}
                    </div>
                  </div>

                  <div>
                    {isCurrentCoordinator ? (
                      <span className="text-[11px] text-text-muted italic px-2 py-1 bg-[#F0EDE7] rounded">
                        Coordinator
                      </span>
                    ) : isSelf ? (
                      <span className="text-[11px] text-text-muted italic px-2 py-1 bg-[#F0EDE7] rounded">
                        Self
                      </span>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={promotingId === f.id}
                        onClick={() => handlePromote(f.id, f.name || f.email || "Forecaster")}
                        className="text-xs"
                      >
                        {promotingId === f.id ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
                        ) : (
                          <Sparkles className="w-3.5 h-3.5 mr-1 text-accent" />
                        )}
                        <span>Promote to Coordinator</span>
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
};
