import { create } from "zustand";

export type WeatherVariable = "rain_mm" | "tmax_c" | "wind_max_kmh";

export interface VariableMeta {
  id: WeatherVariable;
  label: string;
  unit: string;
  shortUnit: string;
  thresholdName: string;
}

export const VARIABLES: Record<WeatherVariable, VariableMeta> = {
  rain_mm: {
    id: "rain_mm",
    label: "24h Accumulated Rainfall",
    unit: "mm/24h (08:30 IST)",
    shortUnit: "mm",
    thresholdName: "Heavy Rain (≥ 64.5 mm)",
  },
  tmax_c: {
    id: "tmax_c",
    label: "Maximum Temperature",
    unit: "°C (Maximum Temperature)",
    shortUnit: "°C",
    thresholdName: "Heatwave (≥ 40°C)",
  },
  wind_max_kmh: {
    id: "wind_max_kmh",
    label: "Peak Wind Gust / Speed",
    unit: "km/h (Peak Gust)",
    shortUnit: "km/h",
    thresholdName: "Gale Wind (≥ 62 km/h)",
  },
};

interface UIState {
  selectedVariable: WeatherVariable;
  selectedLeadDays: number;
  selectedLocationSlug: string;
  selectedRegion: string;
  selectedSeason: string;
  activeTab: string;
  isAssistantOpen: boolean;
  assistantPrompt: string | null;
  sidebarCollapsed: boolean;

  setSelectedVariable: (v: WeatherVariable) => void;
  setSelectedLeadDays: (lead: number) => void;
  setSelectedLocationSlug: (slug: string) => void;
  setSelectedRegion: (r: string) => void;
  setSelectedSeason: (s: string) => void;
  setActiveTab: (tab: string) => void;
  setAssistantOpen: (open: boolean) => void;
  openAssistantWithPrompt: (prompt: string) => void;
  toggleSidebar: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  selectedVariable: "rain_mm",
  selectedLeadDays: 1,
  selectedLocationSlug: "bhubaneswar",
  selectedRegion: "ALL",
  selectedSeason: "monsoon",
  activeTab: "overview",
  isAssistantOpen: false,
  assistantPrompt: null,
  sidebarCollapsed: false,

  setSelectedVariable: (selectedVariable) => set({ selectedVariable }),
  setSelectedLeadDays: (selectedLeadDays) => set({ selectedLeadDays }),
  setSelectedLocationSlug: (selectedLocationSlug) => set({ selectedLocationSlug }),
  setSelectedRegion: (selectedRegion) => set({ selectedRegion }),
  setSelectedSeason: (selectedSeason) => set({ selectedSeason }),
  setActiveTab: (activeTab) => set({ activeTab }),
  setAssistantOpen: (isAssistantOpen) => set({ isAssistantOpen }),
  openAssistantWithPrompt: (assistantPrompt) =>
    set({ isAssistantOpen: true, assistantPrompt }),
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
