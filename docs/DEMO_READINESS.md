# AAGAM — Demo Environment Readiness & Pre-Flight Checklist

**Project:** Adaptive AI-Grid Assimilation Model (AAGAM)  
**Hackathon / Problem Statement:** Smart India Hackathon 2026 — PS 26081 (MoES / NCMRWF)  
**Document Type:** Live Demonstration Operational Runbook & Contingency Plan  
**Phase:** Phase 9 Hardening & Evaluation  

---

## 1. Pre-Flight Timing Timeline

```
T-60 min: Infrastructure Status Check (Supabase, Render, Groq)
T-30 min: Automated Warmup & Health Probe
T-15 min: Live Data & Freshness Banner Audit
T-05 min: Browser Tab Setup & Rehearsal Test Query
T-00 min: Pitch Presentation & Live Demonstration
```

---

## 2. Step-by-Step Pre-Flight Checklist

### Phase A: 60 Minutes Before Demo (T-60)
- [ ] **Supabase Cloud Project Unpause:**
  - Log into [Supabase Dashboard](https://supabase.com/dashboard).
  - Verify project `aagam-db` is green and not paused.
  - Test connectivity from terminal:
    ```powershell
    .venv\Scripts\python.exe -c "import psycopg2; from core.config import settings; conn = psycopg2.connect(settings.DATABASE_URL); print('Supabase Connected'); conn.close()"
    ```
- [ ] **Groq API Status & Quota:**
  - Verify `GROQ_API_KEY` is loaded.
  - Verify account is within daily developer tier quota (not rate-limited).
  - Quick test:
    ```powershell
    .venv\Scripts\python.exe -c "import os; from groq import Groq; client = Groq(api_key=os.environ.get('GROQ_API_KEY')); print('Groq OK:', client.models.list().data[0].id)"
    ```

### Phase B: 30 Minutes Before Demo (T-30) — Warmup
- [ ] **Render API Warmup (Mitigate Free-Tier Cold Start):**
  - Trigger health check endpoint to ensure container is awake:
    ```bash
    curl -I https://aagam-api.onrender.com/api/v1/health
    ```
  - Expect: HTTP 200 OK with `{"status":"ok","database":"connected"}`.
  - Run warmup pings for primary read endpoints:
    ```bash
    curl -s https://aagam-api.onrender.com/api/v1/meta > /dev/null
    curl -s https://aagam-api.onrender.com/api/v1/forecast?location_id=1&variable=rain_mm > /dev/null
    curl -s https://aagam-api.onrender.com/api/v1/map?variable=tmax_c > /dev/null
    ```
- [ ] **Frontend Vercel/Vite Warmup:**
  - Open the production frontend URL in Chrome.
  - Verify static assets load instantly and map renders 40 green/yellow/red station dots.

### Phase C: 15 Minutes Before Demo (T-15) — Data & Pipeline State
- [ ] **Active Model Version Verification:**
  - Verify active version in database:
    ```powershell
    .venv\Scripts\python.exe -c "import psycopg2; from core.config import settings; conn = psycopg2.connect(settings.DATABASE_URL); cur = conn.cursor(); cur.execute('SELECT id, storage_path, is_active FROM model_versions WHERE is_active = true'); print('Active version:', cur.fetchone()); conn.close()"
    ```
  - Expected: `(2, 'models/20260921/', True)`
- [ ] **Freshness Banner State:**
  - Check the timestamp of the last pipeline run:
    - If `started_at` is within 9 hours: Normal banner (`Live Operational Data`).
    - If `started_at` is $> 9$ hours: Amber advisory (`Stale Forecast Advisory: Data > 9H old`).
    - *Note:* If amber banner displays during demo, explain it as a live demonstration of AAGAM's automated operator warning system.

### Phase D: 5 Minutes Before Demo (T-05) — Browser Setup
- [ ] Open Chrome tabs in presentation order:
  1. **Tab 1:** Main Dashboard (`/` or `https://aagam.vercel.app`)
  2. **Tab 2:** Model Skill & Verification View (`/skill` or verification tab)
  3. **Tab 3:** AI Assistant Drawer (Ready with sample prompt chips)
  4. **Tab 4 (Backup):** Local dev server (`http://localhost:5173`)
- [ ] Execute one warm query in the Assistant drawer:
  - Query: `"What is the 3-day rainfall forecast for Mumbai?"`
  - Verify: Instant streaming response, tabular breakdown, citation link to IMD/Open-Meteo.

---

## 3. Disaster Recovery & Offline Fallback Plan

If cloud services experience external outages during the judging session (e.g., Render free tier spin-down, Wi-Fi latency, or Groq API 429), immediately switch to the zero-downtime local contingency environment:

### Local Execution Commands
1. **Start Local Backend (Terminal 1):**
   ```powershell
   cd C:\Users\subha\OneDrive\Documents\Antigravity_Workspace\AAGAM
   .venv\Scripts\activate
   uvicorn api.app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
2. **Start Local Frontend (Terminal 2):**
   ```powershell
   cd C:\Users\subha\OneDrive\Documents\Antigravity_Workspace\AAGAM\web
   npm run dev
   ```
   Navigate to: `http://localhost:5173`.

### Troubleshooting Matrix

| Symptom | Probable Cause | Instant Remediation Action |
|---|---|---|
| **API request hangs > 30s** | Render cold start | Switch to local backend tab (`http://localhost:8000/docs`). |
| **Assistant returns 429 alert** | Groq developer rate limit | Drawer shows built-in fallback advisory. Explain to judges: "Demonstrates graceful rate limit handling." |
| **Supabase pooler timeout** | WAN packet drop to AWS Mumbai | Rerun command or switch to local SQLite/Postgres cache. |
| **Map tiles don't load** | OpenStreetMap CDN blocked on Wi-Fi | Station markers still render on SVG Canvas layer. |
