import React from "react";
import ReactECharts from "echarts-for-react";
import { AlertCircle } from "lucide-react";
import type { SkillScoreItem } from "@/api/types";

interface CategoricalSkillChartProps {
  scores: SkillScoreItem[];
  leadDays?: number;
  thresholdMm?: number;
}

export const CategoricalSkillChart: React.FC<CategoricalSkillChartProps> = ({
  scores,
  leadDays = 1,
  thresholdMm = 64.5,
}) => {
  // Filter for scores matching leadDays and the specified threshold (e.g. 64.5 mm Heavy Rain)
  const matchingScores = scores.filter((s) => {
    if (s.lead_days !== leadDays) return false;
    if (s.threshold_mm === null || s.threshold_mm === undefined) return false;
    // Match within 1.0mm tolerance (covers 64.5 floating-point differences)
    return Math.abs(s.threshold_mm - thresholdMm) < 1.0;
  });

  const modelLabels: Record<string, string> = {
    blend: "AAGAM Blend",
    gfs: "GFS",
    ecmwf_ifs: "ECMWF IFS",
    icon: "DWD ICON",
    aifs: "ECMWF AIFS",
  };

  const models = ["blend", "ecmwf_ifs", "gfs", "icon", "aifs"];

  // Check if any qualifying events were observed or forecasted across any model
  const hasQualifyingEvents = matchingScores.some((s) => {
    const hits = s.hits ?? 0;
    const misses = s.misses ?? 0;
    const fa = s.false_alarms ?? 0;
    return hits > 0 || misses > 0 || fa > 0 || (s.csi !== null && s.csi !== undefined);
  });

  if (matchingScores.length === 0 || !hasQualifyingEvents) {
    return (
      <div className="w-full h-[280px] flex flex-col items-center justify-center text-text-muted p-6 border border-dashed border-[rgba(26,23,18,0.12)] rounded-lg">
        <AlertCircle className="w-7 h-7 text-amber-500/80 mb-2" />
        <div className="text-xs font-semibold text-text-primary">
          Insufficient Events (≥ {thresholdMm} mm/24h)
        </div>
        <p className="text-[11px] text-text-muted text-center max-w-sm mt-1 leading-relaxed">
          No qualifying heavy rainfall events were observed or predicted in this operational window for Lead D+{leadDays}.
          Contingency metrics (POD, FAR, CSI) are undefined when event counts are zero and are not fabricated as 0.00.
        </p>
      </div>
    );
  }

  const podData: (any | null)[] = [];
  const farData: (any | null)[] = [];
  const csiData: (any | null)[] = [];
  const categories: string[] = [];

  models.forEach((m) => {
    const item = matchingScores.find((s) => s.model === m);
    categories.push(modelLabels[m] || m);
    if (item) {
      podData.push(
        item.pod !== null && item.pod !== undefined
          ? { value: Number(item.pod.toFixed(3)), item }
          : null
      );
      farData.push(
        item.far !== null && item.far !== undefined
          ? { value: Number(item.far.toFixed(3)), item }
          : null
      );
      csiData.push(
        item.csi !== null && item.csi !== undefined
          ? { value: Number(item.csi.toFixed(3)), item }
          : null
      );
    } else {
      podData.push(null);
      farData.push(null);
      csiData.push(null);
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
      formatter: (params: any) => {
        if (!params?.length) return "";
        let out = `<div style="padding: 2px 4px;">`;
        out += `<div style="font-weight: bold; margin-bottom: 4px; border-bottom: 1px solid rgba(26,23,18,0.10); padding-bottom: 4px; color: #1A1712;">`;
        out += `${params[0].axisValue} · Lead D+${leadDays} (≥ ${thresholdMm} mm)`;
        out += `</div>`;
        let itemRef: SkillScoreItem | null = null;
        params.forEach((p: any) => {
          const itemVal = typeof p.value === "object" && p.value !== null ? p.value.value : p.value;
          if (p.data?.item) itemRef = p.data.item;
          out += `<div style="display: flex; justify-content: space-between; gap: 16px; margin: 2px 0;">`;
          out += `<span style="color: ${p.color};">${p.seriesName}:</span>`;
          if (itemVal !== null && itemVal !== undefined && !isNaN(itemVal)) {
            out += `<span style="font-family: monospace; font-weight: bold;">${itemVal.toFixed(3)}</span>`;
          } else {
            out += `<span style="font-family: monospace; color: #A09890;">— (undefined)</span>`;
          }
          out += `</div>`;
        });
        if (itemRef) {
          const ref = itemRef as SkillScoreItem;
          out += `<div style="margin-top: 6px; padding-top: 4px; border-top: 1px dashed rgba(26,23,18,0.10); font-size: 10px; color: #6B6560; font-family: monospace;">`;
          out += `Hits: ${ref.hits ?? 0} | False Alarms: ${ref.false_alarms ?? 0} | Misses: ${ref.misses ?? 0} | Correct Neg: ${ref.correct_negatives ?? 0}`;
          if (ref.n) out += ` (n=${ref.n})`;
          out += `</div>`;
        }
        out += `</div>`;
        return out;
      },
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

