import React, { useState } from "react";
import {
  Download,
  FileSpreadsheet,
  FileCode,
  Terminal,
  Copy,
  Check,
} from "lucide-react";
import { useMeta } from "@/api/useMeta";
import { downloadExportFile, getExportDownloadUrl } from "@/api/useHistory";
import { Card, CardHeader, CardTitle, CardDescription } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

export const DataExportPage: React.FC = () => {
  const { data: meta } = useMeta();

  const [dataset, setDataset] = useState<"forecasts" | "alerts" | "weights" | "skill">("forecasts");
  const [format, setFormat] = useState<"csv" | "json">("csv");
  const [variable, setVariable] = useState<string>("rain_mm");
  const [locationSlug, setLocationSlug] = useState<string>("ALL");
  const [isDownloading, setIsDownloading] = useState(false);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const locations = meta?.locations || [];

  const handleDownload = async () => {
    setIsDownloading(true);
    try {
      await downloadExportFile(dataset, format, variable, locationSlug);
      toast.success(`Streaming export of ${dataset} (${format.toUpperCase()}) completed.`);
    } catch (err: any) {
      toast.error(`Export failed: ${err.message}`);
    } finally {
      setIsDownloading(false);
    }
  };

  const exportUrl = getExportDownloadUrl(dataset, format, variable, locationSlug);

  const curlSnippet = `curl -X GET "${window.location.origin}${exportUrl}" \\
  -H "Authorization: Bearer <YOUR_SUPABASE_JWT>" \\
  --output aagam_${dataset}.${format}`;

  const pythonSnippet = `import requests

url = "${window.location.origin}${exportUrl}"
headers = {"Authorization": "Bearer <YOUR_SUPABASE_JWT>"}

response = requests.get(url, headers=headers, stream=True)
with open("aagam_${dataset}.${format}", "wb") as f:
    for chunk in response.iter_content(chunk_size=8192):
        f.write(chunk)
print("Saved aagam_${dataset}.${format}")`;

  const copySnippet = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedCode(id);
    toast.success("Snippet copied to clipboard");
    setTimeout(() => setCopiedCode(null), 2000);
  };

  return (
    <div className="space-y-4 font-sans">
      {/* Exporter Configuration Card */}
      <Card className="p-4">
        <CardHeader className="pb-2 mb-2">
          <div>
            <CardTitle>
              <Download className="w-4 h-4 text-brand-blue" />
              <span>Scientific Data Exporter</span>
            </CardTitle>
            <CardDescription>
              Stream operational forecast records, weights, alerts, or skill metrics (PRD §12)
            </CardDescription>
          </div>
        </CardHeader>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 pt-2">
          {/* Dataset Picker */}
          <div>
            <label className="block text-[11px] font-semibold text-text-muted mb-1">
              Select Dataset:
            </label>
            <select
              value={dataset}
              onChange={(e) => setDataset(e.target.value as any)}
              className="w-full p-2 bg-[#21262d] border border-border rounded text-xs text-text-primary outline-none"
            >
              <option value="forecasts">Forecasts (Blended & NWP Models)</option>
              <option value="alerts">Extreme Hazard Alerts</option>
              <option value="weights">Adaptive Model Weights Matrix</option>
              <option value="skill">Skill Scores & Contingency Table</option>
            </select>
          </div>

          {/* Format Picker */}
          <div>
            <label className="block text-[11px] font-semibold text-text-muted mb-1">
              Format:
            </label>
            <div className="flex items-center gap-2 pt-0.5">
              <button
                onClick={() => setFormat("csv")}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded text-xs border font-mono transition-colors ${
                  format === "csv"
                    ? "bg-brand-blue/20 text-brand-blue border-brand-blue font-bold"
                    : "bg-[#21262d] text-text-secondary border-border"
                }`}
              >
                <FileSpreadsheet className="w-3.5 h-3.5" />
                <span>CSV</span>
              </button>
              <button
                onClick={() => setFormat("json")}
                className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded text-xs border font-mono transition-colors ${
                  format === "json"
                    ? "bg-brand-blue/20 text-brand-blue border-brand-blue font-bold"
                    : "bg-[#21262d] text-text-secondary border-border"
                }`}
              >
                <FileCode className="w-3.5 h-3.5" />
                <span>JSON</span>
              </button>
            </div>
          </div>

          {/* Variable Filter */}
          <div>
            <label className="block text-[11px] font-semibold text-text-muted mb-1">
              Variable Filter:
            </label>
            <select
              value={variable}
              onChange={(e) => setVariable(e.target.value)}
              className="w-full p-2 bg-[#21262d] border border-border rounded text-xs text-text-primary outline-none"
            >
              <option value="rain_mm">Rainfall (rain_mm)</option>
              <option value="tmax_c">Max Temp (tmax_c)</option>
              <option value="wind_max_kmh">Wind Gust (wind_max_kmh)</option>
            </select>
          </div>

          {/* Location Filter */}
          <div>
            <label className="block text-[11px] font-semibold text-text-muted mb-1">
              Station Location:
            </label>
            <select
              value={locationSlug}
              onChange={(e) => setLocationSlug(e.target.value)}
              className="w-full p-2 bg-[#21262d] border border-border rounded text-xs text-text-primary outline-none"
            >
              <option value="ALL">All Representative Locations (40)</option>
              {locations.map((l) => (
                <option key={l.slug} value={l.slug}>
                  {l.name} ({l.region})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Download Trigger */}
        <div className="mt-4 pt-3 border-t border-border/60 flex items-center justify-between flex-wrap gap-2">
          <div className="text-xs text-text-muted">
            Direct Streaming Endpoint:{" "}
            <span className="font-mono text-text-secondary text-[11px]">{exportUrl}</span>
          </div>

          <Button
            variant="primary"
            size="md"
            onClick={handleDownload}
            isLoading={isDownloading}
          >
            <Download className="w-4 h-4 mr-1.5" />
            <span>Download {dataset.toUpperCase()} ({format.toUpperCase()})</span>
          </Button>
        </div>
      </Card>

      {/* Developer / Researcher API Code Snippets (PRD §10.4 FR-UI-7) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* cURL Snippet */}
        <Card className="p-4">
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-border/80">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-brand-blue" />
              <span className="text-xs font-bold text-text-primary">cURL API Access</span>
            </div>
            <button
              onClick={() => copySnippet(curlSnippet, "curl")}
              className="text-text-muted hover:text-text-primary"
            >
              {copiedCode === "curl" ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>
          <pre className="p-3 bg-[#0d1117] rounded border border-border text-[11px] font-mono text-emerald-400 overflow-x-auto">
            {curlSnippet}
          </pre>
        </Card>

        {/* Python Snippet */}
        <Card className="p-4">
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-border/80">
            <div className="flex items-center gap-2">
              <FileCode className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-bold text-text-primary">Python Research Client</span>
            </div>
            <button
              onClick={() => copySnippet(pythonSnippet, "python")}
              className="text-text-muted hover:text-text-primary"
            >
              {copiedCode === "python" ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
          </div>
          <pre className="p-3 bg-[#0d1117] rounded border border-border text-[11px] font-mono text-blue-300 overflow-x-auto">
            {pythonSnippet}
          </pre>
        </Card>
      </div>
    </div>
  );
};
