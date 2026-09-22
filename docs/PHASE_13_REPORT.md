# AAGAM — Phase 13 Report: Climatology + Local Extremeness

**Project:** AAGAM (Adaptive AI-Grid Assimilation Model)  
**SIH 2026 Problem Statement:** PS 26081 (MoES / NCMRWF)  
**Phase:** Phase 13 — Climatology + Local Extremeness (Feature G & heavy_rain_3day)  
**Branch:** `phase-13/climatology`  
**Base Commit SHA:** `7dc05eec1e92d2e429cbfe06a7244f4d33211189`  
**Final Commit SHA:** `f43824e2df5e92995c680bd0dc8cf869714d39d9`  
**Repository Main SHA:** `66b09b693e9ece968dcb3be412979705507967b0` (Unmodified)  
**Date:** September 22, 2026  

---

## 1. Executive Summary

Phase 13 implements station-level empirical climatology percentiles and local extremeness evaluation per `AAGAM_PRD.md` (§6.11, §8.4, §10.4, §11, §11.2, §12) and `AAGAM_UPGRADE_PACK.md` v1.1:
1. **Climatology Percentiles Data Model (`climatology_percentiles`)**: Database migration and table storing historical empirical distributions by station `location_id`, `variable` (`rain_mm`, `tmax_c`, `wind_max_kmh`), `metric` (`1day`, `3day_sum`), and day-of-year window (`doy_window` 1..366, $\pm 7$ days circular).
2. **Circular Day-of-Year Window**: Full calendar boundary wrapping (e.g. DOY 1 window includes DOY 359..366 and 1..8; DOY 365 window includes DOY 358..366 and 1..6) using `min(|d1 - d2|, 366 - |d1 - d2|) <= 7`.
3. **Strict Minimum History Safeguard ($n\_years \ge 15$)**: When qualified history is $< 15$ years, the system suppresses all percentile calculations and local extremeness outputs. It produces `None` rather than fabricating or extrapolating unsupported values.
4. **Local Extremeness & Rarity Context (Feature G)**: Categorizes event rarity against station climatology:
   - Value $\ge p99$: `"roughly a 1-in-100 event"`
   - Value $\ge p95$: `"roughly a 1-in-20 event"`
   - Value $\ge p90$: `"roughly a 1-in-10 event"`
   - Value $< p90$ or $n\_years < 15$: `None` (suppressed)
5. **New Hazard: `heavy_rain_3day`**: Evaluates rolling 3-day accumulated rainfall across the 7-day forecast horizon (up to 5 overlapping windows). Classified dynamically against local 3-day sum percentiles ($p90 \to \text{Advisory}$, $p95 \to \text{Watch}$, $p99 \to \text{Alert}$).
6. **Backfill & Annual Refresh Pipeline**: Idempotent batch pipeline in `pipeline/climatology/backfill.py` using `ON CONFLICT (location_id, variable, metric, doy_window) DO UPDATE`, exposed via CLI `python -m pipeline climatology-backfill` and scheduled annual workflow `.github/workflows/climatology-backfill.yml`.
7. **Public Context & Frontend Integration**:
   - Section 3 ("How unusual — Feature G") rendered in `AlertEventDetailDrawer.tsx` and public share page `PublicEventSharePage.tsx` with a verified 15+ year baseline badge.
   - `AlertCard.tsx` renders local rarity chip and `mm (3-day)` units.
   - `ExtremeWeatherPage.tsx` filter includes `3-Day Heavy Rain (≥ p90)`.

---

## 2. Deliverables & Technical Architecture

### 2.1 Database Schema & Migration
- **Migration File:** `supabase/migrations/20260922000006_phase13_climatology.sql`
- **Table Definition:**
  ```sql
  CREATE TABLE IF NOT EXISTS climatology_percentiles (
      location_id INT NOT NULL REFERENCES locations(id),
      variable    TEXT NOT NULL CHECK (variable IN ('rain_mm', 'tmax_c', 'wind_max_kmh')),
      metric      TEXT NOT NULL CHECK (metric IN ('1day', '3day_sum')),
      doy_window  SMALLINT NOT NULL CHECK (doy_window BETWEEN 1 AND 366),
      mean        REAL,
      p90         REAL,
      p95         REAL,
      p99         REAL,
      n_years     SMALLINT NOT NULL,
      computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      PRIMARY KEY (location_id, variable, metric, doy_window)
  );
  ```
- **Security & RLS:** Public read policy `allow_read_climatology_percentiles` enabled (`FOR SELECT TO anon, authenticated USING (true)`).
- **Table Registry:** Integrated into `pipeline/db/setup_tables.py` for automated schema sync.

### 2.2 Climatology Engine (`pipeline/climatology/`)
- `pipeline/climatology/percentiles.py`:
  - `is_doy_in_window(obs_doy, center_doy, window_days=7)`: Circular day-of-year distance with leap year and year-boundary wrapping.
  - `compute_3day_rainfall_sums(df, rain_col)`: Rolling 3-day sums across strictly consecutive calendar days.
  - `calculate_percentiles(values, n_years, min_years=15)`: Deterministic numpy percentiles with strict $n\_years < 15$ suppression returning `None`.
  - `get_rarity_label(val, p90, p95, p99, n_years)`: Local rarity mapping with strict suppression on insufficient history.
  - `compute_station_climatology(...)`: Prepares all 366 DOY window percentiles for a station and metric.

### 2.3 Extreme Weather Guidance Engine Integration
- `pipeline/blend/extremes.py`:
  - `load_climatology_percentiles_lookup(db_url)`: In-memory hash lookup for $(location\_id, variable, metric, doy)$ returning $p90, p95, p99, n\_years$.
  - Integrated local rarity evaluation into `evaluate_rain_hazard`, `evaluate_wind_hazard`, and `evaluate_heatwave_hazards_for_location`.
  - Implemented `evaluate_heavy_rain_3day_hazards_for_location(loc_df, meta, creation_time)`:
    - Assesses rolling 3-day rainfall sums across forecast leads 1..7 (windows: leads 1-3, 2-4, 3-5, 4-6, 5-7).
    - Thresholds: Advisory ($\ge p90$), Watch ($\ge p95$), Alert ($\ge p99$).
    - Strict safeguard: If climatology is missing or $n\_years < 15$, emits 0 alerts.
  - Integrated into `evaluate_all` and persisted `rarity_label` into `alerts` table in `pipeline/live/runner.py`.

### 2.4 Backfill Pipeline & Automation
- `pipeline/climatology/backfill.py`:
  - Loads truth observation parquet file or historical dataframe.
  - Computes `1day` and `3day_sum` percentiles across all active stations.
  - Performs idempotent upsert via `psycopg2.extras.execute_values` using `ON CONFLICT (location_id, variable, metric, doy_window) DO UPDATE`.
  - Supports `--dry-run` and station filtering `--stations 1,2`.
- CLI Command in `pipeline/cli.py`:
  ```bash
  python -m pipeline climatology-backfill [--stations ...] [--min-years 15] [--dry-run]
  ```
- Workflow: `.github/workflows/climatology-backfill.yml` with manual dispatch and annual schedule (`0 4 1 1 *`).

### 2.5 API Endpoints (`/api/v1`)
- `api/app/routers/climatology.py`:
  - `GET /api/v1/climatology`: Public read endpoint supporting query parameters `location_id`, `variable`, `metric`, `doy_window`, `date`. Returns `ClimatologyResponse` with `insufficient_history: bool` and array of `percentiles`.
- `api/app/routers/alerts.py`:
  - `GET /api/v1/alerts/events/{id}`: Lookups climatological percentiles for the event station/date/hazard and populates `rarity_label` and `rarity_context` in the response envelope.

### 2.6 Frontend Experience
- `web/src/api/types.ts`: Added `rarity_label` and `rarity_context` to `AlertItem` and `AlertEventDetailResponse`, added `ClimatologyPercentileItem` and `ClimatologyResponse`.
- `web/src/components/alerts/AlertEventDetailDrawer.tsx` & `web/src/pages/PublicEventSharePage.tsx`:
  - Section 3: "How unusual (Feature G)" displaying local rarity badge, exact historical percentile context, and a green badge indicating a 15+ year observation baseline.
  - Clean suppression when no climatology or insufficient history exists.
- `web/src/components/alerts/AlertCard.tsx`:
  - Renders purple rarity badge directly on alert card when present.
  - Formats unit as `mm (3-day)` for `heavy_rain_3day` alerts.
- `web/src/pages/ExtremeWeatherPage.tsx`:
  - Added option `<option value="heavy_rain_3day">3-Day Heavy Rain (≥ p90)</option>`.

---

## 3. Spot-Check Acceptance Test Evidence

The 7-point spot-check acceptance test (`tests/test_phase13_acceptance.py`) was executed against controlled seeded historical data:

| # | Acceptance Requirement | Test Implementation | Observed Test Value / Behavior | Status |
|---|------------------------|---------------------|--------------------------------|--------|
| 1 | Qualifying history ($\ge 15$ years) | Station 1 (20 years: 2005–2024) | Generated 366 DOY rows with $n\_years = 20$ | **PASS** |
| 2 | $p90/p95/p99$ populated correctly | Station 1 DOY 190 (mid-monsoon) | $p90 = 49.0\text{ mm}, p95 = 52.0\text{ mm}, p99 = 54.0\text{ mm}$ (monotonic: $p90 \le p95 \le p99$) | **PASS** |
| 3 | DOY $\pm 7$ window applied correctly | Circular wrapping test (DOY 1 & 365) | DOY 1 matches Dec 25..31 (359..366) and Jan 1..8; DOY 365 matches Dec 24..31 and Jan 1..6 | **PASS** |
| 4 | 3-day rainfall climatology for `heavy_rain_3day` | Station 1 `3day_sum` computation | DOY 190 $p90 = 147.0\text{ mm}, p95 = 153.0\text{ mm}, p99 = 159.0\text{ mm}$ | **PASS** |
| 5 | Insufficient history ($< 15$ years) suppression | Station 2 (10 years: 2015–2024) | $p90 = \text{None}, p95 = \text{None}, p99 = \text{None}$; `get_rarity_label` returned `None`; ExtremeGuidanceEngine emitted 0 alerts | **PASS** |
| 6 | No hardcoded percentile values in production | AST / regex scan across pipeline & api | Zero constant assignments to $p90/p95/p99$ in production code | **PASS** |
| 7 | Event continuity & status preserved | Phase 10 status invariant check | `status` remains strictly in `('active', 'expired', 'cancelled')` | **PASS** |

---

## 4. Test Suite & Regression Verification

### 4.1 Phase 13 Focused Tests (24 Passed)
- `tests/test_phase13_climatology.py`: 11 tests (DOY circular window, year boundaries, rolling 3-day sums, percentile math, rarity mapping, station climatology).
- `tests/test_phase13_heavy_rain_3day.py`: 3 tests (advisory/watch/alert threshold crossings, insufficient history suppression, missing climatology suppression).
- `tests/test_phase13_acceptance.py`: 7 tests (7-point acceptance spot-check, public API endpoint, schema validation).
- `tests/test_phase13_backfill.py`: 3 tests (idempotent SQL execution, dry run calculation, empty dataset handling).

### 4.2 Full Repository Regression (276 Passed)
```
pytest -q:
........................................................................ [ 26%]
........................................................................ [ 52%]
........................................................................ [ 78%]
............................................................             [100%]
276 passed, 2 warnings in 57.8s
```

### 4.3 Linters & Frontend Build
- `ruff check .`: All checks passed with 0 errors.
- `web`: `npm run lint` (oxlint) passed with 0 errors.
- `web`: `npm run build` (tsc + vite build) completed with 0 errors.

---

## 5. Repository Integrity Verification

- **Repository `main` Commit SHA:** `66b09b693e9ece968dcb3be412979705507967b0` (Untouched)
- **Ingest & Blend Cadence:** `17 0,6,12,18 * * *` preserved in `.github/workflows/ingest-blend.yml`
- **Daily Summary Cadence:** `30 1 * * *` preserved in `.github/workflows/notify-daily-summary.yml`
- **DrishtiScan Status:** 0 modifications (`git status --porcelain DrishtiScan` empty)
- **Phase Continuity:** Phase 9 (ingest/blend), Phase 10 (event continuity & lifecycle), Phase 11 (notifications), Phase 12 (trust & context) verified 100% intact.
- **Security Audit:** Zero secrets committed; public read model preserved; client bundle contains zero service-role keys.

---

## 6. Conclusion

Phase 13 (Climatology + Local Extremeness) is fully implemented, verified, and ready for freeze.
No Phase 14 work has been initiated.
