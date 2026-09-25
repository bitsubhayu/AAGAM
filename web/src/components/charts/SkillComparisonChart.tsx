import React from "react";
import ReactECharts from "echarts-for-react";
import { Activity } from "lucide-react";
import type { SkillScoreItem } from "@/api/types";

interface SkillComparisonChartProps {
  scores: SkillScoreItem[];
  metric?: "mae" | "rmse" | "bias";
  unit?: string;
  dataStatus?: string;
}

export const SkillComparisonChart: React.FC<SkillComparisonChartProps> = ({
  scores,
  metric = "mae",
  unit = "mm/24h",
  dataStatus,
}) => {
  const leads = [1, 2, 3, 4, 5, 6, 7];
  const models = ["blend", "gfs", "ecmwf_ifs", "icon", "aifs", "equal_mean"];

  // Filter for continuous metric rows (threshold_mm === 0 or mae != null)
  const contScores = scores.filter(
    (s) => s.threshold_mm === 0 || s.threshold_mm === null || s.mae !== null
  );

  // Map each model to an array of lead data points { value, n, lead } or null
  const modelDataMap = new Map<string, (any | null)[]>();
  models.forEach((m) => modelDataMap.set(m, new Array(leads.length).fill(null)));

  let hasAnyData = false;

  contScores.forEach((s) => {
    const leadIdx = leads.indexOf(s.lead_days);
    if (leadIdx !== -1 && modelDataMap.has(s.model)) {
      const val = s[metric];
      if (val !== undefined && val !== null) {
        hasAnyData = true;
        modelDataMap.get(s.model)![leadIdx] = {
          value: Number(val.toFixed(2)),
          n: s.n ?? 0,
          lead: s.lead_days,
        };
      }
    }
  });

  if (!hasAnyData || scores.length === 0) {
    return (
      <div className="w-full h-[340px] flex flex-col items-center justify-center text-text-muted p-6 border border-dashed border-[rgba(26,23,18,0.12)] rounded-lg">
        <Activity className="w-8 h-8 mb-2 opacity-40 text-text-muted" />
        <div className="font-semibold text-sm text-text-primary">
          No Verified Operational Data Available Yet
        </div>
        <div className="text-xs text-text-muted mt-1 max-w-md text-center">
          Operational forecast verification requires matching ground truth observations.
          Points will appear automatically once daily operational forecasts have matching valid truth.
        </div>
      </div>
    );
  }

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
        if (!params?.length) return "";
        let out = `<div style="padding: 2px 4px;">`;
        out += `<div style="font-weight: bold; margin-bottom: 4px; border-bottom: 1px solid rgba(26,23,18,0.10); padding-bottom: 4px; color: #1A1712; display: flex; justify-content: space-between; align-items: center; gap: 8px;">`;
        out += `<span>Lead Day ${params[0].axisValue} · ${metric.toUpperCase()}</span>`;
        if (dataStatus && dataStatus.includes("PRELIMINARY")) {
          out += `<span style="font-size: 9px; padding: 1px 4px; border-radius: 4px; background: #FEF3C7; color: #92400E; font-weight: normal;">PRELIMINARY</span>`;
        }
        out += `</div>`;
        let hasItems = false;
        params.forEach((p: any) => {
          const itemVal = typeof p.value === "object" && p.value !== null ? p.value.value : p.value;
          const sampleN = p.data?.n;
          if (itemVal !== null && itemVal !== undefined && !isNaN(itemVal)) {
            hasItems = true;
            out += `<div style="display: flex; justify-content: space-between; align-items: center; gap: 16px; margin: 2px 0;">`;
            out += `<span style="color: ${p.color};">${p.seriesName}:</span>`;
            out += `<div style="display: flex; align-items: baseline; gap: 6px;">`;
            out += `<span style="font-family: monospace; font-weight: bold;">${itemVal.toFixed(2)} ${unit}</span>`;
            if (sampleN !== undefined && sampleN !== null) {
              out += `<span style="font-family: monospace; font-size: 10px; color: #A09890;">(n=${sampleN})</span>`;
            }
            out += `</div></div>`;
          }
        });
        if (!hasItems) {
          out += `<div style="font-size: 11px; color: #A09890; font-style: italic;">No verified observations for this lead yet</div>`;
        }
        out += `</div>`;
        return out;
      },
    },
    legend: {
      data: ["AAGAM Blend", "GFS (NOAA)", "ECMWF IFS", "DWD ICON", "ECMWF AIFS", "Equal-Mean Baseline"],
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
      data: leads.map((l) => `D+${l}`),
      axisLine: { lineStyle: { color: "rgba(26,23,18,0.15)" } },
      axisLabel: { color: "#A09890", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      name: `${metric.toUpperCase()} (${unit})`,
      nameTextStyle: { color: "#6B6560", fontSize: 11, align: "left" },
      splitLine: { lineStyle: { color: "rgba(26,23,18,0.07)" } },
      axisLabel: { color: "#A09890", fontSize: 11, fontFamily: "monospace" },
    },
    series: [
      {
        name: "AAGAM Blend",
        type: "line",
        connectNulls: false,
        data: modelDataMap.get("blend") || [],
        lineStyle: { color: "#388bfd", width: 3 },
        itemStyle: { color: "#388bfd" },
        symbol: "circle",
        symbolSize: 6,
      },
      {
        name: "GFS (NOAA)",
        type: "line",
        connectNulls: false,
        data: modelDataMap.get("gfs") || [],
        lineStyle: { color: "#58a6ff", width: 1.5 },
        itemStyle: { color: "#58a6ff" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "ECMWF IFS",
        type: "line",
        connectNulls: false,
        data: modelDataMap.get("ecmwf_ifs") || [],
        lineStyle: { color: "#3fb950", width: 1.5 },
        itemStyle: { color: "#3fb950" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "DWD ICON",
        type: "line",
        connectNulls: false,
        data: modelDataMap.get("icon") || [],
        lineStyle: { color: "#f0883e", width: 1.5 },
        itemStyle: { color: "#f0883e" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "ECMWF AIFS",
        type: "line",
        connectNulls: false,
        data: modelDataMap.get("aifs") || [],
        lineStyle: { color: "#a371f7", width: 1.5 },
        itemStyle: { color: "#a371f7" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "Equal-Mean Baseline",
        type: "line",
        connectNulls: false,
        data: modelDataMap.get("equal_mean") || [],
        lineStyle: { color: "#8b949e", width: 1.5, type: "dashed" },
        itemStyle: { color: "#8b949e" },
        symbol: "none",
      },
    ],
  };

  return (
    <div className="w-full h-[340px]">
      <ReactECharts
        option={chartOptions}
        style={{ height: "100%", width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
};

