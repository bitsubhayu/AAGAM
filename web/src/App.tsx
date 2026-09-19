import { useState, useEffect } from "react";
import {
  Activity,
  Database,
  CloudRain,
  Server,
  CheckCircle2,
  AlertCircle,
  Clock,
  RefreshCw,
  ShieldCheck,
  Terminal,
} from "lucide-react";

interface HealthData {
  status: string;
  app: string;
  version: string;
  timestamp: string;
  timezone_display: string;
  supabase_connected: boolean;
  details?: string;
}

interface HelloData {
  message: string;
  project: string;
  phase: string;
  verification_status: "PASS" | "BLOCKED" | "FAIL" | string;
  supabase_status: string;
  data_source: string;
  read_row: any;
  server_time: string;
}

const DEFAULT_API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export function App() {
  const [apiUrl, setApiUrl] = useState<string>(DEFAULT_API_URL);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [hello, setHello] = useState<HelloData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [isWakingUp, setIsWakingUp] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [secondsElapsed, setSecondsElapsed] = useState<number>(0);

  const fetchData = async (targetUrl: string) => {
    setLoading(true);
    setError(null);
    setIsWakingUp(false);
    setSecondsElapsed(0);

    const startTime = Date.now();
    const wakeTimer = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTime) / 1000);
      setSecondsElapsed(elapsed);
      if (elapsed >= 4) {
        setIsWakingUp(true);
      }
    }, 1000);

    try {
      // 1. Fetch Health
      const healthRes = await fetch(`${targetUrl}/health`);
      if (!healthRes.ok) {
        throw new Error(`Health check returned HTTP ${healthRes.status}`);
      }
      const healthJson = await healthRes.json();
      setHealth(healthJson);

      // 2. Fetch Hello World (Supabase Row)
      const helloRes = await fetch(`${targetUrl}/api/v1/hello`);
      if (!helloRes.ok) {
        throw new Error(`Hello endpoint returned HTTP ${helloRes.status}`);
      }
      const helloJson = await helloRes.json();
      setHello(helloJson);
    } catch (err: any) {
      console.error("API Fetch Error:", err);
      setError(
        err.message ||
          "Failed to connect to backend API. Please verify server status."
      );
    } finally {
      clearInterval(wakeTimer);
      setLoading(false);
      setIsWakingUp(false);
    }
  };

  useEffect(() => {
    fetchData(apiUrl);
  }, [apiUrl]);

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] flex flex-col font-sans">
      {/* Top Banner: MoES Theme & SIH Context */}
      <header className="border-b border-[#30363d] bg-[#161b22] px-6 py-4">
        <div className="max-w-6xl mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-500/10 border border-blue-500/30 rounded-lg text-blue-400">
              <CloudRain className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-white">
                  AAGAM
                </h1>
                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-900/40 text-blue-300 border border-blue-700/50 font-mono">
                  Phase 0 Setup
                </span>
              </div>
              <p className="text-xs text-[#8b949e]">
                Adaptive AI-Grid Assimilation Model · SIH 2026 PS 26081 · MoES /
                NCMRWF
              </p>
            </div>
          </div>

          {/* Quick Status Badges */}
          <div className="flex items-center gap-3 text-xs font-mono">
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#21262d] border border-[#30363d] rounded-md">
              <Server className="w-3.5 h-3.5 text-slate-400" />
              <span>Backend:</span>
              {loading ? (
                <span className="text-yellow-400">Testing...</span>
              ) : error ? (
                <span className="text-red-400">Offline</span>
              ) : (
                <span className="text-emerald-400">Online</span>
              )}
            </div>

            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#21262d] border border-[#30363d] rounded-md">
              <Database className="w-3.5 h-3.5 text-slate-400" />
              <span>Supabase:</span>
              {hello?.verification_status === "PASS" ? (
                <span className="text-emerald-400">Connected (PASS)</span>
              ) : hello?.verification_status === "BLOCKED" ? (
                <span className="text-amber-400">Blocked (Setup Pending)</span>
              ) : hello?.verification_status === "FAIL" ? (
                <span className="text-red-400">Failed</span>
              ) : (
                <span className="text-slate-400">Pending</span>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-6xl w-full mx-auto p-6 space-y-6">
        {/* Endpoint Control Bar */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 w-full sm:w-auto">
            <Terminal className="w-4 h-4 text-[#8b949e]" />
            <span className="text-xs font-mono text-[#8b949e]">API Endpoint:</span>
            <input
              type="text"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              className="bg-[#0d1117] border border-[#30363d] rounded px-3 py-1.5 text-xs font-mono text-white flex-1 sm:w-80 focus:outline-none focus:border-blue-500"
              placeholder="http://localhost:8000 or Render URL"
            />
          </div>

          <button
            onClick={() => fetchData(apiUrl)}
            disabled={loading}
            className="flex items-center gap-2 bg-[#21262d] hover:bg-[#30363d] border border-[#30363d] text-xs font-medium px-4 py-2 rounded-md transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-blue-400" : ""}`} />
            {loading ? "Verifying..." : "Re-test Connection"}
          </button>
        </div>

        {/* Cold-start Warning Banner (for Render free tier) */}
        {isWakingUp && (
          <div className="bg-amber-950/40 border border-amber-800/60 rounded-lg p-4 flex items-start gap-3">
            <Clock className="w-5 h-5 text-amber-400 shrink-0 mt-0.5 animate-pulse" />
            <div>
              <h3 className="text-sm font-medium text-amber-200">
                Server Waking Up ({secondsElapsed}s)
              </h3>
              <p className="text-xs text-amber-300/80 mt-1">
                Render free-tier web services sleep after 15 minutes of inactivity. First request takes ~30–50 seconds to spin up. Please stand by.
              </p>
            </div>
          </div>
        )}

        {/* Error Alert */}
        {error && !loading && (
          <div className="bg-red-950/40 border border-red-800/60 rounded-lg p-4 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
            <div className="flex-1">
              <h3 className="text-sm font-medium text-red-200">
                Connection Failed
              </h3>
              <p className="text-xs text-red-300/80 mt-1 font-mono">
                {error}
              </p>
              <div className="mt-3 text-xs text-[#8b949e]">
                Suggestions:
                <ul className="list-disc list-inside mt-1 space-y-0.5">
                  <li>Verify the backend is running (e.g. <code>uvicorn api.app.main:app --port 8000</code>)</li>
                  <li>Ensure CORS allows your browser origin</li>
                  <li>If deployed to Render, check the service build logs</li>
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Verification Status Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Card 1: FastAPI Health Liveness */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 flex flex-col">
            <div className="flex items-center justify-between pb-3 border-b border-[#30363d]">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" />
                <h2 className="text-sm font-semibold text-white">
                  FastAPI Backend Liveness
                </h2>
              </div>
              <span className="text-[10px] font-mono text-[#8b949e]">
                GET /health
              </span>
            </div>

            <div className="mt-4 flex-1 flex flex-col justify-between">
              {health ? (
                <div className="space-y-3 font-mono text-xs">
                  <div className="flex items-center justify-between py-1 border-b border-[#21262d]">
                    <span className="text-[#8b949e]">Status:</span>
                    <span className="text-emerald-400 font-bold flex items-center gap-1">
                      <CheckCircle2 className="w-3.5 h-3.5" /> {health.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#21262d]">
                    <span className="text-[#8b949e]">Service:</span>
                    <span className="text-white">{health.app} v{health.version}</span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#21262d]">
                    <span className="text-[#8b949e]">Timezone:</span>
                    <span className="text-blue-300">{health.timezone_display}</span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#21262d]">
                    <span className="text-[#8b949e]">Server Time:</span>
                    <span className="text-[#8b949e]">{new Date(health.timestamp).toLocaleTimeString()} IST</span>
                  </div>
                  <div className="flex items-center justify-between py-1">
                    <span className="text-[#8b949e]">DB Probe:</span>
                    <span className={health.supabase_connected ? "text-emerald-400" : "text-amber-400"}>
                      {health.details || (health.supabase_connected ? "Connected" : "Pending")}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="h-32 flex items-center justify-center text-xs text-[#8b949e]">
                  {loading ? "Checking backend health..." : "No data available"}
                </div>
              )}
            </div>
          </div>

          {/* Card 2: Supabase Hello-World Database Read */}
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5 flex flex-col">
            <div className="flex items-center justify-between pb-3 border-b border-[#30363d]">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-emerald-400" />
                <h2 className="text-sm font-semibold text-white">
                  Supabase Read Verification
                </h2>
              </div>
              <span className="text-[10px] font-mono text-[#8b949e]">
                GET /api/v1/hello
              </span>
            </div>

            <div className="mt-4 flex-1 flex flex-col justify-between">
              {hello ? (
                <div className="space-y-3 font-mono text-xs">
                  <div className="flex items-center justify-between py-1 border-b border-[#21262d]">
                    <span className="text-[#8b949e]">Verification Result:</span>
                    <span
                      className={`font-semibold px-2 py-0.5 rounded text-[11px] ${
                        hello.verification_status === "PASS"
                          ? "bg-emerald-950/60 text-emerald-300 border border-emerald-800/60"
                          : hello.verification_status === "BLOCKED"
                          ? "bg-amber-950/60 text-amber-300 border border-amber-800/60"
                          : "bg-red-950/60 text-red-300 border border-red-800/60"
                      }`}
                    >
                      {hello.verification_status || "PENDING"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between py-1 border-b border-[#21262d]">
                    <span className="text-[#8b949e]">Data Source:</span>
                    <span className="text-blue-300">{hello.data_source}</span>
                  </div>
                  <div className="py-2">
                    <span className="text-[#8b949e] block mb-1">
                      {hello.verification_status === "PASS" ? "Returned Database Record:" : "Endpoint Message:"}
                    </span>
                    {hello.read_row ? (
                      <pre className="p-3 bg-[#0d1117] border border-[#30363d] rounded text-[11px] overflow-x-auto text-emerald-300">
                        {JSON.stringify(hello.read_row, null, 2)}
                      </pre>
                    ) : (
                      <div className="p-3 bg-[#0d1117] border border-[#30363d] rounded text-[11px] text-amber-300/90 leading-relaxed">
                        {hello.message}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="h-32 flex items-center justify-center text-xs text-[#8b949e]">
                  {loading ? "Reading from Supabase..." : "No data available"}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Phase 0 Acceptance Criteria Checklist */}
        <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-5">
          <div className="flex items-center gap-2 pb-3 border-b border-[#30363d]">
            <ShieldCheck className="w-4 h-4 text-purple-400" />
            <h2 className="text-sm font-semibold text-white">
              Phase 0 Infrastructure Verification Summary
            </h2>
          </div>

          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 text-xs">
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Project Layout & Branch</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Python 3.12 / uv Tooling</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>4 Open-Meteo Models & Runs</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>IMD 08:30 IST & imdlib</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>FastAPI /health Endpoint</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Supabase / PostGIS Schema</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Render Deployment Config</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>Vercel Frontend Config</span>
            </div>
            <div className="p-2.5 bg-[#21262d] border border-[#30363d] rounded flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
              <span>UI Skills (Impeccable/Taste)</span>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-[#30363d] bg-[#161b22] px-6 py-4 text-center text-xs text-[#8b949e]">
        <p>
          AAGAM (Adaptive AI-Grid Assimilation Model) · Smart India Hackathon 2026 · Problem Statement 26081
        </p>
        <p className="mt-1 text-[11px] text-[#484f58]">
          Weather data provided under CC BY 4.0 (Open-Meteo, ECMWF, NOAA, DWD, IMD). Built with FastAPI, Supabase, React, Vite.
        </p>
      </footer>
    </div>
  );
}

export default App;
