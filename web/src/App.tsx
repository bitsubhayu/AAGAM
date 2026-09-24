import { useState, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster, toast } from "sonner";
import { useUIStore } from "@/store/uiStore";
import { useHealth } from "@/api/useHealth";
import { TopHeader } from "@/components/layout/TopHeader";
import { Sidebar } from "@/components/layout/Sidebar";
import { FreshnessBanner } from "@/components/layout/FreshnessBanner";
import { WakingUpBanner } from "@/components/layout/WakingUpBanner";
import { AssistantDrawer } from "@/components/assistant/AssistantDrawer";
import { useAuthStore } from "@/auth/authStore";
import { supabase } from "@/auth/supabase";

// Pages
import { OverviewPage } from "@/pages/OverviewPage";
import { ForecastExplorerPage } from "@/pages/ForecastExplorerPage";
import { WeightMapsPage } from "@/pages/WeightMapsPage";
import { SkillPage } from "@/pages/SkillPage";
import { ExtremeWeatherPage } from "@/pages/ExtremeWeatherPage";
import { AssistantPage } from "@/pages/AssistantPage";
import { PipelineHealthPage } from "@/pages/PipelineHealthPage";
import { DataExportPage } from "@/pages/DataExportPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { PublicEventSharePage } from "@/pages/PublicEventSharePage";

function parsePublicEventId(): number | null {
  if (typeof window === "undefined") return null;
  const path = window.location.pathname;
  const match = path.match(/^\/alerts\/(?:e|events)\/(\d+)\/?$/);
  if (match && match[1]) {
    const parsed = parseInt(match[1], 10);
    return isNaN(parsed) ? null : parsed;
  }
  return null;
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 60 * 1000,
    },
  },
});

function DashboardContent() {
  const { activeTab } = useUIStore();
  const { isLoading: healthLoading } = useHealth();
  const [secondsElapsed, setSecondsElapsed] = useState(0);
  const [publicEventId, setPublicEventId] = useState<number | null>(parsePublicEventId);

  useEffect(() => {
    // Detect and handle Supabase auth hash errors (e.g. #error=access_denied&error_code=otp_expired)
    if (typeof window !== "undefined" && window.location.hash) {
      const hash = window.location.hash.substring(1);
      if (hash.includes("error=")) {
        const hashParams = new URLSearchParams(hash);
        const errorDescription = hashParams.get("error_description");
        const errorCode = hashParams.get("error_code") || hashParams.get("error");
        if (errorCode || errorDescription) {
          const msg = errorDescription
            ? decodeURIComponent(errorDescription.replace(/\+/g, " "))
            : "Sign-in link is invalid or has expired. Please enter the 6-digit OTP code.";
          toast.error(msg);
          window.history.replaceState(null, "", window.location.pathname + window.location.search);
        }
      }
    }

    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        useAuthStore.getState().setSession(session);
      }
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session) {
        useAuthStore.getState().setSession(session);
        if (typeof window !== "undefined" && window.location.hash.includes("access_token=")) {
          window.history.replaceState(null, "", window.location.pathname + window.location.search);
        }
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      setPublicEventId(parsePublicEventId());
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (!healthLoading) return;
    const timer = setInterval(() => {
      setSecondsElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [healthLoading]);

  const isWakingUp = healthLoading && secondsElapsed >= 4;
  const { role } = useAuthStore();

  if (publicEventId !== null) {
    return (
      <PublicEventSharePage
        eventId={publicEventId}
        onNavigateHome={() => {
          window.history.pushState({}, "", "/");
          setPublicEventId(null);
        }}
      />
    );
  }

  const renderActiveTab = () => {
    switch (activeTab) {
      case "overview":
        return <OverviewPage />;
      case "assistant":
        return <AssistantPage />;
      case "forecast":
        return <ForecastExplorerPage />;
      case "weights":
        return <WeightMapsPage />;
      case "skill":
        return <SkillPage />;
      case "alerts":
        return <ExtremeWeatherPage />;
      case "pipeline":
        if (role === "public") {
          return <OverviewPage />;
        }
        return <PipelineHealthPage />;
      case "export":
        return <DataExportPage />;
      case "settings":
        return <SettingsPage />;
      default:
        return <OverviewPage />;
    }
  };

  return (
    <div className="min-h-screen bg-canvas text-text-primary flex flex-col font-sans select-text">
      {/* Top Navigation & Status */}
      <TopHeader />

      {/* Freshness & Cold Start Banners */}
      <FreshnessBanner />
      <WakingUpBanner isWakingUp={isWakingUp} secondsElapsed={secondsElapsed} />

      {/* Workstation Body */}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar />

        {/* Main Viewport Container */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 bg-canvas">
          <div className="max-w-7xl mx-auto">{renderActiveTab()}</div>
        </main>
      </div>

      {/* Slide-out Assistant Drawer */}
      <AssistantDrawer />

      {/* Sonner Notifications — warm light theme */}
      <Toaster
        theme="light"
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#FFFFFF",
            border: "1px solid rgba(26,23,18,0.10)",
            color: "#1A1712",
            fontFamily: "'Instrument Sans', system-ui, sans-serif",
            fontSize: "12px",
            borderRadius: "14px",
            boxShadow: "0 1px 2px rgba(26,23,18,0.04), 0 12px 24px -8px rgba(26,23,18,0.10)",
          },
        }}
      />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <DashboardContent />
    </QueryClientProvider>
  );
}
