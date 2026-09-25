import React, { useState, useEffect, useCallback, useRef } from "react";
import {
  X,
  Bell,
  Mail,
  ShieldCheck,
  CheckCircle2,
  Loader2,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import {
  requestOtp,
  verifyOtp,
  fetchMySubscription,
  updateMySubscription,
  unsubscribeMySubscription,
  getAuthToken,
} from "@/api/client";
import type { Subscription } from "@/api/types";
import { useMeta } from "@/api/useMeta";
import { supabase } from "@/auth/supabase";
import { useAuthStore } from "@/auth/authStore";

interface GetAlertsDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSubscriptionUpdated?: (sub: Subscription | null) => void;
}

export const GetAlertsDialog: React.FC<GetAlertsDialogProps> = ({
  isOpen,
  onClose,
  onSubscriptionUpdated,
}) => {
  const { data: meta } = useMeta();
  const locations = meta?.locations || [];

  const [step, setStep] = useState<"email" | "otp" | "manage">("email");
  const [email, setEmail] = useState<string>(() => {
    try {
      return localStorage.getItem("aagam_user_email") || "";
    } catch {
      return "";
    }
  });
  const [otpToken, setOtpToken] = useState("");

  // Independent mutation states (Part 1B, 1E)
  const [isSendingOtp, setIsSendingOtp] = useState(false);
  const [isVerifyingOtp, setIsVerifyingOtp] = useState(false);
  const [isLoadingSub, setIsLoadingSub] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isUnsubscribing, setIsUnsubscribing] = useState(false);

  // Guard refs to prevent rapid double-clicks and manage abort controllers
  const isSavingRef = useRef(false);
  const isUnsubscribingRef = useRef(false);
  const saveAbortControllerRef = useRef<AbortController | null>(null);
  const unsubAbortControllerRef = useRef<AbortController | null>(null);
  const loadAbortControllerRef = useRef<AbortController | null>(null);

  // Authoritative subscription snapshot from backend
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [selectedLocations, setSelectedLocations] = useState<number[]>([]);
  const [selectedHazards, setSelectedHazards] = useState<string[]>([
    "heavy_rain",
    "heatwave",
    "high_wind",
    "heavy_rain_3day",
  ]);
  const [minSeverity, setMinSeverity] = useState<"advisory" | "watch" | "alert">("watch");
  const [dailySummary, setDailySummary] = useState(true);
  const [lifecycleEmails, setLifecycleEmails] = useState(true);
  const [isActive, setIsActive] = useState(true);

  // Stable callback ref to prevent unnecessary effect triggers
  const onSubscriptionUpdatedRef = React.useRef(onSubscriptionUpdated);
  useEffect(() => {
    onSubscriptionUpdatedRef.current = onSubscriptionUpdated;
  }, [onSubscriptionUpdated]);

  const loadSubscription = useCallback(async () => {
    const controller = new AbortController();
    loadAbortControllerRef.current = controller;
    try {
      setIsLoadingSub(true);
      const sub = await fetchMySubscription({ signal: controller.signal, timeoutMs: 10000 });
      setSubscription(sub);
      if (sub.email) {
        setEmail(sub.email);
        localStorage.setItem("aagam_user_email", sub.email);
      }
      setSelectedLocations(sub.location_ids || []);
      setSelectedHazards(sub.hazards || []);
      setMinSeverity(sub.min_severity || "watch");
      setDailySummary(sub.daily_summary);
      setLifecycleEmails(sub.lifecycle_emails);
      setIsActive(sub.active);
      setStep("manage");
      onSubscriptionUpdatedRef.current?.(sub);
    } catch {
      if (controller.signal.aborted) return;
      setStep("email");
    } finally {
      loadAbortControllerRef.current = null;
      setIsLoadingSub(false);
    }
  }, []);

  const handleCancel = useCallback(() => {
    // 1. Abort any in-flight requests
    if (saveAbortControllerRef.current) {
      saveAbortControllerRef.current.abort();
      saveAbortControllerRef.current = null;
    }
    if (unsubAbortControllerRef.current) {
      unsubAbortControllerRef.current.abort();
      unsubAbortControllerRef.current = null;
    }
    isSavingRef.current = false;
    isUnsubscribingRef.current = false;
    setIsSaving(false);
    setIsUnsubscribing(false);

    // 2. Revert unsaved form changes to the last persisted subscription state
    if (subscription) {
      setSelectedLocations(subscription.location_ids || []);
      setSelectedHazards(subscription.hazards || []);
      setMinSeverity(subscription.min_severity || "watch");
      setDailySummary(subscription.daily_summary);
      setLifecycleEmails(subscription.lifecycle_emails);
      setIsActive(subscription.active);
    }
    // 3. Close dialog
    onClose();
  }, [subscription, onClose]);

  // Escape key and body scroll lock
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleCancel();
    };
    if (isOpen) {
      document.body.style.overflow = "hidden";
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.body.style.overflow = "unset";
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, handleCancel]);

  // Load authoritative subscription when dialog opens
  const wasOpenRef = React.useRef(false);
  useEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      const token = getAuthToken();
      const storeUser = useAuthStore.getState().user;
      const savedEmail = localStorage.getItem("aagam_user_email") || storeUser?.email;

      if (token) {
        if (savedEmail) {
          setEmail(savedEmail);
        }
        loadSubscription();
      } else {
        setStep("email");
      }
    }
    wasOpenRef.current = isOpen;
  }, [isOpen, loadSubscription]);

  // Cleanup abort controllers on unmount
  useEffect(() => {
    return () => {
      saveAbortControllerRef.current?.abort();
      unsubAbortControllerRef.current?.abort();
      loadAbortControllerRef.current?.abort();
    };
  }, []);

  const handleSendOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !email.includes("@")) {
      toast.error("Please provide a valid email address");
      return;
    }

    try {
      setIsSendingOtp(true);
      await requestOtp(email);
      toast.success("Verification code sent! Check your inbox.");
      setStep("otp");
    } catch (err: any) {
      toast.error(err.message || "Failed to send OTP code.");
    } finally {
      setIsSendingOtp(false);
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
      setIsVerifyingOtp(true);
      const resp = await verifyOtp(email.trim(), token);
      toast.success("Authentication successful!");
      localStorage.setItem("aagam_user_email", email);
      if (resp.access_token) {
        localStorage.setItem("aagam_auth_token", resp.access_token);
        if (resp.refresh_token) {
          try {
            const { data } = await supabase.auth.setSession({
              access_token: resp.access_token,
              refresh_token: resp.refresh_token,
            });
            if (data?.session) {
              await useAuthStore.getState().setSession(data.session);
            }
          } catch {
            // non-fatal fallback
          }
        }
      }
      await loadSubscription();
    } catch (err: any) {
      toast.error(err.message || "Invalid or expired verification code.");
    } finally {
      setIsVerifyingOtp(false);
    }
  };

  const handleSavePreferences = async () => {
    // Prevent duplicate submission if already in-flight
    if (isSavingRef.current || isSaving) return;

    isSavingRef.current = true;
    setIsSaving(true);

    const controller = new AbortController();
    saveAbortControllerRef.current = controller;

    try {
      const updated = await updateMySubscription(
        {
          location_ids: selectedLocations,
          hazards: selectedHazards,
          min_severity: minSeverity,
          daily_summary: dailySummary,
          lifecycle_emails: lifecycleEmails,
          active: isActive,
        },
        { signal: controller.signal, timeoutMs: 10000 }
      );

      // Deterministic state update on success:
      // Update local state to reflect persisted backend values immediately
      setSubscription(updated);
      setSelectedLocations(updated.location_ids || []);
      setSelectedHazards(updated.hazards || []);
      setMinSeverity(updated.min_severity || "watch");
      setDailySummary(updated.daily_summary);
      setLifecycleEmails(updated.lifecycle_emails);
      setIsActive(updated.active);

      toast.success("Alert preferences saved successfully!");
      onSubscriptionUpdatedRef.current?.(updated);
    } catch (err: any) {
      if (controller.signal.aborted) return;
      // Retain the user's current form selections so they can retry without losing edits
      toast.error(err.message || "Failed to update alert preferences. Please try again.");
    } finally {
      saveAbortControllerRef.current = null;
      isSavingRef.current = false;
      setIsSaving(false);
    }
  };

  const handleUnsubscribe = async () => {
    if (isUnsubscribingRef.current || isUnsubscribing) return;
    if (!confirm("Are you sure you want to pause all email notifications?")) return;

    isUnsubscribingRef.current = true;
    setIsUnsubscribing(true);

    const controller = new AbortController();
    unsubAbortControllerRef.current = controller;

    try {
      await unsubscribeMySubscription({ signal: controller.signal, timeoutMs: 10000 });
      setIsActive(false);
      if (subscription) {
        const updated = { ...subscription, active: false };
        setSubscription(updated);
        onSubscriptionUpdatedRef.current?.(updated);
      }
      toast.success("Unsubscribed from alert emails.");
    } catch (err: any) {
      if (controller.signal.aborted) return;
      toast.error(err.message || "Failed to unsubscribe.");
    } finally {
      unsubAbortControllerRef.current = null;
      isUnsubscribingRef.current = false;
      setIsUnsubscribing(false);
    }
  };

  const toggleLocation = (id: number) => {
    setSelectedLocations((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const toggleHazard = (h: string) => {
    setSelectedHazards((prev) =>
      prev.includes(h) ? prev.filter((item) => item !== h) : [...prev, h]
    );
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center p-4 bg-[rgba(26,23,18,0.45)] backdrop-blur-sm">
      <div className="relative w-full max-w-lg bg-surface border border-[rgba(26,23,18,0.07)] rounded-card shadow-[0_8px_48px_rgba(26,23,18,0.18)] overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[rgba(26,23,18,0.07)] bg-[#F5F2EC]">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-md bg-[rgba(46,125,107,0.12)] text-[#2E7D6B] border border-[rgba(46,125,107,0.25)]">
              <Bell className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-text-primary">
                {step === "manage" ? "Manage Alert Subscriptions" : "Subscribe to Weather Alerts"}
              </h2>
              <p className="text-xs text-text-muted">
                {step === "manage"
                  ? `Configured for ${email}`
                  : "Receive targeted multi-model email alerts via Brevo"}
              </p>
            </div>
          </div>
          <button
            onClick={handleCancel}
            className="p-1.5 text-text-muted hover:text-text-primary rounded-md hover:bg-[rgba(26,23,18,0.08)] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1">
          {step === "email" && (
            <form onSubmit={handleSendOtp} className="space-y-4">
              <div className="p-3 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-lg text-xs text-text-secondary space-y-1">
                <p className="font-medium text-text-primary flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-accent" />
                  Passwordless Verification
                </p>
                <p>
                  Enter your email address to receive a 6-digit login OTP code. No password required.
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1.5">
                  Email Address
                </label>
                <div className="relative">
                  <Mail className="absolute left-3 top-2.5 w-4 h-4 text-text-muted" />
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="officer@disaster.gov.in"
                    className="w-full bg-white border border-[rgba(26,23,18,0.15)] rounded-lg pl-9 pr-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
                  />
                </div>
              </div>

              <Button type="submit" disabled={isSendingOtp} className="w-full bg-accent text-surface-dark hover:bg-accent/90 font-medium">
                {isSendingOtp ? <Loader2 className="w-4 h-4 animate-spin" /> : "Send 6-Digit Code"}
              </Button>
            </form>
          )}

          {step === "otp" && (
            <form onSubmit={handleVerifyOtp} className="space-y-4">
              <div className="p-3 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-lg text-xs text-text-secondary">
                We sent a 6-digit verification code to <span className="text-text-primary font-medium">{email}</span>.
              </div>

              <div>
                <label className="block text-xs font-medium text-text-secondary mb-1.5">
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
                  className="w-full text-center tracking-widest text-lg font-mono bg-white border border-[rgba(26,23,18,0.15)] rounded-lg px-3 py-2 text-text-primary focus:outline-none focus:border-accent"
                />
              </div>

              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setStep("email")}
                  className="w-1/3"
                >
                  Back
                </Button>
                <Button type="submit" disabled={isVerifyingOtp} className="flex-1 bg-accent text-surface-dark hover:bg-accent/90">
                  {isVerifyingOtp ? <Loader2 className="w-4 h-4 animate-spin" /> : "Verify & Continue"}
                </Button>
              </div>
            </form>
          )}

          {step === "manage" && (
            <div className="space-y-5">
              {/* Delivery Toggles */}
              <div className="p-3 bg-[#F0EDE7] border border-[rgba(26,23,18,0.10)] rounded-lg space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-xs font-medium text-text-primary block">Morning Daily Summary</span>
                    <span className="text-[11px] text-text-muted">07:00 IST digest of all active hazard events</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={dailySummary}
                    onChange={(e) => setDailySummary(e.target.checked)}
                    className="accent-accent w-4 h-4 rounded"
                  />
                </div>

                <div className="flex items-center justify-between border-t border-[rgba(26,23,18,0.07)] pt-2.5">
                  <div>
                    <span className="text-xs font-medium text-text-primary block">Lifecycle Alert Changes</span>
                    <span className="text-[11px] text-text-muted">Immediate emails when threats upgrade or cancel</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={lifecycleEmails}
                    onChange={(e) => setLifecycleEmails(e.target.checked)}
                    className="accent-accent w-4 h-4 rounded"
                  />
                </div>
              </div>

              {/* Minimum Severity Filter */}
              <div>
                <label className="block text-xs font-medium text-text-secondary mb-2">
                  Minimum Alert Severity
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {(["advisory", "watch", "alert"] as const).map((sev) => (
                    <button
                      key={sev}
                      type="button"
                      onClick={() => setMinSeverity(sev)}
                      className={`px-3 py-2 rounded-lg border text-xs capitalize font-medium transition-all ${
                        minSeverity === sev
                          ? "bg-[rgba(46,125,107,0.12)] border-accent text-accent"
                          : "bg-[#F5F2EC] border-[rgba(26,23,18,0.10)] text-text-secondary hover:border-[rgba(26,23,18,0.20)]"
                      }`}
                    >
                      {sev}
                    </button>
                  ))}
                </div>
              </div>

              {/* Hazards Selector */}
              <div>
                <label className="block text-xs font-medium text-text-secondary mb-2">
                  Monitored Hazards
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {[
                    { id: "heavy_rain", label: "Heavy Rain (1-Day)" },
                    { id: "heavy_rain_3day", label: "Persistent Rain (3-Day)" },
                    { id: "heatwave", label: "Heatwave (Tmax)" },
                    { id: "high_wind", label: "Severe Wind Gusts" },
                  ].map((h) => {
                    const checked = selectedHazards.includes(h.id);
                    return (
                      <button
                        key={h.id}
                        type="button"
                        onClick={() => toggleHazard(h.id)}
                        className={`px-2.5 py-2 rounded-lg border text-xs text-left font-medium transition-all flex items-center justify-between ${
                          checked
                            ? "bg-[#F0EDE7] border-accent text-text-primary"
                            : "bg-white border-[rgba(26,23,18,0.10)] text-text-muted"
                        }`}
                      >
                        <span>{h.label}</span>
                        {checked && <CheckCircle2 className="w-3.5 h-3.5 text-accent" />}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Locations Selector */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-text-secondary">
                    Monitored Locations ({selectedLocations.length} selected)
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      setSelectedLocations(
                        selectedLocations.length === locations.length ? [] : locations.map((l, i) => l.id ?? (i + 1))
                      )
                    }
                    className="text-[11px] text-accent hover:underline"
                  >
                    {selectedLocations.length === locations.length ? "Deselect All" : "Select All 40"}
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-1.5 max-h-36 overflow-y-auto p-2 bg-white border border-[rgba(26,23,18,0.10)] rounded-lg">
                  {locations.map((loc, idx) => {
                    const locId = loc.id ?? (idx + 1);
                    const isSelected = selectedLocations.includes(locId);
                    return (
                      <button
                        key={locId}
                        type="button"
                        onClick={() => toggleLocation(locId)}
                        className={`px-2 py-1 rounded text-left text-xs transition-colors flex items-center justify-between ${
                          isSelected
                            ? "bg-[rgba(46,125,107,0.12)] text-accent font-medium"
                            : "text-text-secondary hover:bg-[rgba(26,23,18,0.04)]"
                        }`}
                      >
                        <span className="truncate">{loc.name}</span>
                        {isSelected && <CheckCircle2 className="w-3 h-3 text-accent shrink-0 ml-1" />}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        {step === "manage" && (
          <div className="flex items-center justify-between px-6 py-4 border-t border-[rgba(26,23,18,0.07)] bg-[#F5F2EC]">
            <Button
              variant="outline"
              size="sm"
              onClick={handleUnsubscribe}
              disabled={isUnsubscribing || isSaving || isLoadingSub}
              className="text-red-500 border-red-500/30 hover:bg-red-500/10 text-xs"
            >
              {isUnsubscribing ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" />
                  <span>Unsubscribing...</span>
                </>
              ) : (
                <>
                  <Trash2 className="w-3.5 h-3.5 mr-1" />
                  <span>Unsubscribe</span>
                </>
              )}
            </Button>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={handleCancel}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={handleSavePreferences}
                disabled={isSaving || isLoadingSub}
                className="bg-accent text-surface-dark hover:bg-accent/90 font-medium min-w-[140px] flex items-center justify-center gap-1.5"
              >
                {isSaving ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Saving...</span>
                  </>
                ) : (
                  <span>Save Preferences</span>
                )}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
