# AAGAM — Adaptive AI-Grid Assimilation Model

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.3-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178C6.svg)](https://www.typescriptlang.org/)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL%2015-3ECF8E.svg)](https://supabase.com/)
[![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-F55036.svg)](https://groq.com/)
[![Tests](https://img.shields.io/badge/Tests-182%20Passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Smart India Hackathon 2026 — Problem Statement 26081**  
> **Ministry of Earth Sciences (MoES) / National Centre for Medium Range Weather Forecasting (NCMRWF)**  
> *Hybrid AI–NWP Multi-Model Forecast Blending & Real-Time Operational Assimilation System*

---

## 1. Executive Summary

Global Numerical Weather Prediction (NWP) models (NOAA GFS, ECMWF IFS, DWD ICON) and next-generation AI models (ECMWF AIFS) frequently produce conflicting regional forecasts across the diverse agro-climatic zones of India. A single model often underperforms due to seasonal biases, complex topography, or poor convective parameterization.

**AAGAM (Adaptive AI-Grid Assimilation Model)** solves this by providing:
- **Hierarchical AI Stacking:** Dynamically combines ECMWF IFS, NOAA GFS, DWD ICON, and ECMWF AIFS using regularized Ridge Regression and LightGBM models conditioned on region, climate season, and 1–7 day lead times.
- **Uncertainty & Spread Estimation:** Computes ensemble standard deviation (`spread`) and consensus metrics (`models_over_threshold`) to provide confidence bounds for forecasters.
- **IMD-Compliant Alert Engine:** Automated color-coded threshold exceedance alerts (Green, Yellow, Orange, Red) for extreme precipitation ($\ge 64.5$ mm), heatwaves ($\ge 40^\circ\text{C}$), and severe wind gusts.
- **Grounded AI Assistant:** Powered by Groq's low-latency LPUs running `llama-3.3-70b-versatile`, equipped with 6 deterministic backend inspection tools and a deterministic Number Guard to eliminate hallucinations.
- **Enterprise High Availability:** Sub-500ms API reads, zero-downtime model rollback (330 ms), automated nightly Parquet disaster recovery backups, and graceful 4-level fallback degradation.

---

## 2. Five-Minute Quickstart

### Prerequisites
- **Python:** 3.12+ (managed with `uv` or standard `venv`)
- **Node.js:** 18+ and `npm`
- **PostgreSQL / Supabase:** PostgreSQL 15+ database credentials
- **Groq Cloud API Key:** (for the AI Assistant)

### Step 1: Clone Repository
```bash
git clone https://github.com/bitsubhayu/AAGAM.git
cd AAGAM
```

### Step 2: Configure Environment Variables
Create a root `.env` file from the provided template:
```bash
cp .env.example .env
```
Ensure the following core variables are configured:
```ini
# Supabase PostgreSQL Database (Transaction Pooler port 6543)
DATABASE_URL="postgresql://postgres.xxx:password@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require"
SUPABASE_URL="https://xxx.supabase.co"
SUPABASE_ANON_KEY="eyJhbG..."
SUPABASE_SERVICE_ROLE_KEY="eyJhbG..."

# AI Assistant (Groq Cloud)
GROQ_API_KEY="gsk_..."

# Application Settings
API_V1_STR="/api/v1"
ENVIRONMENT="development"
```

### Step 3: Set Up Python Backend
```powershell
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate   # Windows PowerShell
# source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Run database schema migration (if starting with a clean DB)
# psql $DATABASE_URL -f supabase/migrations/20260921000003_phase5_schema_and_rls.sql
```

### Step 4: Launch FastAPI Server
```powershell
uvicorn api.app.main:app --host 127.0.0.1 --port 8000 --reload
```
*The interactive OpenAPI documentation is now accessible at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).*

### Step 5: Launch Vite Frontend
Open a separate terminal:
```bash
cd web
npm install
npm run dev
```
*The interactive weather operations dashboard will open at [http://localhost:5173](http://localhost:5173).*

---

## 3. High-Level Architecture

```
                       ┌───────────────────────────────────────────────┐
                       │             External Ingestion Feeds          │
                       │   Open-Meteo API | IMD Gridded | ECMWF ERA5   │
                       └───────────────────────┬───────────────────────┘
                                               │
                                               ▼
                       ┌───────────────────────────────────────────────┐
                       │     Data Processing & ML Stacking Pipeline    │
                       │   • Extreme Clamping & Anomaly Filtering      │
                       │   • Hierarchical Ridge & LightGBM Blending    │
                       │   • Dynamic 4-Tier Fallback Hierarchy         │
                       └───────────────────────┬───────────────────────┘
                                               │
                                               ▼
                       ┌───────────────────────────────────────────────┐
                       │      Storage & Persistence (Supabase Cloud)   │
                       │   • PostgreSQL 15 + Row Level Security (RLS)  │
                       │   • PgBouncer (statement_cache_size=0)        │
                       │   • Storage: training-data | models | backups │
                       └───────────────────────┬───────────────────────┘
                                               │
                                               ▼
                       ┌───────────────────────────────────────────────┐
                       │             FastAPI Backend (/api/v1)         │
                       │   • Sub-500ms Warm Read Latency               │
                       │   • Supabase JWT Authentication & RBAC        │
                       │   • SlowAPI Rate Limiting & Strict Envelope   │
                       └───────────────┬───────────────┬───────────────┘
                                       │               │
                     ┌─────────────────┘               └─────────────────┐
                     ▼                                                   ▼
       ┌───────────────────────────┐                       ┌───────────────────────────┐
       │   Groq AI Assistant Tier  │                       │   Vite + React Dashboard  │
       │ • Llama-3.3-70b-versatile │                       │ • Leaflet 40 Stations Map │
       │ • 6 Deterministic Tools   │                       │ • Lead Degradation Curves │
       │ • Deterministic Number Gd │                       │ • Interactive Alerts View │
       │ • SSE Streaming Protocol  │                       │ • Stale Data Banner (>9h) │
       └───────────────────────────┘                       └───────────────────────────┘
```

For detailed architectural diagrams, data flows, and security models, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## 4. Key Capabilities & Endpoints

| Category | Endpoint | Method | Role | Description |
|---|---|---|---|---|
| **Health** | `/api/v1/health` | `GET` | `anon` | Database connectivity probe and service status. |
| **Metadata** | `/api/v1/meta` | `GET` | `anon` | 40 synoptic locations, regions, active model version, last pipeline cycle. |
| **Forecast** | `/api/v1/forecast` | `GET` | `anon` | 1–7 day blended forecast, individual NWP models, and ensemble spread. |
| **Map Layer** | `/api/v1/map` | `GET` | `anon` | Geospatial payload for 40 stations filtered by date and variable. |
| **Alerts** | `/api/v1/alerts` | `GET` | `anon` | Active extreme weather alerts (rain, heat, wind) with severity levels. |
| **Skill Scores** | `/api/v1/skill` | `GET` | `anon` | Verification metrics (MAE, RMSE, Bias, POD, FAR, CSI) across lead days. |
| **Weights** | `/api/v1/weights` | `GET` | `anon` | Region and season-specific weights for GFS, IFS, ICON, and AIFS. |
| **History** | `/api/v1/history` | `GET` | `anon` | Time-series historical observations and past model performance. |
| **Pipeline** | `/api/v1/pipeline/status`| `GET` | `anon` | Execution logs, row counts, and status of automated cron cycles. |
| **Models** | `/api/v1/models/{id}/activate` | `POST` | `admin` | Zero-downtime atomic model version activation and instant rollback. |
| **Assistant** | `/api/v1/assistant/chat` | `POST` | `anon` | Streaming SSE endpoint for AI meteorologist tool orchestration. |
| **Export** | `/api/v1/export` | `GET` | `anon` | CSV/Parquet telemetry and forecast data export. |

---

## 5. Verification & Testing

AAGAM enforces rigorous test coverage across pipelines, ML algorithms, API security, and agent tools.

```powershell
# Run the complete Python test suite (182+ tests)
.venv\Scripts\pytest.exe -v

# Run Python linter & code style checks
.venv\Scripts\ruff.exe check .

# Run Frontend linter (Oxlint / ESLint)
cd web && npm run lint

# Run Frontend production build verification
npm run build
```

### Operational Drills
```powershell
# Execute Disaster Recovery Backup Restoration Drill
.venv\Scripts\python.exe scripts/drill_backup_restore.py

# Execute Zero-Downtime Model Rollback Drill
.venv\Scripts\python.exe scripts/drill_model_rollback.py
```

---

## 6. Data Sources & Attribution

AAGAM gratefully acknowledges and attributes the following meteorological and scientific data providers:
1. **Open-Meteo Seamless API:** Open-access meteorological API providing interpolated point forecasts for ECMWF IFS, NOAA GFS, DWD ICON, and ECMWF AIFS under Creative Commons Attribution 4.0 International (CC BY 4.0).
2. **India Meteorological Department (IMD), Ministry of Earth Sciences:** Gridded daily rainfall (0.25° $\times$ 0.25°) and observational station climatology utilized for bias calibration and verification.
3. **European Centre for Medium-Range Weather Forecasts (ECMWF):** ERA5 atmospheric reanalysis data and AIFS experimental AI model guidance.

---

## 7. Operational Limitations & Disclaimers

- **Research & Demonstration Status:** AAGAM is developed as a competition prototype for SIH 2026. It is **NOT** an official warning bulletin or disaster declaration service. All emergency operations and public safety directives must refer directly to the [India Meteorological Department (IMD)](https://mausam.imd.gov.in).
- **Spatial Coverage:** Configured for 40 representative Indian synoptic stations rather than a continuous national grid.
- **Statistical Blending vs. Physical DA:** AAGAM performs post-processing statistical and machine learning multi-model assimilation; it does not solve physical atmospheric differential equations.
- **Free-Tier Hosting:** Deployed on Render and Supabase free-tier instances with documented cold starts ($~30\text{s}$) and developer API rate limits.

For exhaustive details, refer to [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

---

## 8. Team & Acknowledgements

Developed with precision for **Smart India Hackathon 2026**.  
*Repository:* [https://github.com/bitsubhayu/AAGAM](https://github.com/bitsubhayu/AAGAM)  
*Team:* Subhayu & Contributors  
*Problem Statement:* SIH 2026 PS 26081 (MoES / NCMRWF)

---

## 9. Roadmap / Future Work

### Future: a CAP-format alert feed
India's national alert system, NDMA's SACHET, is built on the Common Alerting Protocol (CAP), the international XML standard for exchanging public warnings between systems. AAGAM's alert-event structure (`alert_events`) already carries everything a CAP message needs: a stable id, a status (active/expired/cancelled), a severity, a location, and update/cancellation semantics via `lifecycle_state`.

A natural next step — not built in this version — is to publish AAGAM's alert events as an unofficial, draft CAP feed at a public URL. This would not connect to SACHET directly (that requires approval from NDMA/DoT), but it demonstrates a credible integration path: any state control room or downstream system that already consumes CAP feeds could, in principle, pick up AAGAM's alerts the same way it picks up alerts from IMD, CWC, or other agencies.

