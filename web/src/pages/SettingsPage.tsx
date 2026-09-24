import React, { useState, useEffect } from "react";
import {
  Shield,
  Clock,
  Database,
  ExternalLink,
  UserCheck,
  Mail,
  Building,
  User,
  KeyRound,
  Loader2,
  Sparkles,
  Award,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { useAuthStore } from "@/auth/authStore";
import { supabase } from "@/auth/supabase";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  requestForecasterOtp,
  verifyForecasterOtp,
  checkForecasterAccess,
  requestForecasterAccess,
  fetchForecasters,
  promoteCoordinator,
  type ForecasterItem,
} from "@/api/client";
import { toast } from "sonner";

export const SettingsPage: React.FC = () => {
  const { role, user, profile, signOut, setSession } = useAuthStore();

  // Forecaster Access state
  const [email, setEmail] = useState("");
  const [accessStage, setAccessStage] = useState<"enter_email" | "approved" | "unapproved" | "submitted">("enter_email");
  const [checkingAccess, setCheckingAccess] = useState(false);
  const [approvedRole, setApprovedRole] = useState<string | null>(null);

  // OTP state (for approved Case A)
  const [otpToken, setOtpToken] = useState("");
  const [submittingOtp, setSubmittingOtp] = useState(false);

  // Request Access state (for unapproved Case B)
  const [reqName, setReqName] = useState("");
  const [reqOrg, setReqOrg] = useState("");
  const [reqReason, setReqReason] = useState("");
  const [submittingReq, setSubmittingReq] = useState(false);

  // Coordinator promotion state
  const [forecasters, setForecasters] = useState<ForecasterItem[]>([]);
  const [loadingForecasters, setLoadingForecasters] = useState(false);
  const [promotingId, setPromotingId] = useState<string | null>(null);

  useEffect(() => {
    if (role === "coordinator") {
      setLoadingForecasters(true);
      fetchForecasters()
        .then((list) => setForecasters(list))
        .catch(() => toast.error("Could not load forecasters list"))
        .finally(() => setLoadingForecasters(false));
    }
  }, [role]);

  const handleCheckAccess = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail || !cleanEmail.includes("@")) {
      toast.error("Please enter a valid email address.");
      return;
    }
    try {
      setCheckingAccess(true);
      const res = await checkForecasterAccess(cleanEmail);
      if (res.approved) {
        setAccessStage("approved");
        setApprovedRole(res.role || "forecaster");
        try {
          await requestForecasterOtp("Forecaster", "AAGAM", cleanEmail);
          toast.success("Verification code dispatched to your email!");
        } catch (otpErr: any) {
          toast.error(otpErr.message || "Failed to dispatch verification code");
        }
      } else {
        setAccessStage("unapproved");
      }
    } catch (err: any) {
      toast.error(err.message || "Failed to verify access status");
    } finally {
      setCheckingAccess(false);
    }
  };

  const handleResendOtp = async () => {
    try {
      setSubmittingOtp(true);
      await requestForecasterOtp("Forecaster", "AAGAM", email.trim().toLowerCase());
      toast.success("New verification code dispatched!");
    } catch (err: any) {
      toast.error(err.message || "Failed to resend code");
    } finally {
      setSubmittingOtp(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = otpToken.trim();
    if (!token || token.length !== 6 || !/^\d+$/.test(token)) {
      toast.error("Please enter the 6-digit numeric verification code.");
      return;
    }
    try {
      setSubmittingOtp(true);
      const resp = await verifyForecasterOtp(email.trim().toLowerCase(), token);
      toast.success("Forecaster authentication verified!");
      if (resp.access_token && resp.refresh_token) {
        const { data } = await supabase.auth.setSession({
          access_token: resp.access_token,
          refresh_token: resp.refresh_token,
        });
        if (data?.session) {
          await setSession(data.session);
        }
      }
      setOtpToken("");
      setAccessStage("enter_email");
    } catch (err: any) {
      toast.error(err.message || "Invalid or expired verification code");
    } finally {
      setSubmittingOtp(false);
    }
  };

  const handleSubmitAccessRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reqName.trim()) {
      toast.error("Please enter your full name.");
      return;
    }
    try {
      setSubmittingReq(true);
      await requestForecasterAccess(
        reqName.trim(),
        email.trim().toLowerCase(),
        reqOrg.trim() || undefined,
        reqReason.trim() || undefined
      );
      toast.success("Forecaster access request recorded!");
      setAccessStage("submitted");
    } catch (err: any) {
      toast.error(err.message || "Failed to submit forecaster access request");
    } finally {
      setSubmittingReq(false);
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
      const updated = await fetchForecasters();
      setForecasters(updated);
    } catch (err: any) {
      toast.error(err.message || "Failed to promote user");
    } finally {
      setPromotingId(null);
    }
  };

  const roleLabels: Record<string, string> = {
    public: "Public",
    forecaster: "Forecaster",
    coordinator: "Forecaster Coordinator",
  };

  return (
    <div className="space-y-4 font-sans max-w-4xl animate-fade-in">
      {/* Active Profile Card */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Shield className="w-4 h-4 text-brand-blue" />
              <span>Authentication & Access Credentials</span>
            </CardTitle>
            <CardDescription>
              Role-Based Access Control enforced at PostgreSQL RLS and FastAPI layers
            </CardDescription>
          </div>
          <Badge
            variant={
              role === "coordinator" ? "alert" : role === "forecaster" ? "watch" : "normal"
            }
          >
            {roleLabels[role] || "Public"}
          </Badge>
        </CardHeader>

        {role === "public" ? (
          <div className="space-y-4">
            <div className="p-3 bg-[#F0EDE7] rounded-lg border border-[rgba(26,23,18,0.10)] space-y-1 text-xs">
              <span className="font-semibold text-text-primary block">
                Public Anonymous Access
              </span>
              <p className="text-text-muted text-[11px] leading-relaxed">
                You are currently browsing with the Public role with full read access to public forecasts, risk maps, skill evaluations, and alerts. To perform operational duties (weight overrides, alert acknowledgements, governance), use the Forecaster Access portal below.
              </p>
            </div>

            {/* Single Forecaster Access Entry Point */}
            <div className="p-4 bg-white border border-[rgba(26,23,18,0.12)] rounded-lg space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
                  <UserCheck className="w-4 h-4 text-accent" />
                  <span>Forecaster Access</span>
                </div>
                {accessStage === "approved" && (
                  <Badge variant="normal">Approved Account</Badge>
                )}
                {accessStage === "unapproved" && (
                  <Badge variant="watch">Approval Required</Badge>
                )}
              </div>

              {accessStage === "enter_email" && (
                <form onSubmit={handleCheckAccess} className="space-y-3">
                  <p className="text-[11px] text-text-muted leading-relaxed">
                    Enter your official email address. Authorized accounts will proceed directly to one-time password verification; unapproved applicants can submit an access request for Coordinator review.
                  </p>
                  <div>
                    <label className="block text-[11px] font-medium text-text-secondary mb-1">
                      Official Email Address
                    </label>
                    <div className="relative">
                      <Mail className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-text-muted" />
                      <input
                        type="email"
                        required
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="forecaster@ncmrwf.gov.in"
                        className="w-full bg-[#FAF9F5] border border-[rgba(26,23,18,0.15)] rounded-md pl-8 pr-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                      />
                    </div>
                  </div>
                  <Button
                    type="submit"
                    disabled={checkingAccess || !email.trim()}
                    className="w-full bg-accent text-surface-dark hover:bg-accent/90 text-xs font-medium"
                  >
                    {checkingAccess ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                    ) : (
                      <KeyRound className="w-3.5 h-3.5 mr-1.5" />
                    )}
                    <span>Continue</span>
                  </Button>
                </form>
              )}

              {/* Case A: Approved Forecaster / Coordinator Email */}
              {accessStage === "approved" && (
                <form onSubmit={handleVerifyOtp} className="space-y-3">
                  <div className="p-2.5 bg-emerald-50 rounded border border-emerald-200 text-xs text-emerald-900 space-y-1">
                    <div className="font-semibold flex items-center gap-1.5">
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-700" />
                      <span>Approved Account Verified ({approvedRole})</span>
                    </div>
                    <p className="text-[11px] text-emerald-800">
                      Verification code dispatched to <span className="font-semibold font-mono">{email}</span>.
                    </p>
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-text-secondary mb-1">
                      Enter 6-Digit Code
                    </label>
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      autoComplete="one-time-code"
                      required
                      value={otpToken}
                      onChange={(e) => {
                        const val = e.target.value.trim();
                        if (val && !/^\d+$/.test(val)) return;
                        if (val.length > 6) return;
                        setOtpToken(val);
                      }}
                      placeholder="123456"
                      className="w-full text-center tracking-widest text-base font-mono bg-[#FAF9F5] border border-[rgba(26,23,18,0.15)] rounded-md py-1.5 text-text-primary focus:outline-none focus:border-accent"
                    />
                  </div>

                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setAccessStage("enter_email");
                        setOtpToken("");
                      }}
                      className="w-1/3 text-xs"
                    >
                      Different Email
                    </Button>
                    <Button
                      type="submit"
                      disabled={submittingOtp || otpToken.length !== 6}
                      size="sm"
                      className="flex-1 bg-accent text-surface-dark hover:bg-accent/90 text-xs font-medium"
                    >
                      {submittingOtp ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                      ) : (
                        <Shield className="w-3.5 h-3.5 mr-1.5" />
                      )}
                      <span>Verify OTP & Sign In</span>
                    </Button>
                  </div>

                  <div className="text-center pt-1">
                    <button
                      type="button"
                      onClick={handleResendOtp}
                      disabled={submittingOtp}
                      className="text-[11px] text-brand-blue hover:underline"
                    >
                      Did not receive code? Resend OTP
                    </button>
                  </div>
                </form>
              )}

              {/* Case B: Unapproved Email -> Request Forecaster Access */}
              {accessStage === "unapproved" && (
                <form onSubmit={handleSubmitAccessRequest} className="space-y-3">
                  <div className="p-3 bg-amber-50 rounded border border-amber-200 text-xs text-amber-900 space-y-1">
                    <div className="font-semibold flex items-center gap-1.5">
                      <AlertCircle className="w-3.5 h-3.5 text-amber-700" />
                      <span>Request Forecaster Access</span>
                    </div>
                    <p className="text-[11px] text-amber-800 leading-relaxed">
                      The address <strong className="font-mono">{email}</strong> is not an approved Forecaster or Coordinator. Normal login is disabled for unregistered accounts. Please submit your candidate details below to request operational access.
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    <div>
                      <label className="block text-[11px] font-medium text-text-secondary mb-1">
                        Full Name *
                      </label>
                      <div className="relative">
                        <User className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-text-muted" />
                        <input
                          type="text"
                          required
                          value={reqName}
                          onChange={(e) => setReqName(e.target.value)}
                          placeholder="Dr. S. K. Roy"
                          className="w-full bg-[#FAF9F5] border border-[rgba(26,23,18,0.15)] rounded-md pl-8 pr-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-[11px] font-medium text-text-secondary mb-1">
                        Institution / Organization
                      </label>
                      <div className="relative">
                        <Building className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-text-muted" />
                        <input
                          type="text"
                          value={reqOrg}
                          onChange={(e) => setReqOrg(e.target.value)}
                          placeholder="IMD / NCMRWF / SDMA"
                          className="w-full bg-[#FAF9F5] border border-[rgba(26,23,18,0.15)] rounded-md pl-8 pr-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                        />
                      </div>
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-text-secondary mb-1">
                      Applicant Email (Verified)
                    </label>
                    <div className="relative">
                      <Mail className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-text-muted" />
                      <input
                        type="email"
                        disabled
                        value={email}
                        className="w-full bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-md pl-8 pr-2.5 py-1.5 text-xs text-text-muted font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-text-secondary mb-1">
                      Operational Justification / Role Details
                    </label>
                    <textarea
                      rows={2}
                      value={reqReason}
                      onChange={(e) => setReqReason(e.target.value)}
                      placeholder="Brief note on your operational forecasting responsibilities..."
                      className="w-full bg-[#FAF9F5] border border-[rgba(26,23,18,0.15)] rounded-md p-2 text-xs text-text-primary focus:outline-none focus:border-accent resize-none"
                    />
                  </div>

                  <div className="flex gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setAccessStage("enter_email")}
                      className="w-1/3 text-xs"
                    >
                      Back
                    </Button>
                    <Button
                      type="submit"
                      disabled={submittingReq || !reqName.trim()}
                      size="sm"
                      className="flex-1 bg-accent text-surface-dark hover:bg-accent/90 text-xs font-medium"
                    >
                      {submittingReq ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                      ) : (
                        <UserCheck className="w-3.5 h-3.5 mr-1.5" />
                      )}
                      <span>Submit Forecaster Request</span>
                    </Button>
                  </div>
                </form>
              )}

              {/* Case B Confirmation: Request Submitted */}
              {accessStage === "submitted" && (
                <div className="p-4 bg-emerald-50 rounded-lg border border-emerald-200 text-xs text-emerald-900 space-y-3 text-center">
                  <CheckCircle2 className="w-8 h-8 text-emerald-600 mx-auto" />
                  <div>
                    <h4 className="font-bold text-sm text-emerald-950">Access Request Submitted</h4>
                    <p className="text-[11px] text-emerald-800 mt-1 max-w-md mx-auto leading-relaxed">
                      Your request for <strong className="font-mono">{email}</strong> has been recorded and submitted to an AAGAM Forecaster Coordinator. You remain in public read-only access until an administrator reviews and approves your account.
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setAccessStage("enter_email");
                      setEmail("");
                      setReqName("");
                      setReqOrg("");
                      setReqReason("");
                    }}
                    className="text-xs bg-white"
                  >
                    Check Another Email
                  </Button>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-xs">
            <div className="p-3 bg-[#F0EDE7] rounded-lg border border-[rgba(26,23,18,0.10)] space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-text-muted text-[11px] block">Operator:</span>
                  <span className="font-semibold text-text-primary">
                    {profile?.display_name || user?.user_metadata?.display_name || user?.email || "Authorized User"}
                  </span>
                </div>
                <div>
                  <span className="text-text-muted text-[11px] block">Role:</span>
                  <span className="text-text-secondary font-medium">
                    {roleLabels[role] || role}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <span className="text-text-muted text-[11px] block">Institution:</span>
                  <span className="text-text-secondary">
                    {profile?.org || user?.user_metadata?.org || "Meteorological Organization"}
                  </span>
                </div>
                <div>
                  <span className="text-text-muted text-[11px] block">Email:</span>
                  <span className="text-text-secondary font-mono">{user?.email || "—"}</span>
                </div>
              </div>
            </div>

            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={() => signOut()}>
                Sign Out
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Coordinator Promotion Panel (Part 16) */}
      {role === "coordinator" && (
        <Card className="p-4">
          <CardHeader className="pb-2 mb-2">
            <div>
              <CardTitle>
                <Award className="w-4 h-4 text-brand-orange" />
                <span>Forecaster Coordinator Promotion Panel</span>
              </CardTitle>
              <CardDescription>
                Designate existing verified Forecasters to act as Forecaster Coordinators (Coordinator privilege)
              </CardDescription>
            </div>
          </CardHeader>

          {loadingForecasters ? (
            <div className="py-6 text-center text-xs text-text-muted">
              <Loader2 className="w-4 h-4 animate-spin mx-auto mb-1.5" />
              Loading verified forecasters…
            </div>
          ) : forecasters.length === 0 ? (
            <div className="py-6 text-center text-xs text-text-muted">
              No registered forecasters found in directory.
            </div>
          ) : (
            <div className="space-y-2">
              <div className="text-xs text-text-muted px-1">
                Verified Directory ({forecasters.length} accounts):
              </div>
              <div className="divide-y divide-[rgba(26,23,18,0.06)] border border-[rgba(26,23,18,0.08)] rounded-lg overflow-hidden bg-white">
                {forecasters.map((f) => {
                  const isCurrentCoordinator = f.role === "coordinator";
                  const isSelf = f.id === user?.id;
                  return (
                    <div
                      key={f.id}
                      className="p-3 flex items-center justify-between gap-3 text-xs"
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
                        <div className="text-[11px] text-text-muted">
                          {f.email} · {f.org || "No org"}
                        </div>
                      </div>

                      <div>
                        {isCurrentCoordinator ? (
                          <span className="text-[11px] text-text-muted italic">Coordinator</span>
                        ) : isSelf ? (
                          <span className="text-[11px] text-text-muted">Self</span>
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
            </div>
          )}
        </Card>
      )}

      {/* System Settings & Timezone */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Clock className="w-4 h-4 text-emerald-600" />
              <span>Timezone & Accumulation Standards</span>
            </CardTitle>
            <CardDescription>
              Authoritative meteorological conventions implemented in AAGAM
            </CardDescription>
          </div>
        </CardHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          <div className="p-3 bg-[#F0EDE7] rounded border border-[rgba(26,23,18,0.10)] space-y-1">
            <span className="font-semibold text-text-primary block">Display Timezone</span>
            <span className="font-mono text-brand-blue font-bold text-sm block">
              Asia/Kolkata (IST · UTC+05:30)
            </span>
            <p className="text-[11px] text-text-muted">
              All dates and timestamps rendered in the dashboard reflect Indian Standard Time.
            </p>
          </div>

          <div className="p-3 bg-[#F0EDE7] rounded border border-[rgba(26,23,18,0.10)] space-y-1">
            <span className="font-semibold text-text-primary block">Rainfall Accumulation Window</span>
            <span className="font-mono text-emerald-700 font-bold text-sm block">
              08:30 IST to 08:30 IST (24 Hours)
            </span>
            <p className="text-[11px] text-text-muted">
              Matches standard IMD synoptic rain-gauge observational windows (03:00 UTC to 03:00 UTC).
            </p>
          </div>
        </div>
      </Card>

      {/* Statutory Attribution & Compliance */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Database className="w-4 h-4 text-purple-600" />
              <span>Data Attribution & Licensing Notice</span>
            </CardTitle>
            <CardDescription>
              Compliance with open scientific datasets and MoES / IMD terms of use
            </CardDescription>
          </div>
        </CardHeader>

        <div className="space-y-3 text-xs text-text-secondary leading-relaxed">
          <div className="p-3 bg-[#F0EDE7] rounded border border-[rgba(26,23,18,0.10)]">
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

          <div className="p-3 bg-[#F0EDE7] rounded border border-[rgba(26,23,18,0.10)]">
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

          <div className="p-3 bg-amber-950/10 rounded border border-amber-800/20 text-amber-900 text-[11px]">
            <strong>Important Operational Notice:</strong> AAGAM is an automated AI-Grid
            assimilation and multi-model post-processing decision support tool developed for MoES / NCMRWF.
            Guidance produced is for operational situational awareness and does not supersede statutory public weather warnings.
          </div>
        </div>
      </Card>
    </div>
  );
};
