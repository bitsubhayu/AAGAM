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
} from "lucide-react";
import { useAuthStore } from "@/auth/authStore";
import { supabase } from "@/auth/supabase";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  requestForecasterOtp,
  verifyForecasterOtp,
  fetchForecasters,
  promoteCoordinator,
  type ForecasterItem,
} from "@/api/client";
import { toast } from "sonner";

export const SettingsPage: React.FC = () => {
  const { role, user, profile, signOut, setSession } = useAuthStore();

  // Forecaster registration form state
  const [name, setName] = useState("");
  const [institution, setInstitution] = useState("");
  const [email, setEmail] = useState("");
  const [otpToken, setOtpToken] = useState("");
  const [otpSent, setOtpSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

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

  const handleRequestOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !institution.trim() || !email.trim()) {
      toast.error("Please fill in your name, institution, and email.");
      return;
    }
    try {
      setSubmitting(true);
      await requestForecasterOtp(name.trim(), institution.trim(), email.trim());
      setOtpSent(true);
      toast.success("Verification code sent to your email!");
    } catch (err: any) {
      toast.error(err.message || "Failed to request forecaster OTP");
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    const token = otpToken.trim();
    if (!token) {
      toast.error("Please enter the 6-digit verification code.");
      return;
    }
    if (!/^\d+$/.test(token)) {
      toast.error("Verification code must contain digits only.");
      return;
    }
    if (token.length !== 6) {
      toast.error("Verification code must be exactly 6 digits.");
      return;
    }
    try {
      setSubmitting(true);
      const resp = await verifyForecasterOtp(email.trim(), token);
      toast.success("Forecaster registration verified!");
      if (resp.access_token && resp.refresh_token) {
        const { data } = await supabase.auth.setSession({
          access_token: resp.access_token,
          refresh_token: resp.refresh_token,
        });
        if (data?.session) {
          setSession(data.session);
        }
      }
      setOtpSent(false);
      setOtpToken("");
    } catch (err: any) {
      toast.error(err.message || "Invalid or expired verification code");
    } finally {
      setSubmitting(false);
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
                You are currently browsing with the Public role. You have read access to all public forecasts,
                risk maps, skill evaluations, and alerts. To perform operational duties (weight overrides,
                alert acknowledgements, forecaster dashboard), register as an authorized Forecaster below.
              </p>
            </div>

            {/* Forecaster Registration Form */}
            <div className="p-4 bg-white border border-[rgba(26,23,18,0.12)] rounded-lg space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
                <UserCheck className="w-4 h-4 text-accent" />
                <span>Forecaster Registration & OTP Verification</span>
              </div>

              {!otpSent ? (
                <form onSubmit={handleRequestOtp} className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    <div>
                      <label className="block text-[11px] font-medium text-text-secondary mb-1">
                        Full Name
                      </label>
                      <div className="relative">
                        <User className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-text-muted" />
                        <input
                          type="text"
                          required
                          value={name}
                          onChange={(e) => setName(e.target.value)}
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
                          required
                          value={institution}
                          onChange={(e) => setInstitution(e.target.value)}
                          placeholder="IMD / NCMRWF / SDMA"
                          className="w-full bg-[#FAF9F5] border border-[rgba(26,23,18,0.15)] rounded-md pl-8 pr-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                        />
                      </div>
                    </div>
                  </div>
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
                        placeholder="forecaster@imd.gov.in"
                        className="w-full bg-[#FAF9F5] border border-[rgba(26,23,18,0.15)] rounded-md pl-8 pr-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                      />
                    </div>
                  </div>
                  <Button
                    type="submit"
                    disabled={submitting}
                    className="w-full bg-accent text-surface-dark hover:bg-accent/90 text-xs font-medium"
                  >
                    {submitting ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                    ) : (
                      <KeyRound className="w-3.5 h-3.5 mr-1.5" />
                    )}
                    <span>Request Verification OTP</span>
                  </Button>
                </form>
              ) : (
                <form onSubmit={handleVerifyOtp} className="space-y-3">
                  <div className="p-2.5 bg-[#F0EDE7] rounded border border-[rgba(26,23,18,0.10)] text-xs text-text-secondary">
                    Verification code dispatched to <span className="font-semibold text-text-primary">{email}</span>.
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
                        if (val && !/^\d+$/.test(val)) {
                          toast.error("Verification code must contain digits only.");
                          return;
                        }
                        if (val.length > 6) {
                          toast.error("Verification code must be exactly 6 digits.");
                          return;
                        }
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
                      onClick={() => setOtpSent(false)}
                      className="w-1/3 text-xs"
                    >
                      Back
                    </Button>
                    <Button
                      type="submit"
                      disabled={submitting}
                      size="sm"
                      className="flex-1 bg-accent text-surface-dark hover:bg-accent/90 text-xs font-medium"
                    >
                      {submitting ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
                      ) : (
                        <Shield className="w-3.5 h-3.5 mr-1.5" />
                      )}
                      <span>Verify & Claim Forecaster Role</span>
                    </Button>
                  </div>
                </form>
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
