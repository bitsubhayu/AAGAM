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
        const metaRole =
          (session.user.app_metadata?.role as UserRole) ||
          (session.user.user_metadata?.role as UserRole);
        const resolvedRole: UserRole =
          profile?.role ||
          (metaRole === "coordinator" || metaRole === "forecaster" ? metaRole : "public");

        set({
          session,
          user: session.user,
          role: resolvedRole,
          profile,
          token: session.access_token,
          isLoading: false,
        });
      } else {
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

  // 1. Initial real session resolution
  supabase.auth.getSession().then(({ data: { session } }) => {
    useAuthStore.getState().setSession(session);
  });

  // 2. Real-time auth subscription
  supabase.auth.onAuthStateChange(async (_event, session) => {
    await useAuthStore.getState().setSession(session);
  });
}

// Auto-start listener in browser environment
if (typeof window !== "undefined") {
  initializeAuthSync();
}
