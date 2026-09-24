# AAGAM — Phase 0 Setup & Environment Guide

**Adaptive AI-Grid Assimilation Model** · SIH 2026 · Problem Statement 26081 (MoES / NCMRWF)  
*Phase 0 Setup Documentation*

---

## 1. Machine & Environment Requirements

- **Operating System**: Windows / Linux / macOS (Tested on Windows 11 x64)
- **Python**: Python 3.12+ (Tested locally with Python 3.13.15)
- **Python Package Manager**: `uv` (Installed v0.12.17 in `.venv`)
- **Node.js**: Node.js v20+ (Tested with v24.13.3) and npm
- **Git**: Configured with remote `https://github.com/bitsubhayu/AAGAM.git`

---

## 2. Git & Branch Strategy

- **Default Branch**: `main`
- **Phase 0 Setup Branch**: `phase-0/setup`
- **Branch Creation**:
  ```bash
  git checkout -b phase-0/setup
  ```
- **Rules**:
  - Setup commits are made to `phase-0/setup`
  - Merging into `main` requires explicit review approval

---

## 3. Environment Variables Configuration

Copy `.env.example` to `.env` in the repository root:
```bash
cp .env.example .env
```

### Required Variables
| Variable | Description | Exposed to Frontend? |
|---|---|---|
| `SUPABASE_URL` | Supabase project API gateway | Yes (Public safe) |
| `SUPABASE_ANON_KEY` | Public anonymous JWT key | Yes (Public safe) |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side administrative key | **NO (Strict Secret)** |
| `DATABASE_URL` | Postgres pooler connection string (Port 6543) | **NO (Strict Secret)** |
| `GROQ_API_KEY` | Groq API Key (AAGAM Assistant) | **NO (Strict Secret)** |
| `GROQ_MODEL` | Default model (`openai/gpt-oss-120b`) | No |
| `GROQ_FALLBACK_MODEL` | Fallback model (`openai/gpt-oss-20b`) | No |
| `OPENMETEO_BASE_FORECAST` | `https://api.open-meteo.com/v1/forecast` | No |
| `OPENMETEO_BASE_HISTORICAL` | `https://archive-api.open-meteo.com/v1/archive` | No |
| `APP_TZ_DISPLAY` | `Asia/Kolkata` | Yes |
| `VITE_API_URL` | Backend URL for web client (dev: `http://localhost:8000`) | Yes |

---

## 4. Python & Virtual Environment Setup

1. **Create Virtual Environment**:
   ```bash
   python -m venv .venv
   ```
2. **Install `uv`**:
   ```bash
   .\.venv\Scripts\pip install uv
   ```
3. **Install Dependencies**:
   ```bash
   .\.venv\Scripts\uv pip install -r requirements.txt
   ```
4. **Run Unit Tests**:
   ```bash
   .\.venv\Scripts\pytest api/tests/
   ```
5. **Run Lint Check**:
   ```bash
   .\.venv\Scripts\ruff check .
   ```

---

## 5. Backend Service Setup (FastAPI)

1. **Start Local Server**:
   ```bash
   .\.venv\Scripts\uvicorn api.app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
2. **Verify Endpoints**:
   - `GET http://localhost:8000/health` (Returns liveness and database probe)
   - `GET http://localhost:8000/api/v1/hello` (Reads row from Supabase)
   - `GET http://localhost:8000/api/v1/meta` (Returns 40 locations and models)
   - `GET http://localhost:8000/docs` (Interactive Swagger UI)

---

## 6. Supabase & PostGIS Configuration

1. **Project Verification**:
   The user has already created the AAGAM Supabase project.
2. **Apply Phase 0 Migration**:
   Run `supabase/migrations/20260919000001_phase0_setup.sql` in the Supabase SQL Editor to enable PostGIS and create `_aagam_setup_check`.
3. **Connection Pooler Recommendation**:
   - Use **Transaction Pooler (Port 6543)** for backend API and GitHub Actions runners.
   - Use **Session Pooler (Port 5432)** for direct schema migrations.

---

## 7. Render Deployment Setup

1. **Repository Connection**:
   In Render Dashboard, connect GitHub repository `bitsubhayu/AAGAM` on branch `phase-0/setup` (or `main`).
2. **Configuration**:
   Render will automatically detect `render.yaml`:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn api.app.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/health`
3. **Environment Variables**:
   Configure in Render Web Service Dashboard (never commit):
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `DATABASE_URL`
   - `APP_TZ_DISPLAY=Asia/Kolkata`
   - `AUTH_REDIRECT_URL=https://<your-vercel-domain>.vercel.app` (e.g. `https://aagam-mlb8.vercel.app`)

---

## 8. Frontend Web Setup (React + Vite)

1. **Install Dependencies**:
   ```bash
   cd web
   npm install
   ```
2. **Start Development Server**:
   ```bash
   npm run dev
   ```
3. **Production Build Check**:
   ```bash
   npm run build
   ```

---

## 9. Vercel Deployment Setup

1. **Import Repository**:
   In Vercel Dashboard, import GitHub repository `bitsubhayu/AAGAM`.
2. **Root Directory**:
   Set Root Directory to `web/`.
3. **Build Settings**:
   - Framework Preset: `Vite`
   - Build Command: `npm run build`
   - Output Directory: `dist`
4. **Environment Variables**:
   Set `VITE_API_URL` to the Render backend service URL.

---

## 10. UI Skills Tooling

1. **Impeccable**:
   - Engine: v4.1.0 installed in `.github/skills/impeccable`.
   - Detector: Run `npx impeccable detect web/src/` to verify anti-pattern rules.
   - Initialized `PRODUCT.md`, `DESIGN.md`, `.impeccable/config.json`, `.impeccable/design.json`.
2. **Taste-Skill**:
   - Dials configured: `DESIGN_VARIANCE = 3`, `MOTION_INTENSITY = 3`, `VISUAL_DENSITY = 8`.
3. **Emil Kowalski Skills**:
   - Installed and available in `.agents/skills`.
