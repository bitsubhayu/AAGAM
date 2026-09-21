# AAGAM — Phase 2 Final Audit & Engineering Report: Skill Scoring & Baselines

**Adaptive AI-Grid Assimilation Model (AAGAM)**  
SIH 2026 · Problem Statement 26081 · Ministry of Earth Sciences (MoES) / NCMRWF  
**Phase:** Phase 2 (Skill Scoring & Baselines)  
**Date:** 21 September 2026  
**Branch:** `phase-2/skill-scoring`  
**Status:** **PASS** (100% Fully Verified, Audited, and Compliant)  

---

## 1. Executive Summary & Audit Verdict

Phase 2 of AAGAM establishes the statistical skill-scoring architecture, hierarchical fallback engine, and transparent benchmark baselines in strict compliance with `AAGAM_PRD.md` (§6.3, §7.4, §8.1, §8.2) and `AAGAM_TECH_STACK.md`.

### Final Audit Verdict: **PASS**

All requirements have been met, verified by automated test suites, and audited against the authoritative dataset:
1. **FR-SKILL-1 (Skill Metrics Engine):** Verified with hand-computed golden vectors for MAE, RMSE, bias, and $n$. Both full historical training data and trailing 60-day live windows are supported and validated with separate Parquet artifacts.
2. **FR-SKILL-2 (Hierarchical Fallback Engine):** Verified deterministic 4-level fallback order with $n_{\text{min}} = 300$. All 1,094 buckets resolved deterministically with zero unresolved cells.
3. **FR-SKILL-3 / PRD §8.2 (Inverse-MAE Skill Weights):** Verified non-negativity ($w_m \ge 0$), sum to 1.0 ($\sum w_m = 1.0$), and graceful zero-weight assignment for missing models.
4. **Baselines Benchmarking:** Verified on strictly held-out test data (**2026-06-21 to 2026-09-18**, 75,600 rows covering the 2026 summer monsoon) across Equal-Weight Mean, Best-Single Model, and Inverse-MAE Skill Blend.
5. **Zero Data Leakage:** Proven and verified by automated temporal inequality assertions ($\max(\text{train}) < \min(\text{val}) < \min(\text{test})$).
6. **Code Quality & Security:** 37/37 passing unit tests in `pytest`, 0 `ruff` linting errors, 0 duplicate keys, 0 secrets in git history.

---

## 2. FR-SKILL-1 Trailing 60-Day Window Verification

Per PRD §6.3:
> *"For each model and each bucket `(variable, lead_days, region, season[, regime])` compute MAE, RMSE, bias, n over a trailing window (default 60 days for live weights; full history for training)."*

### 2.1 Implementation Architecture
- **Filtering Function:** [`filter_by_trailing_window`](file:///c:/Users/subha/OneDrive/Documents/Antigravity_Workspace/AAGAM/pipeline/skill/scoring.py#L69-L103) in `pipeline/skill/scoring.py`.
- **Pipeline Integration:** [`pipeline/skill/runner.py`](file:///c:/Users/subha/OneDrive/Documents/Antigravity_Workspace/AAGAM/pipeline/skill/runner.py) automatically processes both:
  1. Full Historical Training Data $\rightarrow$ [`data/baseline_weights.parquet`](file:///c:/Users/subha/OneDrive/Documents/Antigravity_Workspace/AAGAM/data/baseline_weights.parquet)
  2. Trailing 60-Day Live Window $\rightarrow$ [`data/live_weights_60d.parquet`](file:///c:/Users/subha/OneDrive/Documents/Antigravity_Workspace/AAGAM/data/live_weights_60d.parquet)

### 2.2 Calculated Characteristics of Trailing 60-Day Window
- **Exact Date Window:** `2026-07-21` $\rightarrow$ `2026-09-18` (60 calendar days).
- **Total Filtered Observations:** $40\text{ locations} \times 7\text{ leads} \times 3\text{ variables} \times 60\text{ days} = 50,400\text{ rows}$.
- **Unique Buckets Produced:** 234 buckets.
- **Total Model Weights Produced:** $234 \times 4 = 936\text{ weights}$.
- **Fallback Resolution in 60-Day Window ($n_{\text{min}} = 300$):**
  - Level 0 (Full Bucket): 80 buckets (34.2%)
  - Level 1 (Drop Regime): 154 buckets (65.8%)
  - Level 2 / Level 3: 0 buckets (0.0%)
  *(Notice: The smaller sample size of 60 days naturally causes the fallback engine to engage Level 1 fallback more frequently (65.8%) than full history (48.4%), guaranteeing robust sample sizes $n \ge 300$ without noise).*

### 2.3 Distinctness Proof: Full History vs. Trailing 60-Day Live Weights
Demonstrating that trailing 60-day weights are quantitatively distinct from full-history training metrics, reflecting recent synoptic skill shifts:

#### Representative Bucket: `(rain_mm, lead_days=1, region=NW, season=monsoon, regime=heavy_rain)`
| Model | Full-History MAE | Full-History Weight | Full-History $n$ | 60-Day Live MAE | 60-Day Live Weight | 60-Day Live $n$ |
|---|---|---|---|---|---|---|
| **GFS** | 6.0434 | 0.2193 | 2,196 | 5.1839 | **0.2328** (+0.0135) | 540 |
| **ECMWF IFS** | 4.9631 | 0.2671 | 2,196 | 4.7704 | **0.2529** (-0.0142) | 540 |
| **ICON** | 6.3078 | 0.2101 | 2,196 | 5.7828 | **0.2087** (-0.0014) | 540 |
| **AIFS** | 4.3680 | 0.3035 | 1,098 | 3.9481 | **0.3056** (+0.0021) | 540 |
| **Sum** | — | **1.000000** | — | — | **1.000000** | — |

**Observation:** Over the trailing 60-day monsoon window, AIFS improved its MAE from 4.37 mm to 3.95 mm, and its live weight correctly increased to 0.3056. GFS also showed improved short-range rainfall skill in this window, increasing weight from 0.2193 to 0.2328.

---

## 3. Zero Test Data Leakage Proof

Per `AAGAM_PRD.md` §7.4:
> *"Train = start → (today − ~180 d) · Validation = next 90 d · Test = last 90 d (includes the 2026 monsoon). Never random-shuffle. Add an automated test that asserts max(train_date) < min(val_date) < min(test_date)."*

### 3.1 Strict Chronological Partitions

| Partition | Start Date | End Date | Calendar Days | Rows | Allowed Purpose |
|---|---|---|---|---|---|
| **Train** | `2024-01-20` | `2026-03-22` | 793 days | 663,600 | Fitting `HierarchicalFallbackEngine`, calculating historical skill scores, calculating inverse-MAE baseline weights, selecting Best-Single models. |
| **Validation** | `2026-03-23` | `2026-06-20` | 90 days | 75,600 | Reserved for Phase 3 ML hyperparameter tuning (unused in Phase 2). |
| **Test** | `2026-06-21` | `2026-09-18` | 90 days | 75,600 | Strictly held out. Evaluated only for final candidate metrics comparison. |

### 3.2 Formal Leakage Verification
1. **Inverse-MAE Weights Source:** The fallback engine was initialized exclusively with `splits.train_df`. The latest observation date included in `data/baseline_weights.parquet` is `2026-03-22`.
2. **Best-Single Model Selection Source:** `determine_best_single_models(splits.train_df)` computed training MAE exclusively on data from `2024-01-20` to `2026-03-22`.
3. **No Hindsight Overlap:** The test block begins on `2026-06-21`, exactly 91 days after the end of the training block.
4. **Automated Enforcement:** Verified by automated pytest unit test `test_split_temporal_inequality` and `test_zero_test_data_leakage_in_artifacts`:
   $$\max(\text{train\_date}) = \text{2026-03-22} < \min(\text{val\_date}) = \text{2026-03-23} < \min(\text{test\_date}) = \text{2026-06-21}$$

---

## 4. "Best-Single Model" Methodology & Audit

### 4.1 Selection Methodology
1. **Criterion:** Lowest historical MAE computed on the training partition (`2024-01-20` to `2026-03-22`).
2. **Granularity:** Per `(variable, lead_days)` pair (21 unique combinations: 3 variables $\times$ 7 lead days).
3. **Operational Relevance:** Represents an honest real-world operational decision: forecasters select the single NWP model with the best historical track record for each variable and forecast horizon.

### 4.2 Selected Best-Single Models by Variable and Lead Day

| Variable | Lead Day 1 | Lead Day 2 | Lead Day 3 | Lead Day 4 | Lead Day 5 | Lead Day 6 | Lead Day 7 |
|---|---|---|---|---|---|---|---|
| **Rainfall** (`rain_mm`) | **AIFS** | **AIFS** | **AIFS** | **AIFS** | **GFS** | **GFS** | **GFS** |
| **Max Temp** (`tmax_c`) | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **AIFS** |
| **Max Wind** (`wind_max_kmh`) | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** | **ECMWF IFS** |

### 4.3 Why Test-Set Best-Single Differs from Test-Set Best Raw Individual Model
- In historical training data (`2024-01-20` to `2026-03-22`), GFS had slightly lower average MAE for long-lead rainfall (Leads 5–7).
- However, during the unseen held-out 2026 monsoon test period (`2026-06-21` to `2026-09-18`), AIFS and ECMWF IFS demonstrated superior convective handling, outperforming GFS at Leads 5–7.
- Because Best-Single was pre-selected on historical data, its test performance reflects real-world operational drift: relying on a single static model fails when seasonal or synoptic conditions shift.
- Selecting the best raw model on the test set would constitute in-sample hindsight bias (data leakage). AAGAM strictly reports the true out-of-sample Best-Single baseline.

---

## 5. Inverse-MAE Weights Verification

Mathematical formulation:
$$\tilde{w}_m = \frac{1}{\text{MAE}_m + 10^{-4}}, \quad w_m = \frac{\tilde{w}_m}{\sum_{k \in \mathcal{M}_{\text{valid}}} \tilde{w}_k}$$

### 5.1 Properties Verified Across All 4,376 Rows:
- **Non-negativity:** $\min(w_m) = 0.000000 \ge 0$ (Verified: 0 negative weights).
- **Completeness:** 0 NaN weights across all buckets.
- **Normalization:** $\sum_m w_m = 1.000000 \pm 10^{-6}$ for every single bucket.
- **Zero-Observation Handling:** For ICON at Lead Day 7 (archive horizon $\le 180$h), $n = 0$, $\text{MAE} = \text{NaN}$, weight is strictly assigned $0.0000$, and remaining models (GFS, ECMWF IFS, AIFS) normalize exactly to $1.000000$.

### 5.2 Representative Bucket Weight Audits

#### Bucket A: Rainfall, Short Lead, Dry Regime (Level 0 Full Bucket)
`variable='rain_mm', lead_days=1, region='NW', season='monsoon', regime='dry_or_very_light'`  
*Fallback Level: 0 (full_bucket) | $n_{\text{bucket}} = 942$*
| Model | MAE (mm) | Raw Inverse ($1/(\text{MAE} + \epsilon)$) | Normalized Weight | Model $n$ |
|---|---|---|---|---|
| **GFS** | 0.8915 | 1.1216 | 0.2468 | 942 |
| **ECMWF IFS** | 0.7803 | 1.2814 | **0.2820** | 942 |
| **ICON** | 0.9639 | 1.0373 | 0.2283 | 942 |
| **AIFS** | 0.9057 | 1.1040 | 0.2429 | 437 |
| **Total** | — | **4.5443** | **1.000000** | — |

#### Bucket B: Rainfall, Short Lead, Heavy Rain Regime (Level 1 Fell Back)
`variable='rain_mm', lead_days=1, region='NW', season='monsoon', regime='heavy_rain'`  
*Fallback Level: 1 (drop_regime) | $n_{\text{bucket}} = 2,196$*
| Model | MAE (mm) | Raw Inverse ($1/(\text{MAE} + \epsilon)$) | Normalized Weight | Model $n$ |
|---|---|---|---|---|
| **GFS** | 6.0434 | 0.1655 | 0.2193 | 2,196 |
| **ECMWF IFS** | 4.9631 | 0.2015 | 0.2671 | 2,196 |
| **ICON** | 6.3078 | 0.1585 | 0.2101 | 2,196 |
| **AIFS** | 4.3680 | 0.2289 | **0.3035** | 1,098 |
| **Total** | — | **0.7544** | **1.000000** | — |

#### Bucket C: Max Temperature, Heat Wave Regime (Level 1 Fell Back)
`variable='tmax_c', lead_days=3, region='CENTRAL', season='pre_monsoon', regime='heat_wave'`  
*Fallback Level: 1 (drop_regime) | $n_{\text{bucket}} = 1,442$*
| Model | MAE (°C) | Raw Inverse ($1/(\text{MAE} + \epsilon)$) | Normalized Weight | Model $n$ |
|---|---|---|---|---|
| **GFS** | 1.5612 | 0.6405 | 0.2265 | 1,442 |
| **ECMWF IFS** | 1.1519 | 0.8681 | **0.3069** | 1,442 |
| **ICON** | 1.2659 | 0.7899 | 0.2793 | 1,442 |
| **AIFS** | 1.8876 | 0.5297 | 0.1873 | 798 |
| **Total** | — | **2.8282** | **1.000000** | — |

#### Bucket D: Wind Speed, Moderate Regime (Level 0 Full Bucket)
`variable='wind_max_kmh', lead_days=5, region='SOUTH', season='monsoon', regime='moderate'`  
*Fallback Level: 0 (full_bucket) | $n_{\text{bucket}} = 488$*
| Model | MAE (km/h) | Raw Inverse ($1/(\text{MAE} + \epsilon)$) | Normalized Weight | Model $n$ |
|---|---|---|---|---|
| **GFS** | 6.0586 | 0.1651 | 0.1870 | 488 |
| **ECMWF IFS** | 3.2828 | 0.3046 | **0.3451** | 488 |
| **ICON** | 6.5785 | 0.1520 | 0.1722 | 488 |
| **AIFS** | 3.8324 | 0.2609 | 0.2956 | 241 |
| **Total** | — | **0.8826** | **1.000000** | — |

---

## 6. Full Baseline Benchmark Comparisons (Held-Out Test Set)

Evaluated across **75,600 test rows** during the **2026 Summer Monsoon** (`2026-06-21` to `2026-09-18`):

### Overall Test Block Performance

| Variable | Candidate | MAE | RMSE | Bias | Valid Observations ($n$) |
|---|---|---|---|---|---|
| **Rainfall** (`rain_mm`) | GFS | 8.3864 | 15.8559 | -2.3335 | 25,200 |
| | ECMWF IFS | 7.4875 | 14.3556 | +0.7331 | 25,200 |
| | ICON | 8.0710 | 16.7871 | -0.6665 | 21,600 |
| | AIFS (AI model) | 6.4712 | 11.6996 | +2.0377 | 25,200 |
| | *Equal-Weight Mean* | 6.2757 | 11.8461 | -0.0425 | 25,200 |
| | *Best-Single Model* | 7.1581 | 13.3142 | -0.3292 | 25,200 |
| | **Inverse-MAE Blend** | **6.2231** | **11.7067** | **+0.0752** | 25,200 |
| **Max Temp** (`tmax_c`) | GFS | 2.2840 | 3.0777 | +0.9345 | 25,200 |
| | ECMWF IFS | 1.2781 | 1.6636 | -0.5594 | 25,200 |
| | ICON | 1.4273 | 1.8778 | -0.3546 | 21,600 |
| | AIFS (AI model) | 1.1634 | 1.5007 | -0.6479 | 25,200 |
| | *Equal-Weight Mean* | 1.1035 | 1.4617 | -0.1516 | 25,200 |
| | *Best-Single Model* | 1.2387 | 1.6075 | -0.5457 | 25,200 |
| | **Inverse-MAE Blend** | **1.0444** | **1.3784** | **-0.2541** | 25,200 |
| **Max Wind** (`wind_max_kmh`) | GFS | 6.2103 | 7.8935 | +5.0689 | 25,200 |
| | ECMWF IFS | 3.1491 | 4.1864 | -0.9964 | 25,200 |
| | ICON | 3.5407 | 4.5229 | -2.4868 | 21,600 |
| | AIFS (AI model) | 4.0587 | 5.1049 | -2.6405 | 25,200 |
| | *Equal-Weight Mean* | 2.7803 | 3.5983 | -0.1624 | 25,200 |
| | *Best-Single Model* | 3.1491 | 4.1864 | -0.9964 | 25,200 |
| | **Inverse-MAE Blend** | **2.6733** | **3.4987** | **-0.4122** | 25,200 |

---

## 7. Quality, Tests & Security Execution

- **Pytest:** 37 tests collected, **37 passed**, 0 failed in 5.36s:
  - `test_skill.py`: 16/16 passed (scoring math, golden vectors, trailing window, fallback order, threshold boundary, weight normalization, zero data leakage, Parquet schemas).
  - Regression tests: 21/21 passed (Phase 1 ingestion, locations, preprocessing, Supabase telemetry, API endpoints).
- **Ruff:** `All checks passed!` (0 linting or formatting errors).
- **Duplicate Keys:** 0 duplicate keys across `baseline_weights.parquet`, `live_weights_60d.parquet`, `baseline_comparisons.parquet`, and `skill_scores.parquet`.
- **Data Integrity:** Zero fabricated NaNs, zero out-of-bounds values, non-negative weights verified.
- **Secret Scan:** 0 credentials in git diff or tracked repository files.

---

## 8. Diagnostic Figures

All 5 diagnostic figures are generated and stored in `reports/figures/`:
1. `reports/figures/skill_by_lead_day.png` — MAE degradation vs. lead days (1–7) across candidates.
2. `reports/figures/skill_by_region.png` — Regional skill variation across the 5 IMD regions.
3. `reports/figures/skill_by_season.png` — Climatological seasonal variation.
4. `reports/figures/fallback_distribution.png` — Resolved fallback levels and sample size distribution.
5. `reports/figures/model_coverage_audit.png` — Model valid observation counts documenting archive coverage.

---

## 9. Explicit Scope Boundary

> [!IMPORTANT]
> **PHASE 3 HAS NOT BEEN STARTED:**
> - No Ridge regression model training was performed.
> - No LightGBM model training was performed.
> - No ML model selection or stacking was performed.
> - No dynamic production blending was computed.
> - No extreme-weather alert rules were implemented.
> - No AI assistant / LLM logic was written.
> 
> The repository remains strictly within AAGAM on branch `phase-2/skill-scoring` and is completely frozen at Phase 2 completion.
