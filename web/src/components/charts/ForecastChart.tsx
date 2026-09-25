import React from "react";
import ReactECharts from "echarts-for-react";
import type { ForecastSeriesItem } from "@/api/types";
import { VARIABLES, type WeatherVariable } from "@/store/uiStore";

interface ForecastChartProps {
  series: ForecastSeriesItem[];
  variable: WeatherVariable;
  locationName: string;
  visibleModels?: {
    gfs: boolean;
    ecmwf_ifs: boolean;
    icon: boolean;
    aifs: boolean;
    blended: boolean;
  };
}

function formatShortDate(dateStr: string): string {
  if (!dateStr) return "";
  const clean = dateStr.split("T")[0];
  const parts = clean.split("-");
  if (parts.length === 3) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const mIdx = parseInt(parts[1], 10) - 1;
    const day = parseInt(parts[2], 10);
    if (mIdx >= 0 && mIdx < 12 && !isNaN(day)) {
      return `${months[mIdx]} ${day}`;
    }
  }
  return dateStr;
}

export const ForecastChart: React.FC<ForecastChartProps> = ({
  series,
  variable,
  locationName,
  visibleModels = {
    gfs: true,
    ecmwf_ifs: true,
    icon: true,
    aifs: true,
    blended: true,
  },
}) => {
  const varMeta = VARIABLES[variable];

  const blendedVals = series.map((s) => s.blended);
  const gfsVals = series.map((s) => s.models?.gfs ?? null);
  const ifsVals = series.map((s) => s.models?.ecmwf_ifs ?? null);
  const iconVals = series.map((s) => s.models?.icon ?? null);
  const aifsVals = series.map((s) => s.models?.aifs ?? null);

  // Calculate min and max envelope across models
  const minVals = series.map((s) => {
    const vals = [
      s.models?.gfs,
      s.models?.ecmwf_ifs,
      s.models?.icon,
      s.models?.aifs,
    ].filter((v): v is number => v !== undefined && v !== null);
    return vals.length > 0 ? Math.min(...vals) : s.blended;
  });

  const maxVals = series.map((s) => {
    const vals = [
      s.models?.gfs,
      s.models?.ecmwf_ifs,
      s.models?.icon,
      s.models?.aifs,
    ].filter((v): v is number => v !== undefined && v !== null);
    return vals.length > 0 ? Math.max(...vals) : s.blended;
  });

  const spreadBandVals = maxVals.map((max, idx) => Math.max(0, max - minVals[idx]));

  // Threshold markLines (rendered by default for IMD grounded decision support)
  const getThresholdMarkLine = () => {
    if (variable === "rain_mm") {
      return {
        symbol: "none",
        data: [
          {
            yAxis: 64.5,
            lineStyle: { color: "#d29922", type: "dashed", width: 1.5 },
            label: { formatter: "Heavy Rain (64.5 mm)", color: "#d29922", position: "insideEndTop" },
          },
          {
            yAxis: 115.6,
            lineStyle: { color: "#db6d28", type: "dashed", width: 1.5 },
            label: { formatter: "Very Heavy (115.6 mm)", color: "#db6d28", position: "insideEndTop" },
          },
        ],
      };
    }
    if (variable === "tmax_c") {
      return {
        symbol: "none",
        data: [
          {
            yAxis: 40.0,
            lineStyle: { color: "#db6d28", type: "dashed", width: 1.5 },
            label: { formatter: "Heatwave (40°C)", color: "#db6d28", position: "insideEndTop" },
          },
          {
            yAxis: 45.0,
            lineStyle: { color: "#f85149", type: "dashed", width: 1.5 },
            label: { formatter: "Severe (45°C)", color: "#f85149", position: "insideEndTop" },
          },
        ],
      };
    }
    // wind_max_kmh
    return {
      symbol: "none",
      data: [
        {
          yAxis: 62.0,
          lineStyle: { color: "#d29922", type: "dashed", width: 1.5 },
          label: { formatter: "Gale (62 km/h)", color: "#d29922", position: "insideEndTop" },
        },
      ],
    };
  };

  const chartOptions = {
    backgroundColor: "transparent",
    animationDuration: 300,
    tooltip: {
      trigger: "axis",
      backgroundColor: "#FFFFFF",
      borderColor: "rgba(26,23,18,0.12)",
      borderWidth: 1,
      borderRadius: 12,
      extraCssText: "box-shadow: 0 4px 20px rgba(26,23,18,0.12);",
      textStyle: { color: "#1A1712", fontSize: 12, fontFamily: "'Instrument Sans', system-ui" },
      formatter: (params: any) => {
        if (!params || !params.length) return "";
        const idx = params[0].dataIndex;
        const item = series[idx];
        if (!item) return "";
        let out = `<div style="padding: 2px 4px;">`;
        out += `<div style="font-weight: bold; margin-bottom: 4px; border-bottom: 1px solid rgba(26,23,18,0.10); padding-bottom: 4px; color: #1A1712;">`;
        out += `${locationName} · ${item.valid_date} (D+${item.lead_days})`;
        out += `</div>`;
        out += `<div style="display: flex; justify-content: space-between; gap: 16px; margin: 3px 0; color: #E86440; font-weight: bold;">`;
        out += `<span>AAGAM Blended:</span><span style="font-family: monospace;">${item.blended != null ? item.blended.toFixed(1) : "—"} ${varMeta.shortUnit}</span>`;
        out += `</div>`;

        if (item.models?.gfs !== undefined && item.models?.gfs !== null) {
          out += `<div style="display: flex; justify-content: space-between; gap: 16px; margin: 2px 0; color: #4C7BD9;">`;
          out += `<span>GFS (NOAA):</span><span style="font-family: monospace;">${item.models.gfs.toFixed(1)} ${varMeta.shortUnit}</span>`;
          out += `</div>`;
        }
        if (item.models?.ecmwf_ifs !== undefined && item.models?.ecmwf_ifs !== null) {
          out += `<div style="display: flex; justify-content: space-between; gap: 16px; margin: 2px 0; color: #4FA37A;">`;
          out += `<span>ECMWF IFS:</span><span style="font-family: monospace;">${item.models.ecmwf_ifs.toFixed(1)} ${varMeta.shortUnit}</span>`;
          out += `</div>`;
        }
        if (item.models?.icon !== undefined && item.models?.icon !== null) {
          out += `<div style="display: flex; justify-content: space-between; gap: 16px; margin: 2px 0; color: #C98A1E;">`;
          out += `<span>DWD ICON:</span><span style="font-family: monospace;">${item.models.icon.toFixed(1)} ${varMeta.shortUnit}</span>`;
          out += `</div>`;
        }
        if (item.models?.aifs !== undefined && item.models?.aifs !== null) {
          out += `<div style="display: flex; justify-content: space-between; gap: 16px; margin: 2px 0; color: #8B6FD9;">`;
          out += `<span>ECMWF AIFS (AI):</span><span style="font-family: monospace;">${item.models.aifs.toFixed(1)} ${varMeta.shortUnit}</span>`;
          out += `</div>`;
        }

        out += `<div style="border-top: 1px solid rgba(26,23,18,0.10); margin-top: 4px; pt-2; display: flex; justify-content: space-between; font-size: 11px; color: #A09890;">`;
        out += `<span>Model Spread (σ):</span><span style="font-family: monospace;">${item.spread != null ? item.spread.toFixed(1) : "—"} ${varMeta.shortUnit}</span>`;
        out += `</div>`;
        out += `</div>`;
        return out;
      },
    },
    legend: {
      data: ["AAGAM Blended", "GFS", "ECMWF IFS", "DWD ICON", "ECMWF AIFS"],
      top: 0,
      textStyle: { color: "#6B6560", fontSize: 11 },
      icon: "circle",
    },
    grid: {
      left: "3%",
      right: "4%",
      bottom: "10%",
      top: "14%",
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: series.map((s) => `${formatShortDate(s.valid_date)}\nD+${s.lead_days}`),
      boundaryGap: false,
      axisLine: { lineStyle: { color: "rgba(26,23,18,0.15)" } },
      axisLabel: {
        color: "#A09890",
        fontSize: 11,
        hideOverlap: true,
      },
    },
    yAxis: {
      type: "value",
      name: varMeta.unit,
      nameTextStyle: { color: "#A09890", fontSize: 11, align: "left" },
      splitLine: { lineStyle: { color: "rgba(26,23,18,0.07)" } },
      axisLabel: { color: "#A09890", fontSize: 11, fontFamily: "monospace" },
    },
    series: [
      // Confidence band base (rendered by default)
      {
        name: "Min Base",
        type: "line",
        data: minVals,
        lineStyle: { opacity: 0 },
        stack: "confidence-band",
        symbol: "none",
      },
      {
        name: "Spread Band",
        type: "line",
        data: spreadBandVals,
        lineStyle: { opacity: 0 },
        areaStyle: { color: "rgba(56, 139, 253, 0.12)" },
        stack: "confidence-band",
        symbol: "none",
      },

      // Individual Model Lines
      ...(visibleModels.gfs
        ? [
            {
              name: "GFS",
              type: "line",
              data: gfsVals,
              lineStyle: { color: "#58a6ff", width: 1.5, type: "solid" },
              itemStyle: { color: "#58a6ff" },
              symbol: "emptyCircle",
              symbolSize: 4,
            },
          ]
        : []),
      ...(visibleModels.ecmwf_ifs
        ? [
            {
              name: "ECMWF IFS",
              type: "line",
              data: ifsVals,
              lineStyle: { color: "#3fb950", width: 1.5, type: "solid" },
              itemStyle: { color: "#3fb950" },
              symbol: "emptyCircle",
              symbolSize: 4,
            },
          ]
        : []),
      ...(visibleModels.icon
        ? [
            {
              name: "DWD ICON",
              type: "line",
              data: iconVals,
              lineStyle: { color: "#f0883e", width: 1.5, type: "solid" },
              itemStyle: { color: "#f0883e" },
              symbol: "emptyCircle",
              symbolSize: 4,
            },
          ]
        : []),
      ...(visibleModels.aifs
        ? [
            {
              name: "ECMWF AIFS",
              type: "line",
              data: aifsVals,
              lineStyle: { color: "#a371f7", width: 1.5, type: "solid" },
              itemStyle: { color: "#a371f7" },
              symbol: "emptyCircle",
              symbolSize: 4,
            },
          ]
        : []),

      // Thick AAGAM Blended Line
      ...(visibleModels.blended
        ? [
            {
              name: "AAGAM Blended",
              type: "line",
              data: blendedVals,
              lineStyle: { color: "#388bfd", width: 3.5 },
              itemStyle: { color: "#388bfd" },
              symbol: "circle",
              symbolSize: 6,
              markLine: getThresholdMarkLine(),
            },
          ]
        : []),
    ],
  };

  return (
    <div className="w-full h-[360px]">
      <ReactECharts
        option={chartOptions}
        style={{ height: "100%", width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
};
