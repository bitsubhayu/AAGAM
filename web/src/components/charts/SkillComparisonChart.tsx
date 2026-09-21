import React from "react";
import ReactECharts from "echarts-for-react";
import type { SkillScoreItem } from "@/api/types";

interface SkillComparisonChartProps {
  scores: SkillScoreItem[];
  metric?: "mae" | "rmse" | "bias";
  unit?: string;
}

export const SkillComparisonChart: React.FC<SkillComparisonChartProps> = ({
  scores,
  metric = "mae",
  unit = "mm/24h",
}) => {
  // Aggregate scores by [model, lead_days]
  const leads = [1, 2, 3, 4, 5, 6, 7];
  const models = ["blend", "gfs", "ecmwf_ifs", "icon", "aifs", "equal_mean"];

  const modelDataMap = new Map<string, (number | null)[]>();
  models.forEach((m) => modelDataMap.set(m, new Array(leads.length).fill(null)));

  scores.forEach((s) => {
    const leadIdx = leads.indexOf(s.lead_days);
    if (leadIdx !== -1 && modelDataMap.has(s.model)) {
      const val = s[metric];
      if (val !== undefined && val !== null) {
        modelDataMap.get(s.model)![leadIdx] = val;
      }
    }
  });

  const chartOptions = {
    backgroundColor: "transparent",
    animationDuration: 300,
    tooltip: {
      trigger: "axis",
      backgroundColor: "#161b22",
      borderColor: "#30363d",
      textStyle: { color: "#c9d1d9", fontSize: 12 },
      formatter: (params: any) => {
        if (!params?.length) return "";
        let out = `<div style="padding: 2px 4px;">`;
        out += `<div style="font-weight: bold; margin-bottom: 4px; border-bottom: 1px solid #30363d; padding-bottom: 4px;">`;
        out += `Lead Day ${params[0].axisValue} · ${metric.toUpperCase()}`;
        out += `</div>`;
        params.forEach((p: any) => {
          if (p.value !== null && p.value !== undefined) {
            out += `<div style="display: flex; justify-content: space-between; gap: 16px; margin: 2px 0;">`;
            out += `<span style="color: ${p.color};">${p.seriesName}:</span>`;
            out += `<span style="font-family: monospace; font-weight: bold;">${p.value.toFixed(2)} ${unit}</span>`;
            out += `</div>`;
          }
        });
        out += `</div>`;
        return out;
      },
    },
    legend: {
      data: ["AAGAM Blend", "GFS (NOAA)", "ECMWF IFS", "DWD ICON", "ECMWF AIFS", "Equal-Mean Baseline"],
      top: 0,
      textStyle: { color: "#8b949e", fontSize: 11 },
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
      axisLine: { lineStyle: { color: "#30363d" } },
      axisLabel: { color: "#8b949e", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      name: `${metric.toUpperCase()} (${unit})`,
      nameTextStyle: { color: "#8b949e", fontSize: 11, align: "left" },
      splitLine: { lineStyle: { color: "#21262d" } },
      axisLabel: { color: "#8b949e", fontSize: 11, fontFamily: "monospace" },
    },
    series: [
      {
        name: "AAGAM Blend",
        type: "line",
        data: modelDataMap.get("blend") || [],
        lineStyle: { color: "#388bfd", width: 3 },
        itemStyle: { color: "#388bfd" },
        symbol: "circle",
        symbolSize: 6,
      },
      {
        name: "GFS (NOAA)",
        type: "line",
        data: modelDataMap.get("gfs") || [],
        lineStyle: { color: "#58a6ff", width: 1.5 },
        itemStyle: { color: "#58a6ff" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "ECMWF IFS",
        type: "line",
        data: modelDataMap.get("ecmwf_ifs") || [],
        lineStyle: { color: "#3fb950", width: 1.5 },
        itemStyle: { color: "#3fb950" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "DWD ICON",
        type: "line",
        data: modelDataMap.get("icon") || [],
        lineStyle: { color: "#f0883e", width: 1.5 },
        itemStyle: { color: "#f0883e" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "ECMWF AIFS",
        type: "line",
        data: modelDataMap.get("aifs") || [],
        lineStyle: { color: "#a371f7", width: 1.5 },
        itemStyle: { color: "#a371f7" },
        symbol: "emptyCircle",
        symbolSize: 4,
      },
      {
        name: "Equal-Mean Baseline",
        type: "line",
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
