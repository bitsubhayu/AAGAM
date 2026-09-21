import React from "react";
import {
  LayoutDashboard,
  TrendingUp,
  MapPin,
  Sliders,
  AlertTriangle,
  Activity,
  Download,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
} from "lucide-react";
import { useUIStore } from "@/store/uiStore";
import { useAuthStore } from "@/auth/authStore";

interface NavItem {
  id: string;
  label: string;
  icon: React.ElementType;
  badge?: string;
}

export const Sidebar: React.FC = () => {
  const { activeTab, setActiveTab, sidebarCollapsed, toggleSidebar } = useUIStore();
  const { role } = useAuthStore();

  const navItems: NavItem[] = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "forecast", label: "Forecast Explorer", icon: TrendingUp },
    { id: "weights", label: "Weight Maps", icon: Sliders },
    { id: "skill", label: "Skill & Verification", icon: Activity },
    { id: "alerts", label: "Extreme Weather", icon: AlertTriangle, badge: "Active" },
    { id: "pipeline", label: "Pipeline Health", icon: MapPin },
    { id: "export", label: "Data & Export", icon: Download },
    { id: "settings", label: "Settings", icon: Settings },
  ];

  return (
    <aside
      className={`border-r border-border bg-[#161b22] flex flex-col justify-between transition-all duration-200 select-none ${
        sidebarCollapsed ? "w-14" : "w-56"
      }`}
    >
      <div className="py-3">
        {/* Navigation Items */}
        <nav className="space-y-1 px-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                title={sidebarCollapsed ? item.label : undefined}
                className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-md text-xs font-medium transition-colors ${
                  isActive
                    ? "bg-brand-blue/15 text-brand-blue border border-brand-blue/30 font-semibold"
                    : "text-text-secondary hover:text-text-primary hover:bg-[#21262d]"
                }`}
              >
                <Icon
                  className={`w-4 h-4 shrink-0 ${
                    isActive ? "text-brand-blue" : "text-text-muted"
                  }`}
                />
                {!sidebarCollapsed && (
                  <span className="flex-1 text-left truncate">{item.label}</span>
                )}
                {!sidebarCollapsed && item.badge && (
                  <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-950/60 text-hazard-advisory border border-amber-800/40">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Footer: Toggle & Attribution */}
      <div className="p-2 border-t border-border/70 space-y-2">
        {!sidebarCollapsed && (
          <div className="p-2 bg-[#21262d] rounded text-[10px] text-text-muted space-y-1">
            <div className="flex items-center gap-1 font-semibold text-text-secondary">
              <Shield className="w-3 h-3 text-brand-blue" />
              <span>Role: {role.toUpperCase()}</span>
            </div>
            <p className="line-clamp-2">
              Decision-support system for MoES / NCMRWF. Not an official warning.
            </p>
          </div>
        )}

        <button
          onClick={toggleSidebar}
          className="w-full flex items-center justify-center p-1.5 rounded text-text-muted hover:text-text-primary hover:bg-[#21262d] transition-colors"
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
