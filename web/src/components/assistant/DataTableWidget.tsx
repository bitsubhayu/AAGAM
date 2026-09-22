import React, { useState, useMemo } from "react";
import {
  Download,
  Copy,
  Check,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ExternalLink,
  Table as TableIcon,
} from "lucide-react";
import { toast } from "sonner";
import { API_BASE } from "@/api/client";

export interface DataTablePayload {
  artifact_id: string;
  title: string;
  columns: string[];
  rows: any[][];
  n_rows_total: number;
  download_links: {
    csv: string;
    json: string;
  };
}

interface DataTableWidgetProps {
  dataTable: DataTablePayload;
  onInspectArtifact?: (artifactId: string) => void;
}

export const DataTableWidget: React.FC<DataTableWidgetProps> = ({
  dataTable,
  onInspectArtifact,
}) => {
  const [sortColIndex, setSortColIndex] = useState<number | null>(null);
  const [sortAsc, setSortAsc] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);

  const handleSort = (idx: number) => {
    if (sortColIndex === idx) {
      setSortAsc(!sortAsc);
    } else {
      setSortColIndex(idx);
      setSortAsc(true);
    }
  };

  const sortedRows = useMemo(() => {
    if (sortColIndex === null) return dataTable.rows;
    return [...dataTable.rows].sort((a, b) => {
      const valA = a[sortColIndex];
      const valB = b[sortColIndex];
      if (valA === valB) return 0;
      if (valA === null || valA === undefined) return 1;
      if (valB === null || valB === undefined) return -1;

      if (typeof valA === "number" && typeof valB === "number") {
        return sortAsc ? valA - valB : valB - valA;
      }
      return sortAsc
        ? String(valA).localeCompare(String(valB))
        : String(valB).localeCompare(String(valA));
    });
  }, [dataTable.rows, sortColIndex, sortAsc]);

  const handleCopyCSV = () => {
    try {
      const headerLine = dataTable.columns.join(",");
      const rowLines = dataTable.rows.map((r) =>
        r.map((v) => (v === null || v === undefined ? "" : `"${v}"`)).join(",")
      );
      const csvText = [headerLine, ...rowLines].join("\n");
      navigator.clipboard.writeText(csvText);
      setCopied(true);
      toast.success("Table copied to clipboard as CSV");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy CSV");
    }
  };

  const downloadCsvUrl = `${API_BASE.replace("/api/v1", "")}${dataTable.download_links.csv}`;
  const downloadJsonUrl = `${API_BASE.replace("/api/v1", "")}${dataTable.download_links.json}`;

  return (
    <div className="my-2 rounded border border-border bg-[#111922] overflow-hidden text-xs">
      {/* Table Header Bar */}
      <div className="px-3 py-2 bg-[#161b22] border-b border-border flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <TableIcon className="w-3.5 h-3.5 text-brand-blue flex-shrink-0" />
          <span className="font-semibold text-text-primary truncate" title={dataTable.title}>
            {dataTable.title}
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#21262d] text-text-muted font-mono">
            {dataTable.n_rows_total} rows
          </span>
        </div>

        {/* Quick Action Toolbar */}
        <div className="flex items-center gap-1">
          <button
            onClick={handleCopyCSV}
            className="flex items-center gap-1 px-2 py-1 rounded bg-[#21262d] hover:bg-[#30363d] text-text-secondary hover:text-text-primary text-[11px] transition-colors"
            title="Copy as CSV"
          >
            {copied ? <Check className="w-3 h-3 text-brand-green" /> : <Copy className="w-3 h-3" />}
            <span>Copy</span>
          </button>

          <a
            href={downloadCsvUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 px-2 py-1 rounded bg-[#21262d] hover:bg-[#30363d] text-text-secondary hover:text-text-primary text-[11px] transition-colors"
            title="Download CSV"
          >
            <Download className="w-3 h-3" />
            <span>CSV</span>
          </a>

          <a
            href={downloadJsonUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 px-2 py-1 rounded bg-[#21262d] hover:bg-[#30363d] text-text-secondary hover:text-text-primary text-[11px] transition-colors"
            title="Download JSON"
          >
            <Download className="w-3 h-3" />
            <span>JSON</span>
          </a>

          {onInspectArtifact && (
            <button
              onClick={() => onInspectArtifact(dataTable.artifact_id)}
              className="flex items-center gap-1 px-2 py-1 rounded bg-blue-500/10 hover:bg-blue-500/20 text-brand-blue text-[11px] transition-colors border border-blue-500/30"
              title="Inspect Artifact Details"
            >
              <ExternalLink className="w-3 h-3" />
              <span>Inspect</span>
            </button>
          )}
        </div>
      </div>

      {/* Scrollable Data Table Container */}
      <div className="overflow-x-auto max-h-72 overflow-y-auto">
        <table className="w-full text-left border-collapse text-[11px]">
          <thead className="bg-[#1c2430] text-text-secondary sticky top-0 z-10 border-b border-border shadow-sm">
            <tr>
              {dataTable.columns.map((col, idx) => {
                const isSorted = sortColIndex === idx;
                return (
                  <th
                    key={col}
                    onClick={() => handleSort(idx)}
                    className="px-2.5 py-1.5 font-medium cursor-pointer hover:bg-[#263242] transition-colors select-none whitespace-nowrap"
                  >
                    <div className="flex items-center gap-1">
                      <span>{col}</span>
                      {isSorted ? (
                        sortAsc ? (
                          <ArrowUp className="w-3 h-3 text-brand-blue" />
                        ) : (
                          <ArrowDown className="w-3 h-3 text-brand-blue" />
                        )
                      ) : (
                        <ArrowUpDown className="w-2.5 h-2.5 text-text-muted opacity-50" />
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/40 font-mono">
            {sortedRows.map((row, rIdx) => (
              <tr
                key={rIdx}
                className={rIdx % 2 === 0 ? "bg-[#111922] hover:bg-[#1a2330]" : "bg-[#141d28] hover:bg-[#1a2330]"}
              >
                {row.map((val, cIdx) => (
                  <td key={cIdx} className="px-2.5 py-1 whitespace-nowrap text-text-primary text-[11px]">
                    {val === null || val === undefined ? (
                      <span className="text-text-muted">—</span>
                    ) : typeof val === "number" ? (
                      val
                    ) : (
                      String(val)
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer Indicator */}
      {dataTable.n_rows_total > dataTable.rows.length && (
        <div className="px-3 py-1.5 bg-[#161b22] border-t border-border text-[10px] text-text-muted flex items-center justify-between">
          <span>
            Showing first {dataTable.rows.length} of {dataTable.n_rows_total} rows.
          </span>
          <span>Use download actions above to access full dataset.</span>
        </div>
      )}
    </div>
  );
};
