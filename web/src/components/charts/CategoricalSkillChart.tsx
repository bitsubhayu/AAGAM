import React from "react";
import ReactECharts from "echarts-for-react";
import type { SkillScoreItem } from "@/api/types";

interface CategoricalSkillChartProps {
  scores: SkillScoreItem[];
  leadDays?: number;
}

export const CategoricalSkillChart: React.FC<CategoricalSkillChartProps> = ({
  scores,
  leadDays = 1,
}) => {
  // Filter for scores matching leadDays and having categorical metrics (pod, far, csi)
  const matchingScores = scores.filter(
    (s) => s.lead_days === leadDays && s.pod !== null && s.pod !== undefined
  );

  const modelLabels: Record<string, string> = {
    blend: "AAGAM Blend",
    gfs: "GFS",
    ecmwf_ifs: "ECMWF IFS",
    icon: "DWD ICON",
    aifs: "ECMWF AIFS",
  };

  const models = ["blend", "ecmwf_ifs", "gfs", "icon", "aifs"];
  const podData: number[] = [];
  const farData: number[] = [];
  const csiData: number[] = [];
  const categories: string[] = [];

  models.forEach((m) => {
    const item = matchingScores.find((s) => s.model === m);
    if (item) {
      categories.push(modelLabels[m] || m);
      podData.push(item.pod ?? 0);
      farData.push(item.far ?? 0);
      csiData.push(item.csi ?? 0);
    }
  });

  const chartOptions = {
    backgroundColor: "transparent",
    animationDuration: 300,
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: "#FFFFFF",
      borderColor: "rgba(26,23,18,0.12)",
      borderWidth: 1,
      borderRadius: 12,
      extraCssText: "box-shadow: 0 4px 20px rgba(26,23,18,0.12);",
      textStyle: { color: "#1A1712", fontSize: 12, fontFamily: "'Instrument Sans', system-ui" },
    },
    legend: {
      data: ["POD (Hit Rate ↑)", "FAR (False Alarm ↓)", "CSI (Critical Success ↑)"],
      top: 0,
      textStyle: { color: "#6B6560", fontSize: 11 },
    },
    grid: {
      left: "3%",
      right: "4%",
      bottom: "10%",
      top: "16%",
      containLabel: true,
    },
    xAxis: {
      type: "category",
      data: categories,
      axisLine: { lineStyle: { color: "rgba(26,23,18,0.15)" } },
      axisLabel: { color: "#A09890", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      name: "Score Ratio (0.0 to 1.0)",
      max: 1.0,
      splitLine: { lineStyle: { color: "rgba(26,23,18,0.07)" } },
      axisLabel: { color: "#A09890", fontSize: 11, fontFamily: "monospace" },
    },
    series: [
      {
        name: "POD (Hit Rate ↑)",
        type: "bar",
        data: podData,
        itemStyle: { color: "#4FA37A", borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "FAR (False Alarm ↓)",
        type: "bar",
        data: farData,
        itemStyle: { color: "#E86440", borderRadius: [4, 4, 0, 0] },
      },
      {
        name: "CSI (Critical Success ↑)",
        type: "bar",
        data: csiData,
        itemStyle: { color: "#4C7BD9", borderRadius: [4, 4, 0, 0] },
      },
    ],
  };

  return (
    <div className="w-full h-[280px]">
      <ReactECharts
        option={chartOptions}
        style={{ height: "100%", width: "100%" }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
};
