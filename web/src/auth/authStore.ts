import { create } from "zustand";
import { supabase } from "./supabase";
import type { Session, User } from "@supabase/supabase-js";

export type UserRole = "public" | "forecaster" | "coordinator";

export interface UserProfile {
  id: string;
  email: string;
  role: UserRole;
  display_name?: string | null;
  org?: string | null;
}

interface AuthState {
  user: User | null;
  session: Session | null;
  role: UserRole;
  profile: UserProfile | null;
  token: string | null;
  isLoading: boolean;
  setSession: (session: Session | null) => Promise<void>;
  signOut: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

async function fetchAuthoritativeProfile(userId: string): Promise<UserProfile | null> {
  try {
    const { data, error } = await supabase
      .from("profiles")
      .select("user_id, role, display_name, org")
      .eq("user_id", userId)
      .maybeSingle();

    if (error || !data) {
      return null;
    }

    const roleStr = String(data.role || "").toLowerCase();
    const validRole: UserRole =
      roleStr === "coordinator" || roleStr === "forecaster" ? roleStr : "public";

    return {
      id: String(data.user_id),
      email: "",
      role: validRole,
      display_name: data.display_name,
      org: data.org,
    };
  } catch (err) {
    console.warn("Failed to fetch authoritative profile:", err);
    return null;
  }
}

export const useAuthStore = create<AuthState>((set, get) => {
  const initialToken = localStorage.getItem("aagam_auth_token");

  return {
    user: null,
    session: null,
    role: "public",
    profile: null,
    token: initialToken,
    isLoading: true,

    setSession: async (session: Session | null) => {
      if (session?.user) {
        localStorage.setItem("aagam_auth_token", session.access_token);
        const profile = await fetchAuthoritativeProfile(session.user.id);
        if (profile && session.user.email) {
          profile.email = session.user.email;
        }
        // Authoritative role from public.profiles only. Never trust JWT user_metadata or app_metadata.
        const resolvedRole: UserRole = profile?.role || "public";

        set({
          session,
          user: session.user,
          role: resolvedRole,
          profile,
          token: session.access_token,
          isLoading: false,
        });
      } else {
        // Check for local demo token before clearing
        const demoToken = localStorage.getItem("aagam_auth_token");
        if (demoToken === "demo-forecaster-token") {
          set({
            session: null,
            user: { id: "00000000-0000-0000-0000-000000000002", email: "forecaster@aagam.gov.in" } as any,
            role: "forecaster",
            profile: {
              id: "00000000-0000-0000-0000-000000000002",
              email: "forecaster@aagam.gov.in",
              role: "forecaster",
              display_name: "Demo Forecaster",
              org: "IMD",
            },
            token: "demo-forecaster-token",
            isLoading: false,
          });
          return;
        } else if (demoToken === "demo-coordinator-token") {
          set({
            session: null,
            user: { id: "00000000-0000-0000-0000-000000000003", email: "coordinator@aagam.gov.in" } as any,
            role: "coordinator",
            profile: {
              id: "00000000-0000-0000-0000-000000000003",
              email: "coordinator@aagam.gov.in",
              role: "coordinator",
              display_name: "Demo Coordinator",
              org: "IMD",
            },
            token: "demo-coordinator-token",
            isLoading: false,
          });
          return;
        }

        localStorage.removeItem("aagam_auth_token");
        set({
          session: null,
          user: null,
          role: "public",
          profile: null,
          token: null,
          isLoading: false,
        });
      }
    },

    refreshProfile: async () => {
      const user = get().user;
      if (!user) return;
      const profile = await fetchAuthoritativeProfile(user.id);
      if (profile) {
        set({ profile, role: profile.role });
      }
    },

    signOut: async () => {
      try {
        await supabase.auth.signOut();
      } catch (err) {
        console.error("Sign out error", err);
      }
      localStorage.removeItem("aagam_auth_token");
      localStorage.removeItem("aagam_user_email");
      set({
        user: null,
        session: null,
        token: null,
        role: "public",
        profile: null,
        isLoading: false,
      });
    },
  };
});

// Singleton session synchronization
let authInitialized = false;

export function initializeAuthSync(): void {
  if (authInitialized) return;
  authInitialized = true;

  // 1. Initial demo token resolution
  const curToken = typeof window !== "undefined" ? localStorage.getItem("aagam_auth_token") : null;
  if (curToken?.startsWith("demo-")) {
    useAuthStore.getState().setSession(null);
    return;
  }

  // 2. Initial real session resolution
  supabase.auth.getSession().then(({ data: { session } }) => {
    const token = localStorage.getItem("aagam_auth_token");
    if (token?.startsWith("demo-")) return;
    useAuthStore.getState().setSession(session);
  });

  // 3. Real-time auth subscription
  supabase.auth.onAuthStateChange(async (_event, session) => {
    const token = localStorage.getItem("aagam_auth_token");
    if (token?.startsWith("demo-")) return;
    await useAuthStore.getState().setSession(session);
  });
}

// Auto-start listener in browser environment
if (typeof window !== "undefined") {
  initializeAuthSync();
}
