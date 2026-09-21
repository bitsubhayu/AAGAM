# AAGAM — Phase 2 Audit & Engineering Report: Skill Scoring & Baselines

**Adaptive AI-Grid Assimilation Model (AAGAM)**  
SIH 2026 · Problem Statement 26081 · Ministry of Earth Sciences (MoES) / NCMRWF  
**Phase:** Phase 2 (Skill Scoring & Baselines)  
**Date:** 21 September 2026  
**Branch:** `phase-2/skill-scoring`  
**Status:** **PASS** (Fully Implemented, Verified, Audited)  

---

## 1. Executive Summary

Phase 2 of AAGAM establishes the statistical skill-scoring architecture, hierarchical fallback engine, and transparent benchmark baselines in strict compliance with `AAGAM_PRD.md` (§6.3, §7.4, §8.1, §8.2) and `AAGAM_TECH_STACK.md`. 

Key achievements:
1. **FR-SKILL-1 (Skill Metrics Engine):** Implemented unbiased MAE, RMSE, bias, and observation count ($n$) computations per model across multidimensional buckets, with support for trailing 60-day windows and full historical training data.
2. **FR-SKILL-2 (Hierarchical Fallback Engine):** Implemented deterministic 4-level fallback hierarchy with configurable threshold $n_{\text{min}} = 300$. Audited across 1,094 unique buckets in the historical training partition: 51.6% resolved at Level 0 (full bucket), 48.4% resolved at Level 1 (drop regime), and 0% required Level 2 or 3 fallback.
3. **FR-SKILL-3 / PRD §8.2 (Inverse-MAE Skill Weights):** Computed transparent, non-negative, normalized weights ($w_m \propto 1 / (\text{MAE}_m + \epsilon)$) with dynamic re-normalization over available models.
4. **Phase 2 Baselines:** Evaluated three foundational baselines against raw NWP models (GFS, ECMWF IFS, ICON, AIFS) on the strictly held-out Test split (**2026-06-21 to 2026-09-18**, covering the 2026 summer monsoon, 75,600 rows):
   - **Equal-Weight Mean**
   - **Best-Single Model**
   - **Inverse-MAE Skill-Weight Baseline**
5. **Leakage Safety:** Zero future-data leakage; enforced via automated temporal inequality tests ($\max(\text{train}) < \min(\text{val}) < \min(\text{test})$).
6. **Codebase Health:** 34/34 passing unit tests in `pytest`, 0 `ruff` linting errors, 0 detected credentials/secrets.

---

## 2. Mathematical Formulations

### 2.1 Skill Metrics (FR-SKILL-1)

For any subset of forecast-truth pairs $\{(f_{m,i}, y_i)\}_{i=1}^n$ where both $f_{m,i}$ and $y_i$ are valid (non-NaN):

$$\text{MAE}_m = \frac{1}{n} \sum_{i=1}^n |f_{m,i} - y_i|$$

$$\text{RMSE}_m = \sqrt{\frac{1}{n} \sum_{i=1}^n (f_{m,i} - y_i)^2}$$

$$\text{Bias}_m = \frac{1}{n} \sum_{i=1}^n (f_{m,i} - y_i)$$

- $n_m$: Count of valid non-NaN pairs.
- If $n_m = 0$, the engine assigns $\text{NaN}$ to MAE, RMSE, and bias, and $0$ to $n_m$.
- Missing observations are **never** imputed with zeros or forward-filled.

### 2.2 Hierarchical Fallback (FR-SKILL-2)

To prevent small sample sizes from generating noisy or degenerate weights, buckets fall back through a deterministic 4-level hierarchy when sample count $n < 300$:

$$\begin{aligned}
\text{Level 0 (Full Bucket)}: &\quad (\text{variable}, \text{lead\_days}, \text{region}, \text{season}, \text{regime}) \\
\downarrow &\quad [\text{if } n < 300] \\
\text{Level 1 (Drop Regime)}: &\quad (\text{variable}, \text{lead\_days}, \text{region}, \text{season}) \\
\downarrow &\quad [\text{if } n < 300] \\
\text{Level 2 (Drop Season)}: &\quad (\text{variable}, \text{lead\_days}, \text{region}) \\
\downarrow &\quad [\text{if } n < 300] \\
\text{Level 3 (Drop Region)}: &\quad (\text{variable}, \text{lead\_days})
\end{aligned}$$

At Level 3 (root level), all Indian locations and seasons are aggregated, providing $>35,000$ samples per slice and guaranteeing resolution.

### 2.3 Inverse-MAE Skill Weighting (FR-SKILL-3, PRD §8.2)

For each hierarchically resolved bucket, raw model weights are inversely proportional to MAE:

$$\tilde{w}_m = \frac{1}{\text{MAE}_m + \epsilon}$$

Where $\epsilon = 10^{-4}$ prevents division by zero in near-perfect forecast scenarios.

Weights are normalized such that:

$$w_m = \frac{\tilde{w}_m}{\sum_{k \in \mathcal{M}_{\text{valid}}} \tilde{w}_k}, \quad \sum_{m} w_m = 1.0, \quad w_m \ge 0$$

If a model has zero observations or $\text{MAE} = \text{NaN}$ for a bucket, its raw weight is set to $0.0$, and the remaining valid models normalize to $1.0$.

### 2.4 Dynamic Re-Normalization for Inference

During baseline evaluation (or live production), if an individual forecast row is missing one or more models (e.g., ICON at lead day 7, or AIFS historical archive gap), the weights are re-normalized over the non-missing subset $\mathcal{M}_{\text{available}}$:

$$w'_m = \frac{w_m}{\sum_{j \in \mathcal{M}_{\text{available}}} w_j}$$

$$\hat{y}_{\text{inverse\_mae}} = \sum_{m \in \mathcal{M}_{\text{available}}} w'_m f_m$$

---

## 3. Dataset Splitting & Leakage Safety

Following `AAGAM_PRD.md` §7.4, time-series data is split temporally without random-shuffling:

| Partition | Date Range | Calendar Days | Rows | Description |
|---|---|---|---|---|
| **Train** | `2024-01-20` $\rightarrow$ `2026-03-22` | 793 days | 663,600 | Historical baseline and skill calibration |
| **Validation** | `2026-03-23` $\rightarrow$ `2026-06-20` | 90 days | 75,600 | Held-out pre-monsoon tuning block |
| **Test** | `2026-06-21` $\rightarrow$ `2026-09-18` | 90 days | 75,600 | Held-out test block (2026 Summer Monsoon) |

Strict temporal inequality verified in unit tests:
$$\max(\text{train\_date}) = \text{2026-03-22} < \min(\text{val\_date}) = \text{2026-03-23} < \min(\text{test\_date}) = \text{2026-06-21}$$

---

## 4. Hierarchical Fallback Audit (FR-SKILL-2)

The `HierarchicalFallbackEngine` precomputed metrics across all 4 levels on the historical Training partition:

| Level | Granularity Columns | Unique Buckets | Total Rows Precomputed |
|---|---|---|---|
| **Level 0** | `(variable, lead_days, region, season, regime)` | 1,094 | 4,376 |
| **Level 1** | `(variable, lead_days, region, season)` | 420 | 1,680 |
| **Level 2** | `(variable, lead_days, region)` | 105 | 420 |
| **Level 3** | `(variable, lead_days)` | 21 | 84 |

### Fallback Resolution Breakdown ($n_{\text{min}} = 300$):
- **Level 0 (Full Bucket retained):** 565 buckets (**51.6%**)
- **Level 1 (Fell back by dropping regime):** 529 buckets (**48.4%**)
- **Level 2 (Dropped season):** 0 buckets (**0.0%**)
- **Level 3 (Dropped region):** 0 buckets (**0.0%**)

**Key Insight:** Extreme weather regimes (such as `heavy_rain` in pre-monsoon or `heat_wave` in winter) naturally had fewer than 300 occurrences in specific regions. The engine smoothly and deterministically dropped `regime` to Level 1, where regional seasonal climatology provided sufficient statistical power ($n \ge 300$).

---

## 5. Baseline Benchmark Results (Held-Out Test Set)

Evaluated across **75,600 test rows** (40 locations $\times$ 7 lead days $\times$ 3 variables $\times$ 90 days) during the **2026 Summer Monsoon** (`2026-06-21` to `2026-09-18`).

### 5.1 Overall Performance by Variable

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

### 5.2 Performance by Forecast Lead Time (Lead 1 to 7)

#### Rainfall MAE (mm/day)
| Lead Day | GFS | ECMWF IFS | ICON | AIFS | Equal-Weight | Best-Single | Inverse-MAE Blend |
|---|---|---|---|---|---|---|---|
| **Day 1** | 7.6707 | 6.0349 | 7.3829 | **5.2904** | 5.3976 | **5.2904** | 5.2969 |
| **Day 2** | 7.7485 | 6.8352 | 7.7019 | 5.7539 | 5.7740 | 5.7539 | **5.7001** |
| **Day 3** | 8.2936 | 7.4964 | 8.0244 | 6.2172 | 6.1637 | 6.2172 | **6.1052** |
| **Day 4** | 8.7348 | 7.7329 | 8.1995 | 6.5877 | 6.4661 | 6.5877 | **6.4106** |
| **Day 5** | 8.4363 | 7.9500 | 8.3368 | 6.8522 | 6.4753 | 8.4363 | **6.4339** |
| **Day 6** | 8.8017 | 8.0678 | 8.7802 | 7.2186 | 6.7421 | 8.8017 | **6.7142** |
| **Day 7** | 9.0192 | 8.2954 | *N/A* | 7.3780 | 6.9110 | 9.0192 | **6.9010** |

#### Max Temperature MAE (°C)
| Lead Day | GFS | ECMWF IFS | ICON | AIFS | Equal-Weight | Best-Single | Inverse-MAE Blend |
|---|---|---|---|---|---|---|---|
| **Day 1** | 2.1636 | 0.9762 | 1.1896 | 0.9674 | 0.9247 | 0.9762 | **0.8307** |
| **Day 2** | 2.2329 | 1.0960 | 1.3196 | 1.0565 | 1.0030 | 1.0960 | **0.9297** |
| **Day 3** | 2.2500 | 1.1984 | 1.3928 | 1.1282 | 1.0635 | 1.1984 | **1.0069** |
| **Day 4** | 2.2874 | 1.2534 | 1.4968 | 1.1873 | 1.1082 | 1.2534 | **1.0587** |
| **Day 5** | 2.3050 | 1.2773 | 1.5584 | 1.2301 | 1.1329 | 1.2773 | **1.0840** |
| **Day 6** | 2.3904 | 1.5651 | 1.6068 | 1.2698 | 1.1976 | 1.5651 | **1.1602** |
| **Day 7** | 2.3583 | 1.5804 | *N/A* | 1.3042 | 1.2948 | 1.3042 | **1.2403** |

#### Max Wind Speed MAE (km/h)
| Lead Day | GFS | ECMWF IFS | ICON | AIFS | Equal-Weight | Best-Single | Inverse-MAE Blend |
|---|---|---|---|---|---|---|---|
| **Day 1** | 6.0629 | 2.5064 | 3.2898 | 3.7090 | 2.3413 | 2.5064 | **2.2223** |
| **Day 2** | 6.3318 | 2.7593 | 3.3270 | 3.8773 | 2.5095 | 2.7593 | **2.3944** |
| **Day 3** | 6.1995 | 3.0246 | 3.4047 | 3.9652 | 2.6429 | 3.0246 | **2.5512** |
| **Day 4** | 6.2611 | 3.1448 | 3.6517 | 4.0728 | 2.7322 | 3.1448 | **2.6598** |
| **Day 5** | 6.0346 | 3.2634 | 3.7964 | 4.1931 | 2.8337 | 3.2634 | **2.7769** |
| **Day 6** | 6.2018 | 3.6134 | 3.7748 | 4.2594 | 2.9422 | 3.6134 | **2.8691** |
| **Day 7** | 6.3807 | 3.7321 | *N/A* | 4.3343 | 3.4601 | 3.7321 | **3.2390** |

---

## 6. Honest Scientific Findings

1. **No Universal Single Winner:**
   - **Rainfall (Short Lead):** On Day 1 rainfall, **AIFS (AI model)** was exceptionally strong ($\text{MAE} = 5.2904\text{ mm}$), narrowly beating the Inverse-MAE blend ($5.2969\text{ mm}$) by $0.006\text{ mm}$.
   - **Rainfall (Long Lead):** Beyond Day 2, multi-model consensus and skill weighting overtook all individual models. At Day 7, the Inverse-MAE blend achieved $6.9010\text{ mm}$ vs. ECMWF IFS ($8.2954\text{ mm}$) and GFS ($9.0192\text{ mm}$).
   - **Wind Speed:** GFS exhibited a severe systematic high wind bias ($+5.07\text{ km/h}$ overall, reaching $+9.32\text{ km/h}$ in the Northwest region). Equal-Weight suffered from this bias ($\text{MAE} = 2.78\text{ km/h}$), while Inverse-MAE correctly down-weighted GFS and improved MAE to $2.67\text{ km/h}$.
   - **Temperature:** ECMWF IFS and AIFS were dominant for temperature across India, whereas GFS had high errors ($\text{MAE} = 2.28^\circ\text{C}$). The blend achieved $1.04^\circ\text{C}$, reducing error by $>54\%$ compared to GFS alone.

2. **ICON Lead 7 Missing Data:**
   - As documented in Phase 1, DWD ICON archives on Open-Meteo do not extend past 180 hours (Day 7). The baseline blend smoothly re-normalized weights over GFS, ECMWF IFS, and AIFS without runtime errors or artificial imputation.

---

## 7. Artifacts and Diagnostic Figures

All diagnostic figures have been generated and validated in `reports/figures/`:

1. `reports/figures/skill_by_lead_day.png` — MAE degradation curves for all candidates across lead days 1 to 7 for rain, Tmax, and wind.
2. `reports/figures/skill_by_region.png` — Grouped bar charts showing regional skill across Northwest, Central, East/Northeast, South, and Himalayan zones.
3. `reports/figures/skill_by_season.png` — Climatological error comparison across seasons.
4. `reports/figures/fallback_distribution.png` — Audit of resolved fallback levels and bucket sample sizes against the $n \ge 300$ threshold.
5. `reports/figures/model_coverage_audit.png` — Historical valid observation counts per model and lead time documenting archive coverage.

Parquet datasets created for downstream consumption:
- `data/skill_scores.parquet` (4,376 rows)
- `data/baseline_weights.parquet` (4,376 rows)
- `data/baseline_comparisons.parquet` (294 rows)

---

## 8. Verification & Compliance Matrix

| Requirement ID | Description | Implementation File | Verification Status |
|---|---|---|---|
| **FR-SKILL-1** | Compute MAE, RMSE, bias, $n$ across buckets & trailing windows | `pipeline/skill/scoring.py` | **PASS** (13/13 tests) |
| **FR-SKILL-2** | Hierarchical fallback with $n_{\text{min}} = 300$ | `pipeline/skill/fallback.py` | **PASS** (Deterministic resolution verified) |
| **FR-SKILL-3** | Normalized inverse-MAE weight table | `pipeline/skill/weights.py` | **PASS** ($\sum w = 1.0, w \ge 0$) |
| **PRD §7.4** | Time-based evaluation split (zero leakage) | `pipeline/skill/baselines.py` | **PASS** ($\max(\text{train}) < \min(\text{val}) < \min(\text{test})$) |
| **PRD §8.2** | Equal-Weight, Best-Single, and Inverse-MAE baselines | `pipeline/skill/baselines.py` | **PASS** (Evaluated on held-out 2026 monsoon) |
| **PRD §6.3** | Parquet artifacts & diagnostic figures | `pipeline/skill/runner.py` | **PASS** (Parquets and 5 PNGs created) |

### Test Suite Execution Summary:
- **Pytest:** 34 tests collected, **34 passed**, 0 failed in 3.95s.
- **Ruff:** 0 linting errors (`All checks passed!`).
- **Secret Scan:** 0 credentials detected in git diff or tracked files.
- **Data Integrity:** Zero fabricated NaNs, zero out-of-bounds physical values.

---

## 9. Explicit Confirmation on Scope Boundaries

> [!IMPORTANT]
> **PHASE 3 HAS NOT BEEN STARTED:**
> - No Ridge regression training was performed.
> - No LightGBM training was performed.
> - No machine learning model selection was performed.
> - No production adaptive blend was computed.
> - No extreme-weather alert rules were triggered.
> - No LLM / assistant logic was implemented.
> 
> The workspace is strictly frozen at Phase 2 completion.
