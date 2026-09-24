import type { ErrorEnvelope } from "./types";

export class ApiError extends Error {
  code: string;
  status: number;
  retryAfter?: number | null;

  constructor(status: number, code: string, message: string, retryAfter?: number | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

export const API_BASE = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : "/api/v1";

export const HEALTH_URL = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/health`
  : "/health";

/**
 * Retrieves the currently active JWT token (either from Supabase session or demo role switcher).
 */
export function getAuthToken(): string | null {
  const local = localStorage.getItem("aagam_auth_token");
  if (local) return local;

  // Fallback: check Supabase session stored in localStorage
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key.includes("supabase.auth.token") || (key.startsWith("sb-") && key.endsWith("-auth-token")))) {
        const item = JSON.parse(localStorage.getItem(key) || "{}");
        if (item?.access_token) return item.access_token;
      }
    }
  } catch {
    // Ignore storage parse errors
  }
  return null;
}

export async function apiFetch<T>(
  endpoint: string,
  options: RequestInit & { timeoutMs?: number } = {}
): Promise<T> {
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});

  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const url = endpoint.startsWith("http")
    ? endpoint
    : `${API_BASE}${endpoint.startsWith("/") ? "" : "/"}${endpoint}`;

  const timeoutMs = options.timeoutMs ?? 20000;
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort(new Error("Request timed out"));
  }, timeoutMs);

  if (options.signal) {
    options.signal.addEventListener("abort", () => controller.abort(options.signal?.reason));
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      let errorCode = "UNKNOWN_ERROR";
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      let retryAfter: number | null = null;

      const retryHeader = response.headers.get("Retry-After");
      if (retryHeader) {
        retryAfter = parseInt(retryHeader, 10) || null;
      }

      try {
        const errorJson: ErrorEnvelope = await response.json();
        if (errorJson?.error) {
          errorCode = errorJson.error.code || errorCode;
          errorMessage = errorJson.error.message || errorMessage;
          if (errorJson.error.retry_after !== undefined) {
            retryAfter = errorJson.error.retry_after;
          }
        }
      } catch {
        // Non-JSON response
      }

      throw new ApiError(response.status, errorCode, errorMessage, retryAfter);
    }

    // If response has no content
    if (response.status === 204) {
      return {} as T;
    }

    return (await response.json()) as T;
  } catch (err: any) {
    if (err instanceof ApiError) {
      throw err;
    }
    if (controller.signal.aborted || err?.name === "AbortError" || err?.name === "TimeoutError") {
      const isSub = endpoint.includes("/subscriptions");
      const msg = isSub
        ? "Saving preferences timed out. Please try again."
        : `Request to ${endpoint} timed out after ${Math.round(timeoutMs / 1000)}s. Please try again.`;
      throw new ApiError(
        408,
        "REQUEST_TIMEOUT",
        msg
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

import type {
  Subscription,
  SubscriptionUpdate,
  OtpVerifyResponse,
  UnsubscribeResponse,
  CheckAccessResponse,
  ForecasterAccessRequestItem,
  AlertCancelResponse,
  AlertEventCancelResponse,
} from "./types";

export async function requestOtp(email: string): Promise<{ status: string; message: string }> {
  return apiFetch<{ status: string; message: string }>("/auth/otp/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function verifyOtp(email: string, token: string): Promise<OtpVerifyResponse> {
  const cleanToken = token.trim();
  if (!/^\d{6}$/.test(cleanToken)) {
    throw new ApiError(400, "INVALID_OTP_FORMAT", "Verification code must be exactly 6 numeric digits.");
  }
  const resp = await apiFetch<OtpVerifyResponse>("/auth/otp/verify", {
    method: "POST",
    body: JSON.stringify({ email: email.trim(), token: cleanToken }),
  });
  if (resp.access_token) {
    localStorage.setItem("aagam_auth_token", resp.access_token);
    if (resp.user?.email) {
      localStorage.setItem("aagam_user_email", resp.user.email);
    }
  }
  return resp;
}

export async function fetchMySubscription(): Promise<Subscription> {
  return apiFetch<Subscription>("/subscriptions/me", { timeoutMs: 10000 });
}

export async function updateMySubscription(payload: SubscriptionUpdate): Promise<Subscription> {
  return apiFetch<Subscription>("/subscriptions/me", {
    method: "PUT",
    body: JSON.stringify(payload),
    timeoutMs: 10000,
  });
}

export async function unsubscribeMySubscription(): Promise<UnsubscribeResponse> {
  return apiFetch<UnsubscribeResponse>("/subscriptions/me", {
    method: "DELETE",
  });
}

export async function requestForecasterOtp(
  name: string,
  institution: string,
  email: string
): Promise<{ status: string; message: string }> {
  return apiFetch<{ status: string; message: string }>("/auth/forecaster/otp/request", {
    method: "POST",
    body: JSON.stringify({ name, institution, email }),
  });
}

export async function verifyForecasterOtp(
  email: string,
  token: string
): Promise<OtpVerifyResponse> {
  const cleanToken = token.trim();
  if (!/^\d{6}$/.test(cleanToken)) {
    throw new ApiError(400, "INVALID_OTP_FORMAT", "Verification code must be exactly 6 numeric digits.");
  }
  const resp = await apiFetch<OtpVerifyResponse>("/auth/forecaster/otp/verify", {
    method: "POST",
    body: JSON.stringify({ email: email.trim(), token: cleanToken }),
  });
  if (resp.access_token) {
    localStorage.setItem("aagam_auth_token", resp.access_token);
    if (resp.user?.email) {
      localStorage.setItem("aagam_user_email", resp.user.email);
    }
  }
  return resp;
}

export interface ForecasterItem {
  id: string;
  email?: string;
  name?: string;
  display_name?: string;
  org?: string;
  role: string;
}

export async function fetchForecasters(): Promise<ForecasterItem[]> {
  const resp = await apiFetch<any>("/auth/forecasters");
  const list = Array.isArray(resp) ? resp : resp?.forecasters || [];
  return list.map((item: any) => ({
    id: item.id,
    email: item.email,
    name: item.name || item.display_name || item.email || "Forecaster",
    display_name: item.display_name,
    org: item.org,
    role: item.role,
  }));
}

export async function promoteCoordinator(
  userId: string
): Promise<{ status: string; message: string; user_id: string; role: string }> {
  return apiFetch<{ status: string; message: string; user_id: string; role: string }>(
    `/auth/forecasters/${userId}/promote-coordinator`,
    {
      method: "POST",
    }
  );
}

export async function checkForecasterAccess(email: string): Promise<CheckAccessResponse> {
  return apiFetch<CheckAccessResponse>("/auth/forecaster/check-access", {
    method: "POST",
    body: JSON.stringify({ email: email.trim().toLowerCase() }),
  });
}

export async function requestForecasterAccess(
  name: string,
  email: string,
  institution?: string,
  reason?: string
): Promise<{ status: string; message: string; request_id: string }> {
  return apiFetch<{ status: string; message: string; request_id: string }>(
    "/auth/forecaster/request-access",
    {
      method: "POST",
      body: JSON.stringify({
        name: name.trim(),
        email: email.trim().toLowerCase(),
        institution: institution?.trim() || null,
        reason: reason?.trim() || null,
      }),
    }
  );
}

export async function fetchForecasterRequests(
  status?: string
): Promise<ForecasterAccessRequestItem[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const resp = await apiFetch<{ requests: ForecasterAccessRequestItem[] }>(
    `/auth/forecaster/requests${qs}`
  );
  return resp.requests || [];
}

export async function approveForecasterRequest(
  requestId: string
): Promise<{ status: string; message: string; role: string; user_id?: string }> {
  return apiFetch<{ status: string; message: string; role: string; user_id?: string }>(
    `/auth/forecaster/requests/${requestId}/approve`,
    {
      method: "POST",
    }
  );
}

export async function rejectForecasterRequest(
  requestId: string
): Promise<{ status: string; message: string }> {
  return apiFetch<{ status: string; message: string }>(
    `/auth/forecaster/requests/${requestId}/reject`,
    {
      method: "POST",
    }
  );
}

export async function cancelAlert(alertId: number): Promise<AlertCancelResponse> {
  return apiFetch<AlertCancelResponse>(`/alerts/${alertId}/cancel`, {
    method: "POST",
  });
}

export async function cancelAlertEvent(eventId: number): Promise<AlertEventCancelResponse> {
  return apiFetch<AlertEventCancelResponse>(`/alerts/events/${eventId}/cancel`, {
    method: "POST",
  });
}


