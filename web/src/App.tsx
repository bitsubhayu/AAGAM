import { useState, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { useUIStore } from "@/store/uiStore";
import { useHealth } from "@/api/useHealth";
import { TopHeader } from "@/components/layout/TopHeader";
import { Sidebar } from "@/components/layout/Sidebar";
import { FreshnessBanner } from "@/components/layout/FreshnessBanner";
import { WakingUpBanner } from "@/components/layout/WakingUpBanner";
import { AssistantDrawer } from "@/components/assistant/AssistantDrawer";

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

  useEffect(() => {
    if (!healthLoading) return;
    const timer = setInterval(() => {
      setSecondsElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [healthLoading]);

  const isWakingUp = healthLoading && secondsElapsed >= 4;

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
    <div className="min-h-screen bg-background text-text-primary flex flex-col font-sans select-text">
      {/* Top Navigation & Status */}
      <TopHeader />

      {/* Freshness & Cold Start Banners */}
      <FreshnessBanner />
      <WakingUpBanner isWakingUp={isWakingUp} secondsElapsed={secondsElapsed} />

      {/* Workstation Body */}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar />

        {/* Main Viewport Container */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 bg-[#0d1117]">
          <div className="max-w-7xl mx-auto">{renderActiveTab()}</div>
        </main>
      </div>

      {/* Slide-out Assistant Drawer */}
      <AssistantDrawer />

      {/* Rich Sonner Notifications */}
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#161b22",
            border: "1px solid #30363d",
            color: "#c9d1d9",
            fontFamily: "'IBM Plex Sans', sans-serif",
            fontSize: "12px",
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
