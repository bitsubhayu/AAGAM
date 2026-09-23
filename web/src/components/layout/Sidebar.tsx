import React from "react";
import {
  LayoutDashboard,
  TrendingUp,
  Sliders,
  AlertTriangle,
  Activity,
  Bot,
  Download,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
  Server,
} from "lucide-react";
import { useUIStore } from "@/store/uiStore";
import { useAuthStore } from "@/auth/authStore";

interface NavItem {
  id: string;
  label: string;
  icon: React.ElementType;
  badge?: string;
  requiresRole?: "forecaster" | "coordinator";
}

export const Sidebar: React.FC = () => {
  const { activeTab, setActiveTab, sidebarCollapsed, toggleSidebar } = useUIStore();
  const { role } = useAuthStore();

  const isForecasterOrCoordinator = role === "forecaster" || role === "coordinator";

  const allNavItems: NavItem[] = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "forecast", label: "Forecast Explorer", icon: TrendingUp },
    { id: "weights", label: "Weight Maps", icon: Sliders },
    { id: "skill", label: "Skill & Verification", icon: Activity },
    { id: "alerts", label: "Extreme Weather", icon: AlertTriangle, badge: "Active" },
    { id: "assistant", label: "AAGAM Assistant", icon: Bot, badge: "AI" },
    {
      id: "pipeline",
      label: "Pipeline Health",
      icon: Server,
      requiresRole: "forecaster",
    },
    { id: "export", label: "Data & Export", icon: Download },
    { id: "settings", label: "Settings", icon: Settings },
  ];

  // Part 14: Filter navigation items based on current authoritative role
  const navItems = allNavItems.filter((item) => {
    if (item.requiresRole && !isForecasterOrCoordinator) {
      return false;
    }
    return true;
  });

  const getRoleLabel = () => {
    switch (role) {
      case "coordinator":
        return "Forecaster Coordinator";
      case "forecaster":
        return "Forecaster";
      default:
        return "Public";
    }
  };

  return (
    <aside
      className={`border-r border-[rgba(26,23,18,0.09)] bg-surface flex flex-col justify-between transition-all duration-200 ease-out-smooth select-none ${
        sidebarCollapsed ? "w-14" : "w-56"
      }`}
    >
      <div className="py-3">
        {/* Navigation Items */}
        <nav className="space-y-0.5 px-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                data-tab={item.id}
                onClick={() => setActiveTab(item.id)}
                title={sidebarCollapsed ? item.label : undefined}
                className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-[12px] text-xs font-medium transition-all duration-150 ${
                  isActive
                    ? "bg-accent text-white shadow-pill font-semibold"
                    : "text-text-secondary hover:text-text-primary hover:bg-[#F0EDE7]"
                }`}
              >
                <Icon
                  className={`w-4 h-4 shrink-0 ${
                    isActive ? "text-white" : "text-text-muted"
                  }`}
                />
                {!sidebarCollapsed && (
                  <span className="flex-1 text-left truncate">{item.label}</span>
                )}
                {!sidebarCollapsed && item.badge && (
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded-full font-semibold ${
                      isActive
                        ? "bg-white/20 text-white"
                        : "bg-accent-soft text-accent border border-accent/20"
                    }`}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Footer (Part 15) */}
      <div className="p-2 border-t border-[rgba(26,23,18,0.09)] space-y-2">
        {!sidebarCollapsed && (
          <div className="p-2.5 bg-[#F0EDE7] rounded-[12px] text-[10px] text-text-muted space-y-1">
            <div className="flex items-center gap-1.5 font-semibold text-text-secondary">
              <Shield
                className={`w-3 h-3 ${
                  role === "coordinator"
                    ? "text-accent"
                    : role === "forecaster"
                    ? "text-brand-blue"
                    : "text-text-muted"
                }`}
              />
              <span className="truncate">Role: {getRoleLabel()}</span>
            </div>
            <p className="line-clamp-2 leading-relaxed">
              Decision-support system for MoES / NCMRWF. Not an official warning.
            </p>
          </div>
        )}

        <button
          onClick={toggleSidebar}
          className="w-full flex items-center justify-center p-1.5 rounded-[10px] text-text-muted hover:text-text-primary hover:bg-[#F0EDE7] transition-colors duration-150"
          title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {sidebarCollapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <div className="flex items-center gap-2 text-xs">
              <ChevronLeft className="w-4 h-4" />
              <span>Collapse</span>
            </div>
          )}
        </button>
      </div>
    </aside>
  );
};
