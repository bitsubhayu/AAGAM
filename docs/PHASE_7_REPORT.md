# AAGAM — Phase 7 Implementation Report: Web Frontend & Workstation

**Project:** Adaptive AI-Grid Assimilation Model (AAGAM)  
**Problem Statement:** MoES / NCMRWF — SIH 2026 PS 26081  
**Branch:** `phase-7/frontend`  
**Base Commit:** `debd511ca6ba4a9350be4f04b26fd7424f7bd3a3` (Phase 6 Frozen Head)  
**Date:** September 21, 2026  
**Status:** **Phase 7 Implementation & Frontend Verification Complete.**

---

## Executive Summary

Phase 7 delivers the complete, operational web frontend workstation for AAGAM according to `AAGAM_PRD.md` (§10 UI/UX specification, §12 API contracts, §13 non-functional requirements), `AAGAM_TECH_STACK.md` §9, `DESIGN.md`, and `PRODUCT.md`.

The workstation is built using **React 19**, **TypeScript**, **Vite**, **Tailwind CSS**, **shadcn/ui design patterns**, **Apache ECharts** (`echarts-for-react`), **Leaflet** (`react-leaflet`), **TanStack Query v5**, **Zustand v5**, **Sonner**, **Motion**, and **Supabase JS**.

All required screens, components, and interactive data workflows consume real data from the frozen Phase 6 FastAPI backend at `/api/v1`. The service-role key is strictly excluded from client-side code, and standard Supabase JWT authorization with RBAC (`viewer`, `forecaster`, `admin`) is enforced.

---

## 1. Frontend Architecture & Technology Stack

| Capability | Library / Tool | Implementation Detail |
|---|---|---|
| **App Shell & Bundler** | Vite 8 + React 19 + TypeScript | Path alias `@/*` configured for clean modular imports; sub-second HMR. |
| **Styling & Tokens** | Tailwind CSS + CSS Variables | Dark technical workstation theme (`#0d1117` base, `#161b22` cards, `#21262d` inputs, `#30363d` borders). |
| **Typography** | `@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-mono` | Self-hosted fonts; tabular numerals enabled for numerical alignment across tables and charts. |
| **State Management** | Zustand | `authStore.ts` (session, JWT, role, demo persona) and `uiStore.ts` (variable, lead day, location, drawer). |
| **Data Fetching & Cache** | TanStack Query v5 | Automatic query deduplication, short-lived cache TTLs (60s forecasts, 300s metadata/weights), and automatic mutation invalidation. |
| **Spatial Map** | Leaflet + React-Leaflet | 40 synoptic stations rendered on Carto Dark matter basemap with graduated hazard circles and station inspection popups. |
| **Meteorological Charts** | Apache ECharts | Multi-model evolution (GFS, IFS, ICON, AIFS), thick blended series, uncertainty envelopes, IMD thresholds, and 5x7 weight heatmaps. |
| **Toasts & Notifications** | Sonner | Rich dark-themed transient toast feedback for overrides, alert acknowledgements, and exports. |
| **Markdown Display** | `react-markdown` | Renders formatted meteorological assistant briefings in the slide-out drawer. |
| **Authentication** | `@supabase/supabase-js` | Standard public anon key authentication + Dual-mode Quick Role Switcher for judging and evaluation. |

---

## 2. Screens & Functional Coverage (PRD §10.4)

### 1. Overview Dashboard (`FR-UI-1`)
- **KPI Row:** Active hazard alerts count, weekly dominant model, blend skill gain vs equal-mean baseline, and model version freshness badge.
- **Main Map:** Interactive Leaflet India map showing 40 synoptic representative locations with graduated hazard circles (Rainfall, Max Temp, Wind). Clicking any point opens a station inspection summary with an "Open in Explorer" direct action.
- **Side Panel:** Top active weather alerts list with quick action to the Extreme Weather Center and 90-day verification skill trends.
- **Status Banners:** Stale data advisory banner (triggers if data > 9h old) and waking-up cold-start resume indicator.

### 2. Forecast Explorer (`FR-UI-2`)
- **Station Search & Picker:** Filter across 40 representative locations by city name, state, or agro-climatic region.
- **Interactive Controls:** Toggle multi-model series (GFS, ECMWF IFS, DWD ICON, ECMWF AIFS, AAGAM Blend), toggle uncertainty spread envelope (min–max range), and toggle IMD threshold lines (e.g. 64.5 mm heavy rain, 40°C heatwave, 62 km/h gale).
- **ECharts Timeline Chart:** Multi-model curves from Day+0 to Day+7 with exact hover tooltips and IST valid dates.
- **Exact Numerical Table:** Complete tabular matrix with model values, model spread ($\sigma$), threshold exceedance count, and one-click "Copy CSV" functionality.
- **Assistant Integration:** "Ask AAGAM" button directly launches the Assistant Drawer with prefilled location and lead-time context.

### 3. Weight Maps & Forecaster Overrides (`FR-UI-3`)
- **Heatmap View:** Interactive 5 regions (NW, Central, East/NE, South, Himalayan) × 7 lead days (D+1 to D+7) matrix. Cell hue represents dominant model, while saturation indicates dominance margin.
- **Cell Detail Inspector:** Clicking any cell displays a comprehensive breakdown: 4 model weight progress bars, verification sample count ($n$), low-sample warning if $n < 30$, and fallback tier applied.
- **Dominant Model Spatial Grid:** Spatial Leaflet view showing dominant model per station with full 4-model percentage distribution popups.
- **Forecaster Override Modal (`forecaster+` role):** 4 model sliders with live 100% renormalization, mandatory meteorological justification ($\ge 10$ characters), expiry selector, and active override audit trail.

### 4. Skill & Verification (`FR-UI-4`)
- **Error Evolution Curves:** MAE and RMSE across lead times (D+1 to D+7) for AAGAM Blend, GFS, ECMWF IFS, DWD ICON, ECMWF AIFS, and Equal-Mean Baseline.
- **Honesty Banner (PRD §2.1 G1):** Explicitly highlights any lead days where single models outperformed the blend on held-out test data.
- **Categorical Contingency Chart:** Probability of Detection (POD), False Alarm Ratio (FAR), and Critical Success Index (CSI) grouped bars evaluated at the IMD heavy rainfall threshold (64.5 mm/24h).
- **Exact Skill Matrix Table:** Tabular summary with MAE, RMSE, Bias, and CSI scores.

### 5. Extreme Weather Center (`FR-UI-5`)
- **Multi-Factor Hazard Encoding (WCAG 2.1 AA Non-Color Principle):** Every card displays an explicit icon (`CloudRain`, `Flame`, `Wind`, `AlertTriangle`), text severity label (`ADVISORY`, `WATCH`, `ALERT`), exact numerical value with units (`mm/24h`, `°C`, `km/h`), and multi-model agreement chip (e.g. "3/4 models exceed threshold").
- **Why Flagged Diagnostic Modal:** Displays exact decision rule text, model exceedance count, spread ($\sigma$), and IMD threshold criteria.
- **Acknowledge Action (`forecaster+`):** Role-gated acknowledgement action with optimistic cache updates and Sonner toast confirmations.

### 6. Pipeline Health & Telemetry (`FR-UI-8`)
- **Telemetry KPIs:** Active model version ID (`v2`), pipeline success rate (100%), estimated daily API calls vs cap (~640 / 10,000, 6.4%), and database transaction pooler status.
- **Execution Log Table:** Telemetry table recording job name, status, start time (IST), rows written, API call estimates, and error messages.
- **Admin Model Rollback Modal (`admin` only):** 1-click model activation and rollback calling `POST /api/v1/models/{id}/activate` with automatic cache invalidation.

### 7. Scientific Data Exporter (`FR-UI-7`)
- **Dataset Picker:** `forecasts`, `alerts`, `weights`, `skill`.
- **Format:** CSV or JSON streaming export.
- **Direct Download:** Triggers `/api/v1/export` streaming endpoint.
- **Developer Code Box:** Copyable cURL and Python code snippets for researchers.

### 8. Settings & Attribution (`FR-UI-9`)
- **Operator Context:** Displays active user role (`viewer`, `forecaster`, `admin`), organization, and permissions.
- **Timezone Notice:** Standardizes on Indian Standard Time (`Asia/Kolkata` · UTC+05:30) and 08:30 IST 24-hour rainfall accumulation windows.
- **Attribution & Licensing:** Full attribution for Open-Meteo (CC BY 4.0) and India Meteorological Department (Pai et al. gridded rainfall).

### 9. AAGAM Assistant Drawer (`FR-UI-6`)
- **Slide-out Drawer:** Available globally across all screens.
- **Mode Chips:** Explain / Raw / Both.
- **Streaming Renderer:** Connects to `/api/v1/chat` SSE stream and renders with `react-markdown`.
- **Phase 8 Boundary:** Provides full UI scaffolding and prompt starters; Groq tool-use agent loop remains isolated for Phase 8.

---

## 3. Role-Based Access Control (RBAC) Matrix

| Action | Viewer | Forecaster | Admin | UI Behavior |
|---|:-:|:-:|:-:|---|
| View Dashboards, Maps & Charts | ✔ | ✔ | ✔ | Available to all |
| Export CSV / JSON Data | ✔ | ✔ | ✔ | Available to all |
| Acknowledge Hazard Alerts | – | ✔ | ✔ | Enabled for Forecaster+; labeled "Viewer (Read)" and disabled for Viewer |
| Create Audited Weight Overrides | – | ✔ | ✔ | Enabled for Forecaster+; labeled "Forecaster Only" and disabled for Viewer |
| Activate / Rollback Model Version | – | – | ✔ | Enabled for Admin only; labeled "Admin Only (Rollback)" and disabled for others |

A **Quick Role Switcher** is accessible in the top header, allowing instant switching between Dr. Meera (NCMRWF Forecaster), Mr. Rao (Disaster Officer / Viewer), and System Admin to evaluate RBAC restrictions seamlessly.

---

## 4. Verification & Static Analysis Results

### A. TypeScript & Frontend Build
```powershell
npm run build
```
- **Result:** `tsc -b && vite build` exited with code `0`.
- **Artifacts:** Built clean production bundle in `dist/` (assets transformed in 1.55s).

### B. Frontend Linter (`oxlint`)
```powershell
npm run lint
```
- **Result:** `Found 0 warnings and 0 errors.` Finished in 28ms on 49 files.

### C. Backend Test Suite (`pytest`)
```powershell
.venv\Scripts\pytest.exe
```
- **Result:** `118 passed, 0 failures, 0 skipped, 9 warnings in 68.38s`.
- **Contracts:** All Phase 6 API contracts preserved with 100% fidelity.

### D. Code Quality (`ruff`)
```powershell
.venv\Scripts\ruff.exe check .
```
- **Result:** `All checks passed! 0 lint errors.`

### E. Security Verification
- Service-role key is **never** referenced or included in frontend client code.
- `.env` and `.env.*` are excluded via `.gitignore`.
- No mock or fake weather data introduced into production paths.

---

## 5. Git Isolation & Safety Confirmation

- **Current Branch:** `phase-7/frontend`
- **Starting Commit:** `debd511ca6ba4a9350be4f04b26fd7424f7bd3a3`
- **Target `main` Branch:** Untouched at `66b09b6`.
- **Phase 5:** Remains frozen with 3-cycle operational acceptance deferred.
- **Phase 8:** Completely untouched (no Groq assistant agent or tool loops implemented).
