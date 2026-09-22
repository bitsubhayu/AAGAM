# AAGAM — Phase 12 Report: Trust + Context

**Project:** AAGAM (Adaptive AI-Grid Assimilation Model)  
**SIH 2026 Problem Statement:** PS 26081 (MoES / NCMRWF)  
**Phase:** Phase 12 — Trust + Context (Features A, C, F & Expired Event Verification)  
**Branch:** `phase-12/trust-context`  
**Base Commit SHA:** `9baaccc361390f15b0f9eacf08495da2714c4606`  
**Phase 10 Base SHA:** `3aec054cef50347c0213868e26d40fff00984e5d`  
**Repository Main SHA:** `66b09b693e9ece968dcb3be412979705507967b0` (Unmodified)  
**Date:** September 22, 2026  

---

## 1. Executive Summary

Phase 12 delivers the three core **Trust + Context** capabilities specified in `AAGAM_PRD.md` (§10.4, §10.5, §11.3, §12, §12.1, §12.2) and `AAGAM_UPGRADE_PACK.md` v1.1:
1. **Feature A — Track Record**: Trailing 180-day verification performance calculation evaluated dynamically per `(hazard, region, severity_peak)`. Excludes `high_uncertainty` model spread flags (`applicable: false`), guards against low-sample sizes ($n < 5$) with `low_sample: true` and plain-language warnings, and provides exact hit-rate metrics ($hits / (hits + false\_alarms)$).
2. **Feature C — "What this means" Guidance**: Static, team-authored editorial guidance in `config/hazard_guidance.yaml` covering all 4 hazards (`heavy_rain`, `heatwave`, `high_wind`, `heavy_rain_3day`) across all 3 severities (`advisory`, `watch`, `alert`). Includes clear plain-language descriptions, bulleted actionable precautions, and official IMD District Warning Portal (GIS) links. Strictly deterministic and not AI/LLM-generated.
3. **Feature F — Public Sharing**: Permanent event URLs (`/alerts/e/{id}` and `/alerts/events/{id}`) accessible to anyone without requiring login or a Supabase JWT. Server-generated `share_text` formatted strictly per PRD §10.4 template for 1-click WhatsApp sharing with official decision-support disclaimers.
4. **Expired Event Verification**: Verification outcome computation engine in `pipeline/events/verify.py` implementing PRD §12.2 truth evaluation (`hit`, `false_alarm`, `unverifiable`, `pending`). Verified expired events display their historical lifecycle and outcome without leaking any private subscriber data.

---

## 2. Deliverables & Technical Architecture

### 2.1 Feature C: Static Team-Authored Hazard Guidance
- **Configuration:** `config/hazard_guidance.yaml`
  - Defined 12 comprehensive hazard × severity editorial guides calibrated to official IMD warning thresholds and Beaufort scale wind standards.
  - Official IMD link: `https://mausam.imd.gov.in/responsive/districtWiseWarningGIS.php`.
- **Backend Service:** `api/app/services/hazard_guidance.py`
  - Function `get_hazard_guidance(hazard: str, severity: str)` loads and caches YAML configuration at startup.
  - Serves static, deterministic content into the `guidance` envelope of `GET /api/v1/alerts/events/{id}`.

### 2.2 Feature A: 180-Day Track Record Evaluation
- **Backend Service:** `api/app/services/track_record.py`
  - Function `fetch_track_record(conn, hazard, region, severity, window_days=180)` queries historical `alert_events` where `outcome IN ('hit', 'false_alarm')` over the trailing 180-day window (`start_date >= CURRENT_DATE - 180 days`).
  - Strict Rules Enforced:
    - `high_uncertainty` excluded: returns `applicable: false, note: "not applicable to this hazard type"`.
    - $n < 5$ low-sample guard: returns `low_sample: true` and note `"Not enough past alerts of this type yet to show a track record."`.
    - Valid sample ($n \ge 5$): returns `hit_rate = round(hits / n, 3)` and formatted summary text matching PRD §10.4: `f"Alerts like this one (same hazard, region, severity) have verified true {hits} of {n} times in the last 180 days"`.
    - Denominator $n = hits + false\_alarms$. Excludes `pending` and `unverifiable` outcomes.
    - Zero hardcoded production results.

### 2.3 Feature F: Public Sharing & Permanent Event URLs
- **Permanent URL:** `/alerts/e/{id}` and `/alerts/events/{id}`.
- **Server Share Text:** Generated in `GET /api/v1/alerts/events/{id}` following PRD §10.4:
  ```
  ⚠️ {severity_label} — {hazard_label} for {location_name}
  {valid_date_range}: {headline value} ({agreement})
  Details: {public_url}
  — via AAGAM (decision support, not an official IMD warning)
  ```
- **Public Share Page:** `web/src/pages/PublicEventSharePage.tsx`
  - Standalone, responsive public view.
  - Accessible without login / in incognito windows.
  - Presents decision support disclaimer, event summary, "What this means", track record, lifecycle timeline, and share action buttons.
  - Zero exposure of user subscriptions, emails, or operator tokens.
- **Client Routing:** `web/src/App.tsx` routes direct requests for `/alerts/e/:id` directly to `PublicEventSharePage`.

### 2.4 Expired Event Verification Engine
- **Module:** `pipeline/events/verify.py`
  - Implements PRD §12.2:
    - `hit`: Observed ground truth value on at least one day in event range crossed threshold.
    - `false_alarm`: Ground truth available for full range, but no day crossed threshold.
    - `unverifiable`: Truth missing for any day in range (never silently guessed or reinterpreted).
    - `pending`: `end_date` is in the future.
  - Updates `alert_events.outcome` and `alert_events.verified_at`.

---

## 3. API & Database Specifications

### 3.1 API Endpoints
| Endpoint | Method | Role | Description |
|---|---|---|---|
| `/api/v1/alerts/events/{id}` | GET | Public | Returns complete event details with `guidance`, `track_record`, and `share_text`. Accessible without JWT. |
| `/api/v1/alerts/track-record` | GET | Public | Queries trailing 180-day track record for arbitrary `(hazard, region, severity, window_days)`. |
| `/api/v1/alerts/events/{id}/ack` | POST | forecaster+ | Acknowledges active event. Gated to forecaster/admin. |

### 3.2 Database Schema
- Preserves Phase 10 migration `20260922000004_phase10_alert_events_and_public_rls.sql`.
- `alert_events` table retained indefinitely per PRD §11.5 to power the 180-day track record.
- `alert_events.status` constraint strictly preserved as `('active', 'expired', 'cancelled')`.
- Public RLS read access intact on `alert_events` and `alerts`.

---

## 4. Test Suite & Verification Results

### 4.1 Focused Phase 12 Tests
- `tests/test_phase12_guidance.py` (4 tests):
  - YAML syntax and structure validation.
  - Coverage for all 12 hazard × severity combinations.
  - Official IMD warning GIS portal URL presence.
  - Deterministic and static execution.
- `tests/test_phase12_track_record.py` (5 tests):
  - `high_uncertainty` exclusion (`applicable: false`).
  - Trailing 180-day window boundary filtering.
  - Low-sample ($n < 5$) warning and flag.
  - Correct hit rate calculation and PRD summary formatting.
  - Zero-sample edge cases.
- `tests/test_phase12_sharing.py` (4 tests):
  - Unauthenticated access to `GET /api/v1/alerts/events/{id}` succeeds with 200 OK.
  - Permanent event URL `/alerts/e/{id}` resolution.
  - WhatsApp share text format adherence.
  - Security boundary: no private subscriber data, tokens, or emails exposed.
- `tests/test_phase12_acceptance.py` (2 comprehensive end-to-end tests):
  - Unit evaluation of expired event outcomes (`hit`, `false_alarm`, `unverifiable`, `pending`).
  - Full 10-point acceptance scenario covering expired events, track record, guidance, sharing, and security.

### 4.2 Full Regression Run
- **Total Pytest Tests:** 252 collected, **252 passed**, 0 failed (100% pass rate).
  - All Phase 10 tests passed (32 tests).
  - All Phase 11 tests passed (19 tests).
  - All Phase 12 tests passed (15 tests).
- **Ruff Lint Check:** 0 errors across entire repository (`ruff check .` clean).
- **Frontend Oxlint:** 0 errors across 56 frontend files (`npm run lint` clean).
- **Frontend Production Build:** Successful in 4.96s (`npm run build` clean).

---

## 5. Repository Integrity & Boundary Affirmations

- **Main Branch SHA:** `66b09b693e9ece968dcb3be412979705507967b0` (Untouched).
- **Phase 9 6-Hour Ingestion Scheduler:** `.github/workflows/ingest-blend.yml` preserved at `17 0,6,12,18 * * *`.
- **Phase 11 Daily Summary Scheduler:** `.github/workflows/notify-daily-summary.yml` preserved at `30 1 * * *`.
- **DrishtiScan:** Untouched (working tree clean on `main`).
- **Phase 13:** Strictly NOT implemented.
- **CAP Feed:** Remains documented for future roadmap only.
