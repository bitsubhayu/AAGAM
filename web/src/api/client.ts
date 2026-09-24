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
  return localStorage.getItem("aagam_auth_token");
}

export async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
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

  const response = await fetch(url, {
    ...options,
    headers,
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
}

import type {
  Subscription,
  SubscriptionUpdate,
  OtpVerifyResponse,
  UnsubscribeResponse,
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
  return apiFetch<Subscription>("/subscriptions/me");
}

export async function updateMySubscription(payload: SubscriptionUpdate): Promise<Subscription> {
  return apiFetch<Subscription>("/subscriptions/me", {
    method: "PUT",
    body: JSON.stringify(payload),
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
  org?: string;
  role: string;
}

export async function fetchForecasters(): Promise<ForecasterItem[]> {
  const resp = await apiFetch<{ forecasters: ForecasterItem[] }>("/auth/forecasters");
  return resp.forecasters || [];
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

