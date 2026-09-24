# AAGAM — Automated Model-Version Switching: Design Document
**Continuation of the same audit** (repo `bitsubhayu/AAGAM`, branch `fix/live-functionality-audit`, HEAD `06bd002179dbf7a0b3d15a260c49bd459360f207`). This is a **design**, not code. Nothing in this document has been implemented, committed, or migrated.

## Grounding: what was actually read before writing this design
Per your instruction not to invent a generic MLOps design, this document is built from the real current code, not assumed:
- `pipeline/models/registry.py` (full) — the only place activation/rollback logic currently exists
- `pipeline/models/select.py` (full) — the existing per-(variable, lead_days) Ridge-vs-LightGBM selection rule
- `pipeline/live/retrain_runner.py` (orchestration, first 120 lines + call graph)
- `.github/workflows/train-weekly.yml`, `.github/workflows/ingest-blend.yml`
- `supabase/migrations/*` — exact current schema of `model_versions`, `weights`, `skill_scores`, `pipeline_runs`, `alerts`/`alert_events`
- `api/app/routers/models.py`, `api/app/routers/pipeline.py` — current API surface (confirmed in the prior audit pass: `POST /models/{id}/activate` is **hard-disabled for every role**, always returns 403)
- `docs/PHASE_9_REPORT.md` — the authoritative current definition of Milestone M4 (14-day / 56-cycle scheduled cloud soak, ≥95% success, currently **PENDING**, gating Phase 9)
- The RBAC findings from Part A of this audit (three roles only: `public`, `forecaster`, `coordinator` — no `admin`)

---

## A. Current AAGAM version architecture (as it actually exists today)

**`model_versions` schema** (migration `20260921000003`):
```sql
model_versions (id, created_at, storage_path, metrics jsonb, is_active boolean)
-- partial unique index: at most one is_active = true row at any time
```
That is the entire schema — five columns. There is no `status`, no `parent_version_id`, no `config_hash`, no `algorithm_type`, no evaluation window, no activation/deactivation timestamp separate from `created_at`.

**What actually happens today, end to end:**
1. `train-weekly.yml` runs `python -m pipeline train` every Sunday 02:47 UTC.
2. `RetrainRunner.run_weekly_retraining()` loads `data/training_dataset.parquet`, splits temporally (train/validation/test — confirmed no random shuffle), fits a Ridge stacking engine (`HierarchicalFallbackEngine` + `RidgeStackingEngine`, 4-fold rolling-origin CV) and a LightGBM engine per variable with early stopping on the validation partition.
3. `select.py::run_blend_selection()` runs **per (variable, lead_days)** — 3 variables × up to 8 lead days = up to 24 independent slices — comparing Ridge vs. LightGBM validation MAE for that slice only. If they're within 2%, the slice is flagged `"average"`; otherwise the lower-MAE engine wins. This produces `blend_selection.json`.
4. `ModelRegistry.register_version()` packages the trained artifacts into `models/{yyyymmdd}/`, uploads them to Supabase Storage, and calls `evaluate_quality_gate()`.
5. `evaluate_quality_gate()` computes **one single composite number**: the mean of `metrics["lightgbm_validation_mae"]` (or `validation_mae`) across the three variables — rain, tmax, wind, each already in different units and different scales, averaged with equal implicit weight — and compares it to the same composite computed from the **currently active** version's stored `metrics`. If `candidate ≤ active × 1.02`, the candidate passes.
6. If it passes (or if `force_activate=True`), the same transaction flips `is_active` on the old row to `false` and inserts the new row with `is_active=true`. **This happens automatically, unconditionally, inside the weekly cron job** — there is no shadow period, no canary period, no human approval step, no minimum-sample check, and no cooldown. It is a single-shot, same-cycle promotion.
7. `rollback_to_version(target_version_id)` exists as a separate, manually-invoked method (used by `scripts/drill_model_rollback.py`) that flips `is_active` straight to an arbitrary past version, with no audit row written anywhere other than a log line, no reason field, and no check for whether that target is actually the "last known good" one.
8. The only place a human can act through the product is `POST /api/v1/models/{id}/activate` — and (per Part A of this audit) that endpoint **unconditionally returns 403 to every role**, including Coordinator. So today, the *only* thing that actually changes the active model version is this single weekly script's one-metric gate. There is no manual override reachable through the deployed product at all.

**A separate, already-fine-grained data source already exists and is under-used:** `skill_scores` (migration `20260921000003`) is already keyed by `(computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly)` and separately carries `mae, rmse, bias, pod, far, csi`. `weights` is already keyed by `(version_id, variable, region, season, lead_days, model, method)`. **Neither table is read anywhere in the promotion decision today** — the quality gate in `registry.py` only ever looks at the flat `metrics` JSON blob stored on the candidate/active `model_versions` rows themselves. This is the single most important architectural fact for this design: **the stratified data the switching algorithm needs already exists and is already computed every cycle by `verify-daily.yml`; it simply isn't consulted yet.**

*(Minor code-quality note found while reading, not a security issue: `registry.py` lines 148–149 contain an unreachable duplicate `return passed, reason, active_version` statement immediately after the real return — harmless, worth a one-line cleanup whenever this file is next touched.)*

---

## B. Problems with the current manual/automatic system

1. **Single scalar metric.** Composite MAE, averaged across three variables of different units (mm, °C, km/h) with no normalization, is the entire decision. RMSE, bias, POD/FAR/CSI (all already computed into `skill_scores`) are ignored for the activation decision.
2. **No spatial or temporal stratification.** One number for the whole country, all seasons, all lead days combined. A candidate that is much better at short lead times in the monsoon-heavy East but slightly worse everywhere else could pass or fail the gate for reasons that have nothing to do with its real strengths.
3. **No confidence/sample-size floor.** The gate compares two averages with no regard for how many verified forecasts backed either number.
4. **No hysteresis.** A single weekly cycle where the candidate's composite MAE is 1.9% better (within tolerance to *pass*, but also within noise) is enough to switch — and an equally noisy result next week could switch back. This is exactly the "flapping" scenario this task is asking to be designed against.
5. **No shadow or canary period.** Activation happens the same cycle the metric is computed, with zero operational observation of the candidate actually running in something closer to production conditions first.
6. **No automatic rollback.** If a newly-promoted version degrades in the days *after* promotion (e.g., a genuine regression that validation data didn't catch), nothing detects or reverts it — rollback is a manual script, not a monitor.
7. **No durable audit trail of *why*.** The only record is a log line plus whatever ended up in the winning row's `metrics` JSON. There is no queryable answer to "why is this version active" beyond re-deriving it from `metrics` by hand.
8. **No protection of "last known good."** `rollback_to_version` will happily set `is_active` to any row ID, including one that was itself later found to be bad.
9. **The one human-facing control (`POST /models/{id}/activate`) is completely disabled**, so paradoxically the *only* actor that can currently change the active model is unattended weekly cron — there is no way for a Coordinator to freeze, pause, or force a version through the product today.

None of this means the current design is unreasonable as a v1 — it is a sensible, honest, conservative starting point (single metric, small tolerance, auto-activate only if not worse). The gap is specifically the things this task asks for: multi-metric, stratified, confidence-gated, hysteresis-protected, shadow/canary-verified, auto-monitored, auto-rollback-capable, fully audited promotion.

---

## C. Recommended number of versions — and what "version" should mean going forward

**Recommendation: do not create v1/v2/v3 as separate hand-written algorithms.** The existing system is already a single algorithm (Ridge + LightGBM + per-slice selection + composite-MAE gate) that is retrained weekly and produces a *new version of the same algorithm's fitted parameters* each time. That is the correct shape to keep. What changes going forward is **not** the number of hand-designed algorithm variants — it is:

- **One production *lineage*** (the Ridge+LightGBM+per-slice-selection approach already in place), which continues to produce a new **candidate** version every week (or on-demand), exactly as today.
- A small, fixed, *justified* number of **algorithm generations**, only incremented when the actual blending approach itself changes (not the fitted weights):
  - **Generation 1 (already built and running today):** Ridge stacking + LightGBM, selected per (variable, lead_days) by validation MAE, single composite-MAE activation gate. This is what exists right now — call it `algorithm_type = "ridge_lgbm_v1"` in the new schema (§D), not "v1" of AAGAM as a product.
  - **Generation 2 (this design's actual contribution):** the *same* Ridge+LightGBM fitting, but with the multi-metric, stratified, confidence-gated, hysteresis/shadow/canary-protected **promotion algorithm** described in §E–§Q below replacing today's single-shot composite-MAE gate. The forecasting math does not change; the *decision process for when to trust a new fit* changes. This is `algorithm_type = "ridge_lgbm_v1"` still (same models), with `evaluation_policy = "staged_v2"` (new).
  - **A future Generation 3** (regime-aware blending, or a different engine family entirely) would only be justified once there is real evidence Generation 2's stratified evaluation is *consistently* surfacing a regime/season interaction the current per-slice selection can't capture — this is a "when the data tells you to," not a "because the prompt suggested v1/v2/v3" decision. This document does **not** design Generation 3; it designs the promotion *process* so that if/when a Generation 3 algorithm is proposed, it can compete for promotion through the same machinery.

**So, concretely: every weekly retrain still produces exactly one new *candidate configuration* of the existing algorithm, exactly as today.** What's new is a richer, safer, evidence-gated path from "candidate exists" to "candidate is active," plus the ability for that path to say no, hold, watch, or roll back — not a family of parallel algorithms competing every cycle.

**Are versions permanent production algorithms or candidate configurations?** Candidate configurations, immutable once created. A version is a frozen, reproducible snapshot (trained artifacts + the exact evaluation evidence that led to its status) — never edited in place. A "new version" always means a new row; nothing about an existing row's trained parameters changes after creation. Its **status** changes (candidate → shadow → canary → active → superseded/rolled_back/retired), but its **content** (weights, config, metrics as originally evaluated) does not.

**How are new versions created?** Exactly as today — the weekly retrain cron, plus (new) an on-demand `workflow_dispatch` trigger a Coordinator can fire manually (see §T). No other automatic candidate-generation source is introduced (§E explains why).

---

## D. What a "model version" means — the version manifest

A version must capture everything needed to reproduce the forecast it produced. Extending the existing `model_versions` table (not replacing it) with the fields actually needed, justified one at a time against what's missing in §A/§B:

| Field | Type | Why |
|---|---|---|
| `id` | serial (existing) | unchanged |
| `created_at` | timestamptz (existing) | unchanged |
| `storage_path` | text (existing) | unchanged — points at `models/{yyyymmdd}/` |
| `metrics` | jsonb (existing) | unchanged — keeps the raw per-slice validation numbers already produced by `select.py`/`retrain_runner.py` |
| `is_active` | boolean (existing) | **kept for backward compatibility** with every existing read path (`get_active_version()`, the blend job, the API), but becomes a *derived* value maintained by triggers off the new `status` field (§O/§N), not written directly by application code going forward |
| `parent_version_id` | int, nullable, FK to `model_versions(id)` | every candidate is a retrain of the previous active lineage; needed to answer "what changed" and to know the rollback target if this version is later reverted |
| `algorithm_type` | text | `"ridge_lgbm_v1"` today; only a new value when the actual algorithm family changes (§C) — not incremented per retrain |
| `evaluation_policy` | text | which promotion algorithm governed this version's path to activation — `"legacy_single_gate"` for anything created before this design ships, `"staged_v2"` for everything after, so historical versions remain honestly labeled rather than silently reinterpreted |
| `config_hash` | text | SHA-256 of the serialized training config (feature set, hyperparameters, `TOLERANCE_PCT`, location list, training/validation window bounds) — makes "is this really reproducible" a checkable fact, not a claim |
| `training_window_start`, `training_window_end` | date | the actual train-partition bounds used (from `split_dataset_temporally`) |
| `validation_window_start`, `validation_window_end` | date | ditto for validation — needed so §F/§S evaluation queries can never accidentally reuse the same rows a version was validated on (data-leakage prevention, §18/§R below) |
| `status` | text, CHECK-constrained | the lifecycle state — see §O |
| `activated_at` | timestamptz, nullable | when `status` first became `active` (distinct from `created_at`) |
| `deactivated_at` | timestamptz, nullable | when it stopped being active (superseded or rolled back) |
| `created_by` | text | `"pipeline:train-weekly"` or `"pipeline:manual-dispatch"` or a Coordinator's `user_id` if manually triggered — always a system/service identity for candidate creation itself (never a human directly writes a version row; humans only ever act on *existing* versions per §16 of your brief) |

**This is additive, not a rewrite:** every existing column stays, every existing reader (`get_active_version`, the live-blend job, `api/app/routers/models.py`, `api/app/routers/pipeline.py`) keeps working unmodified against `is_active`/`metrics`/`storage_path` while the new columns are populated alongside.

---

## E. Candidate generation

**Source of candidates: exactly one — the existing weekly retrain, unchanged in *how* it fits Ridge/LightGBM.** This design deliberately does **not** add automatic hyperparameter search, hazard-threshold search, or weight-space exploration as candidate sources. Reasoning, directly answering your instruction not to allow unrestricted automatic parameter search:

- The current system already explores the one dimension that matters most per-slice (Ridge vs. LightGBM vs. average) via `select.py`, bounded to exactly those three outcomes.
- `weights` in the Ridge path are already constrained: `CHECK (weight >= 0 AND weight <= 1)` at the DB layer (migration `20260921000003`), and `registry.py::_populate_weights_table` already normalizes so weights sum to 1 per `(variable, region, season, lead_days, method)` group. No model can be silently zeroed out by an automatic search under this design — the *existing* Ridge fit already handles that via its own regularization; the promotion algorithm does not additionally prune models.
- Adding a second, independent candidate-generation source (e.g., an automatic hyperparameter search running alongside the weekly retrain) multiplies the surface this design has to make safe (more candidates → more chances for a bad one to slip through a stratified-but-still-imperfect gate) for a benefit that hasn't been demonstrated as necessary. If the Generation-1 algorithm's own weekly fit is not the bottleneck on forecast skill, that is itself useful evidence for a future Generation-2 *algorithm* proposal (§C) — not a reason to let the *promotion* system start generating its own algorithmic variants.

**Frequency:** one candidate per weekly retrain cycle (unchanged), plus an operator-triggered `workflow_dispatch` path for an out-of-cycle candidate (e.g., after a deliberate config change), capped at **one on-demand candidate at a time** — a new manual dispatch is refused (with a clear error) while a previous candidate from either source is still anywhere in the `candidate`/`shadow`/`canary` pipeline (§O), so there is never more than one non-active version being evaluated concurrently. This directly satisfies "maximum candidates per cycle": **one**.

**Bounds enforced at candidate-creation time (unchanged from today, made explicit):**
- Ridge weights: `0 ≤ w ≤ 1`, normalized to sum to 1 per stratum (existing DB constraint + existing registry code).
- `TOLERANCE_PCT = 0.02` remains a named, configurable constant (already is — `pipeline/models/select.py:24`, `pipeline/models/registry.py:25`), not a magic number sprinkled inline.
- Minimum training sample requirement: reuse the existing `HierarchicalFallbackEngine(min_samples=300)` bound already present in `retrain_runner.py:103` — if a stratum can't reach 300 samples it already falls back to a coarser bucket; this design does not change that, it only adds an *additional*, separate minimum-sample floor for the *promotion decision* itself (§I), which is a different question from "can this stratum be fit at all."

---

## F. Evaluation windows — multiple, not one

Three windows, each answering a different question, chosen against what AAGAM's own data actually supports (Previous-Runs history from Jan 2024 per the Tech Stack; `skill_scores.window_days` already supports arbitrary windows; `is_weekly` snapshots already retained ~26 weeks per the retention design in `AAGAM_UPGRADE_PACK.md`):

| Window | Length | Question it answers | Why this length |
|---|---|---|---|
| **Recent** | trailing 14 days (≈56 six-hourly cycles, deliberately the same length as the M4 soak window so the two share intuition) | "Is the candidate behaving sanely right now, at all?" | Long enough to span at least one full weekly cycle and multiple synoptic situations; short enough to react to a real problem within the shadow/canary period (§L/§M) rather than waiting a season out |
| **Seasonal** | trailing 90 days, but **only** days matching the *current* IMD season (winter/pre-monsoon/monsoon/post-monsoon) via `skill_scores.season` | "Is the candidate actually better for the weather regime India is in right now?" | Matches the PRD's existing `skill_scores` season stratification directly; 90 days is enough trailing history to contain several weeks of same-season data without reaching back a full year |
| **Long-term baseline** | all available verified history for that `(variable, region, lead_days)` slice, capped by whatever `skill_scores.is_weekly=true` retention already keeps (~26 weeks per the upgrade pack) | "Is the candidate better than the *stable*, noise-averaged baseline, not just a lucky recent stretch?" | This is what actually prevents "one good week" from driving a decision — the long-term window is deliberately the least reactive of the three and is given the most weight in §H |

**A candidate must clear the bar on the long-term baseline window primarily; the recent and seasonal windows are used as corroborating/blocking signals (§H, §K), never as the sole basis for promotion.** This is the direct answer to "prevent the algorithm from overreacting to recent noise": noise dominates short windows, not long ones, so the long window is structurally weighted higher, and the short windows can only *block* a promotion that the long window already supports (via the hysteresis/consecutive-cycle rule in §K), never *trigger* one on their own.

---

## G. Metrics — what's measured, and for what

Reusing exactly the metrics `skill_scores` already computes (migration `20260921000003`: `mae, rmse, bias, pod, far, csi`) — no new metric computation is introduced by this design; only how they're **combined into a decision** is new.

**For continuous variables (rain_mm, tmax_c, wind_max_kmh):**
- **MAE** — primary continuous-accuracy metric (matches the existing gate's intent, kept).
- **RMSE** — penalizes large misses more than MAE; important specifically because rainfall is heavy-tailed (per `AAGAM_PRD.md §4.3`, rain evaluation already uses Tweedie/log-transform reasoning) — a candidate that trades a slightly worse MAE for a much worse RMSE is quietly worse at exactly the large-miss cases that matter for hazard guidance downstream.
- **Bias** — not used to reward/penalize magnitude, but as a **guardrail**: a candidate whose absolute bias is meaningfully larger than the active version's (see §Q, rollback triggers) is flagged even if MAE/RMSE look fine, because systematic over/under-forecasting is exactly the kind of failure mode averaging-based metrics can hide.

**For hazard/extreme-weather guidance (per `AAGAM_PRD.md §8.5`'s existing categorical evaluation, at the IMD rain thresholds already in `skill_scores.threshold_mm`):**
- **POD, FAR, CSI** — used specifically for the rain hazard classes, since that's the only variable with the categorical thresholds already computed. CSI (which balances hits against both misses and false alarms) is the single categorical number carried into the composite score (§H); POD/FAR are kept as **diagnostic, not scored** — a candidate that improves CSI by cutting misses while blowing up false alarms (or vice versa) should be visible in the audit trail (§R) even though CSI alone doesn't fully separate those cases.

**Calibration/reliability:** not scored in this design. `skill_scores` does not currently compute a reliability diagram or calibration statistic, and inventing one now would violate "do not invent numerical coefficients without justification" — this is flagged as a genuine gap and a candidate future addition (§Y, test strategy, includes a recommendation to add this once the data exists), not silently worked around.

**How missing metrics are handled:** if a given `(variable, region, season, lead_days)` stratum has no CSI (e.g., `tmax_c`/`wind_max_kmh`, which have no categorical threshold defined), that stratum's composite score (§H) simply omits the CSI term and renormalizes the remaining weights for that stratum — it is never imputed or defaulted to a guessed value.

---

## H. Composite scoring — normalized, stratified, and honest about its weights

**Two-level structure, not one flat number:**

**Level 1 — per-stratum score**, for each `(variable, region, season, lead_days)` cell that has enough samples (§I):
```
mae_skill    = 1 - (candidate_mae / reference_mae)        # reference = active version, same stratum, same window
rmse_skill   = 1 - (candidate_rmse / reference_rmse)
bias_penalty = -abs(candidate_bias - reference_bias) / (abs(reference_bias) + epsilon)
csi_skill    = (candidate_csi - reference_csi)             # only for rain strata with a defined threshold; CSI is already in [0,1] so no ratio-normalization needed

stratum_score = w_mae * mae_skill + w_rmse * rmse_skill + w_bias * bias_penalty + w_csi * csi_skill
                (weights renormalized to sum to 1 over whichever terms are actually present in this stratum, per §G)
```
Every term is expressed as **skill relative to the active version**, not an absolute metric value — this is what makes the numbers comparable across rain (mm), temperature (°C), and wind (km/h) without inventing a cross-variable normalization scheme: each variable is only ever compared to *itself*, one active-vs-candidate pair at a time.

**Starting weights (explicitly configuration, not hardcoded — see below):** `w_mae = 0.40, w_rmse = 0.30, w_bias = 0.15, w_csi = 0.15`. **Justification, as required — these are not asserted as objectively correct:** MAE and RMSE together carry the majority weight because they are the two metrics every variable has and directly reflect the PRD's own stated primary goal (§2, M1/M2 — beating the equal-mean/best-single baseline on MAE). RMSE is weighted below MAE because it's more outlier-sensitive and, unmoderated, could let a single bad extreme-rain day dominate a decision meant to be about typical-case reliability — MAE stays primary, RMSE corroborates. Bias and CSI are weighted equally and lower because they are guardrail/diagnostic signals (§G) rather than the primary accuracy question. **These four numbers live in `config/model_switching.yaml`, not in code**, exactly per your instruction that any initially-uncertain coefficient must be configuration, reviewable and tunable by whoever owns the product without a code change.

**Level 2 — composite score**, aggregating strata into one number **per evaluation window** (Recent/Seasonal/Long-term from §F):
```
composite_score(window) = weighted_mean(stratum_score across all qualifying strata,
                                          weight = stratum's n_samples in that window)
```
Sample-count weighting means a stratum with 3,000 verified forecasts influences the composite far more than one with 40 — this is the direct, simple way to avoid one thin, noisy bucket (e.g., a rarely-verified Himalayan station) swinging the whole decision, without needing a more elaborate technique that isn't justified by AAGAM's actual data volume (see §19 discussion below on why full bootstrap CIs are not used).

The three window-level composites (`composite_recent`, `composite_seasonal`, `composite_longterm`) are **not** further collapsed into one master number. They are carried separately into the promotion rule (§K), where the long-term composite is the primary gate and the other two act as corroborating/blocking checks — deliberately not hidden behind a single opaque score, so the audit trail (§R) can always show which window(s) actually supported a decision.

---

## I. Minimum sample / confidence requirements

Mandatory floors, checked **before** a stratum's score is allowed to contribute to §H at all:

| Requirement | Threshold | Source of the number |
|---|---|---|
| Minimum verified forecasts per stratum, per window | **≥ 30** | Below this, `stratum_score` is excluded from the composite entirely (not zero-filled, not imputed) — 30 is the conventional rough floor below which a sample mean/MAE is treated as too noisy to trust in most operational forecast-verification practice; this project's own `weights`-table fallback logic already uses a similar philosophy (`min_samples=300` for *fitting*, a lower bar is appropriate for *verifying* since verification only needs to detect a difference, not fit a model) |
| Minimum strata contributing to a window's composite | **≥ 5** of the `(variable, region, season, lead_days)` cells that theoretically apply | Prevents a "long-term composite" that is technically computed but actually rests on one or two lucky/unlucky cells |
| Minimum locations represented | **≥ 50%** of the 40 configured locations must have contributed at least one qualifying stratum | Directly answers "minimum number of locations" — prevents a candidate that only has enough history in, say, 6 well-covered cities from being judged as if it were evaluated nationally |
| Minimum lead times represented | **≥ 4** of the 8 lead days (0–7) | A candidate that's only verifiable at short lead times (because longer-lead history hasn't accumulated yet) should not be promoted on partial-horizon evidence |
| Minimum extreme-event samples (for the CSI term specifically) | **≥ 10** verified rain-threshold crossings in the window | CSI computed from fewer than 10 actual hazard events is dominated by single-event noise; below this floor the CSI term is dropped from that stratum's score (§G's "missing metric" handling), not defaulted |

**What does not count toward any of these floors** (directly per your brief): rows where `skill_scores` truth is missing, `outcome IN ('pending','unverifiable')` on the `alert_events` side (reusing the exact vocabulary already defined for alert verification in the earlier phase of this audit), or rows flagged `degraded=true` on `blended_forecasts` (a model was missing that cycle). These are excluded from the denominator entirely, not counted as zero-skill or dropped silently without being logged — the count of excluded rows is itself recorded in the audit trail (§R) so "insufficient data" decisions are inspectable.

**Statistical reasoning:** this design deliberately does **not** claim formal statistical power/significance guarantees (that would require assumptions about the error distribution this document isn't in a position to justify from the data available). Instead it uses **sample-count floors + weighted aggregation + a long-term-primary window + a multi-cycle hysteresis requirement (§K)** as a combined, defensible substitute — each individual mechanism is simple and auditable, and together they target the same goal (don't act on thin evidence) that a formal significance test would, without asserting a confidence-interval precision this system's data volume doesn't clearly support (see §19).

---

## J. Confidence rules (summary — mechanics detailed in §I above and §K below)
A window's composite score is only "usable" (eligible to support a promotion/rollback decision) when **all** of §I's floors are met simultaneously for that window. A window that fails any floor is marked `insufficient_evidence` in the audit trail and is simply excluded from that cycle's decision — the promotion state machine (§N) treats "insufficient evidence on the long-term window" as a hard block, not as a pass-by-default.

---

## K. Hysteresis — preventing version flapping

This directly answers your v2=0.812 vs v3=0.814 example. Three mechanisms, used together (your brief asked for the best combination, not a single one):

**1. Promotion margin — Conservative Operational Margin with Regional Guardrail (Formulation B):**
Do NOT interpret or describe this as a statistical standard error, confidence interval, significance test, or probability. It is an operational promotion-risk margin.

The promotion rule requires BOTH:
1. Candidate composite advantage $\ge$ `required_margin`
2. Every one of the 5 configured AAGAM meteorological regions (`EAST_NE`, `SOUTH`, `CENTRAL`, `NW`, `HIMALAYAN`) satisfies the regional non-regression guardrail:
   $$\text{regional\_score}_r \ge -0.01$$

The exact required margin equation:
```
required_margin = BASE_MARGIN * (1 + lambda_sample + lambda_inconsistency)
```
Where:
- `BASE_MARGIN = 0.02`: an **absolute composite-score margin** (not a percentage).
- `lambda_sample = max(0.0, (target_sample_volume - N_total) / target_sample_volume)`: where `target_sample_volume = 1000` and `N_total = sum(n_s)`.
- `lambda_inconsistency = (sum_{s: Y_s < 0} n_s) / N_total`: sample-weighted fraction of verified forecast volume in strata where the candidate degraded ($Y_s < 0$).
- All numeric parameters are strictly configuration-driven in `config/model_switching.yaml`.
- Insufficient evidence ($N_{\text{total}} < 150$ or fewer than 5 qualifying strata or missing any of the 5 regions) must block promotion (`INSUFFICIENT_DATA`), never reduce the margin to allow promotion.

In the negative test case (0.812 vs 0.814): candidate composite advantage is 0.002. Since `required_margin >= 0.02`, candidate advantage $0.002 < 0.02$, so promotion is rejected with `decision='NO_IMPROVEMENT'`.

**2. Consecutive-cycle confirmation:** a candidate must clear the margin above on **two consecutive weekly evaluation cycles**, not one. Practically: the first cycle a candidate passes moves it from `evaluating` to `eligible` (§N) but does *not* activate it; only a second, independent cycle's evaluation (using a window that has rolled forward, so it is not literally re-scoring the same days) confirms eligibility and allows the state machine to proceed toward shadow/canary. A candidate that passed by luck once is very unlikely to pass by luck twice in a row against a wider, later window.

**3. Minimum dwell time:** once a version is actually promoted to `active`, it must remain active for **at least 14 days** (the same length as the Recent window in §F, and as the M4 soak — chosen for consistency of intuition across the project, not coincidence) before a *new* candidate is even eligible to begin displacing it, **unless** an automatic rollback (§Q) fires, which is explicitly exempt from this dwell time because rollback exists precisely to react faster than the promotion path when something is actively wrong. This directly prevents the `v1 → v2 → v1 → v2 → v3 → v2` oscillation your brief describes: even a genuinely superior candidate cannot displace an incumbent inside its first two weeks, by design.

---

## L. Shadow evaluation

**Shadow mode = the candidate's forecasts are computed and scored, but never written to `blended_forecasts` or shown to any user, forecaster, or alert rule.** This is a new, additive computation path, not a change to the existing live-blend job's output.

- **Duration:** the candidate remains in `shadow` for exactly **one full weekly cycle** (7 days) after passing the two-consecutive-cycle eligibility check in §K — long enough to observe a full week of real, current data end-to-end (including at least one live ingest/verify cycle pair for every lead day 0–7), short enough that it doesn't indefinitely delay a genuinely good candidate.
- **Minimum samples during shadow:** the same §I floors, re-evaluated using *only* data generated during the shadow window itself (not the earlier training/validation history) — this is what actually tests "does this work going forward," separate from "did it look good on held-out historical data."
- **Comparison methodology:** shadow-window composite score (§H, computed the identical way) vs. the active version's composite score over that *same* calendar week (both scored against the same truth, so this is a fair, like-for-like comparison, not shadow-vs-a-different-time-period-of-active).
- **Candidate failure handling:** if the shadow-window composite fails to hold the §K margin, the candidate is moved to `rejected` (§N) with the shadow-period evidence recorded in the audit trail (§R) — it does not get a second shadow attempt on the same trained artifacts; a genuinely improved candidate would come from the *next* weekly retrain, which starts from fresher data anyway.
- **Resource limits:** shadow scoring reuses the exact same inference code path as production blending (no separate "shadow model server") and runs as an additional step inside the existing 6-hourly `ingest-blend` cycle, writing its outputs to a new, separate table (§S) rather than a parallel pipeline — this bounds the added compute to "one extra blend pass per cycle," not a second parallel system.

---

## M. Canary evaluation

**Canary = the candidate is live for a small, explicit subset of production traffic, not just computed silently.** This is the step between "looks good in shadow" and "fully active everywhere."

- **Canary scope:** the candidate's blend becomes the **displayed default** (in `blended_forecasts` and the dashboard) for **5 of the 40 configured locations**, chosen to span the five regions defined in `config/regions.yaml` (one per region) so the canary can't accidentally be evaluated only in one climate/terrain type. The other 35 locations continue to be served by the still-active version throughout canary.
- **Why 5, not "a percentage of traffic" in the usual web-service sense:** AAGAM doesn't have per-request traffic to split — it has 40 fixed locations. A per-location canary is the natural equivalent and has the useful property that it is fully explainable to a Coordinator ("these five places are on the candidate right now") rather than a probabilistic sampling scheme.
- **Duration:** **14 days** (again matching the Recent window and M4 soak length) — long enough to include real forecaster/subscriber-facing usage and at least one full extreme-weather-alert cycle in a typical Indian synoptic pattern, not just internal shadow scoring.
- **Minimum samples:** §I floors, evaluated only within the 5 canary locations plus the matching stratified windows — necessarily a smaller n than the full-network floors, so the per-location floor uses a relaxed sample count (**≥ 15** verified forecasts per stratum instead of 30) explicitly because this is a narrower slice by design, not a lowering of rigor — the *full-network* promotion decision at the end of canary (§N) still requires the original §I floors, now satisfied by canary-period data pooled with the preceding shadow-period data.
- **Failure handling:** if canary-period performance at those 5 locations fails the margin, or (more importantly) if any automatic rollback trigger (§Q) fires during canary, the candidate is immediately reverted to shadow-only (those 5 locations revert to the incumbent) and marked `rejected` — canary failure is treated exactly as seriously as an active-version rollback, just scoped to fewer locations, because it is testing real user-facing output.
- **Resource limits:** identical reasoning to §L — one extra blend pass, now for 5 locations' worth of "which version is authoritative for the dashboard," implemented as a lookup table (§S) the API layer consults per-location rather than a second deployment.

---

## N. Automatic promotion — state machine

**States** (extends the existing two-value `is_active` boolean into a real `status` column per §D, while keeping `is_active` itself as a maintained derived flag so nothing existing breaks):

```
draft → candidate → evaluating → eligible → shadow → canary → active → superseded
                 ↘ rejected                          ↘ rejected         ↘ rolled_back
```

| State | Meaning | Entered when | `is_active` |
|---|---|---|---|
| `draft` | Artifacts trained, not yet registered | `RetrainRunner` finishes fitting, before `register_version()` commits the row | false |
| `candidate` | Registered in DB, first cycle's §H scoring not yet run | Row inserted | false |
| `evaluating` | §H/§I scoring in progress for the current cycle | Automatically, same transaction as insert | false |
| `eligible` | Passed §K's margin on cycle 1, waiting for cycle-2 confirmation | §K mechanism 1 passes | false |
| `rejected` | Failed the gate, or failed shadow/canary | Any evaluation cycle fails §K, or shadow/canary fails | false — **terminal, no further transitions** |
| `shadow` | Passed §K's two-cycle confirmation; running silently per §L | §K mechanism 2 confirms | false |
| `canary` | Passed shadow; live at 5 locations per §M | §L succeeds | false (network-wide); this version *is* what those 5 locations serve, tracked separately (§S), not via the global `is_active` flag |
| `active` | Fully promoted, serving all 40 locations | §M succeeds | **true** — and this is the only automatic transition that flips the existing `is_active` column, keeping every current reader correct with zero code changes required in the live-blend job |
| `superseded` | Was `active`, a later version has now been promoted over it | The *next* version reaches `active` | false |
| `rolled_back` | Was `active`, automatically or manually reverted | §Q fires | false — **the previous version it reverted to is set back to `active`**, not this row |

**Every transition's exact condition** (no "if performance looks good" wording, per your instruction):
- `candidate → evaluating`: automatic, immediately.
- `evaluating → eligible`: `composite_longterm(candidate) ≥ composite_longterm(active) + required_margin` (§K.1) **and** all §I floors met for the long-term window **and** neither the Recent nor Seasonal window's composite is *below* the active version's by more than `required_margin` (i.e., short-term/seasonal windows can't trigger promotion alone, but a clearly bad short-term signal can veto one — this is the "corroborating/blocking" role promised in §F).
- `evaluating → rejected`: the negation of the above, OR any §I floor fails on the long-term window (`INSUFFICIENT_DATA`, distinct reason code from `NO_IMPROVEMENT` in the audit trail, §R).
- `eligible → shadow`: the **next** weekly cycle's evaluation independently re-confirms the same condition as `evaluating → eligible`, using a window that has rolled forward (§K.2). If it doesn't reconfirm, `eligible → rejected` (reason `NOT_CONFIRMED`).
- `shadow → canary`: 7 days elapsed in `shadow` **and** §L's shadow-period composite meets the same margin, computed against the *concurrent* active-version performance.
- `shadow → rejected`: §L failure, or 7 days elapsed without meeting the floors (reason `INSUFFICIENT_DATA` if floors unmet, `NO_IMPROVEMENT` if floors met but margin not held).
- `canary → active`: 14 days elapsed in `canary` **and** §M's pooled canary+shadow evidence meets the full-network §I floors and §K margin **and** no rollback trigger (§Q) fired during canary.
- `canary → rejected`: any rollback trigger fires during canary, or the 14 days elapse without meeting the criteria above.
- `active → superseded`: automatic, the instant a different version's `canary → active` transition commits (single transaction, mirrors the existing `UPDATE model_versions SET is_active=false ... ; INSERT ... is_active=true` pattern already in `registry.py`, extended to also stamp `status`/`deactivated_at`/`activated_at`).
- `active → rolled_back`: any §Q trigger fires against the currently active version (not a candidate — this is a live degradation).

---

## O. Automatic rollback — state machine and triggers

**Rollback target is always `parent_version_id` of the failing version — i.e., "the version it superseded" — never an arbitrary version ID.** This directly answers "rollback should normally return to the last known-good version": the parent pointer introduced in §D *is* that definition, mechanically, not just by convention.

**Triggers** (evaluated every 6-hourly cycle for the currently `active` version and, separately, every cycle during `canary` for the canary version — reusing the same §H/§I machinery, just pointed at a very short trailing window):

| Trigger | Threshold | Window | Why this one, and why not others in your brief's list |
|---|---|---|---|
| Sudden MAE/RMSE degradation | Trailing-3-day composite MAE worse than the version's own *shadow/canary-period* baseline MAE by more than 25% | 3 days, min 20 samples | A large, fast move relative to the version's *own* recent history (not the old active version's) is the clearest signal something broke specifically about this deployment, not just "the weather got hard everywhere" |
| Bias explosion | `abs(bias)` more than triples versus the version's shadow/canary-period baseline bias | 3 days, min 20 samples | Matches §G's guardrail role for bias — a sign-flip or scale error in a new fit shows up here fast and is rarely a "the weather was just unusual" explanation |
| CSI collapse | Rain CSI drops by more than 0.15 (absolute) versus baseline, **and** at least 3 real threshold-crossing events occurred in the window | 3 days | Guards specifically against the hazard-guidance use case degrading even if continuous MAE looks fine; the event-count condition stops a single missed/false alarm from being treated as a "collapse" |
| Pipeline error rate | Any 3 consecutive 6-hourly cycles where this version's blend step raises an exception or writes zero rows | 3 cycles (18h) | Operational/data-integrity failure, not a forecast-quality question — deliberately fast because this is a "is it working at all" check, not a statistical one |
| Missing forecast coverage | Version's blend is `degraded=true` (an upstream model source missing) for more than 50% of locations in a single cycle, for 2 consecutive cycles | 2 cycles | Distinguishes "one model API had a bad hour" (already handled by the existing per-cycle `degraded` flag and renormalization, per `AAGAM_PRD.md FR-BLEND-4`) from a real, sustained coverage problem worth reverting for |

**Explicitly not used as rollback triggers**, per your brief's own caution list: a single day's bad forecast, one missed extreme event in isolation, or any signal computed from a stratum currently below its §I sample floor (an under-sampled stratum's "bad-looking" number is excluded from rollback scoring exactly as it's excluded from promotion scoring — consistent treatment both directions).

**Cooldown:** after any automatic rollback, the system enters a **7-day cooldown** during which no *new* promotion (§N) may reach `active`, even if a different, unrelated candidate is independently sitting in `canary` and would otherwise qualify — the one exception is that the rolled-back-to parent version itself is, by definition, already `active` again the instant rollback executes; cooldown blocks the *next* promotion on top of it, giving the system time to confirm the rollback target is itself stable before layering more change on top. Rollback itself is **never** subject to cooldown against *itself* firing again — if the reinstated parent version somehow also degrades, the same triggers apply to it too, but there is a **hard circuit breaker**: if two rollbacks occur within any rolling 14-day period, automatic promotion is fully frozen (state machine held at whatever `active` version is currently in place) and the system requires a Coordinator's explicit manual action (§16 below) to resume — this is the "never automatically rollback repeatedly without a safety mechanism" requirement, made concrete.

**Rollback audit record:** every rollback (automatic or manual) writes a row to the new `model_version_decisions` table (§S) with `decision='ROLLED_BACK'`, the exact trigger that fired, the metric values that crossed the threshold, the window, and the sample counts — the same schema used for promotion decisions (§R), not a separate mechanism.

---

## P. Emergency fallback

**`last_known_good_version` is not a separate concept from `parent_version_id`/`status='active'` — it is simply "whichever version currently has `status='active'`."** This deliberately avoids introducing a second, potentially-inconsistent pointer to track. Protection:

- The currently-`active` version's row can **never** be deleted (DB-level: no `DELETE` statement exists anywhere in the codebase against `model_versions`, and this design does not add one — versions are only ever superseded/rolled_back/retired, i.e. status changes, never row deletions, for the lifetime of the product).
- If the automated evaluation pipeline itself fails (DB partially unavailable, Groq/Open-Meteo/whatever external dependency is down, or — per your brief — "no candidate has enough evidence"), the system's deterministic safe state is simply: **do nothing.** The currently-`active` version keeps serving exactly as it does today when nothing is wrong; a failed evaluation cycle is logged (`pipeline_runs`, exactly as today) and retried next cycle. This is a direct consequence of the state machine in §N never having an automatic transition that *requires* a candidate to exist or a decision to be reached — absence of evidence simply means no transition fires, not that the system enters an undefined state.
- If **all** candidates are exhausted (every recent candidate `rejected`), the system simply continues serving the long-standing `active` version indefinitely — there is no forced-promotion path anywhere in this design, matching your explicit prohibition on promoting from insufficient evidence.
- If observations/truth are unavailable (an IMD/ERA5 outage), every window in §F that depends on verified truth naturally fails its §I sample floors and the promotion/rollback machinery goes quiet on its own — this reuses the exact "don't count pending/unverifiable rows" logic already defined for alert verification, applied here too, rather than inventing separate handling.

---

## Q. Cooldown
Covered concretely in §O (7-day post-rollback cooldown, 14-day double-rollback circuit breaker) and §K.3 (14-day minimum dwell time after any promotion, which is the *symmetric* cooldown on the promotion side — nothing new to add here beyond cross-referencing both, by design, so the rule lives in one place per direction rather than being restated.

---

## R. Audit trail

**New table, `model_version_decisions`** (full schema in §S) — every transition in §N and every trigger evaluation in §O, whether it fired or not, writes exactly one row. Fields directly answer "why is v3 active today":

```
id, decision (PROMOTED | ROLLED_BACK | REJECTED | INSUFFICIENT_DATA | NO_IMPROVEMENT |
              OPERATIONAL_FAILURE | COOLDOWN | FROZEN | NOT_CONFIRMED),
previous_version_id, candidate_version_id,
composite_recent, composite_seasonal, composite_longterm (both previous and candidate, all six numbers),
sample_counts jsonb (per-window, per-floor-type counts from §I, including excluded-row counts),
evaluation_window_start, evaluation_window_end,
reason text (human-readable, generated from the exact numeric comparison — never freeform),
triggered_by (trigger name from §O's table, null for promotion-path decisions),
pipeline_run_id (FK to the existing pipeline_runs table — ties every decision to the exact cycle that made it),
algorithm_version (the `evaluation_policy` value from §D, so a future change to the promotion algorithm itself is distinguishable from a change in the forecasting algorithm),
created_at
```
"Why is v3 active today" is then answerable with a single query: the most recent `PROMOTED` row where `candidate_version_id` equals the currently-active version's id, which carries every number that decision was based on, plus (by following `previous_version_id` backward) the full chain of decisions that led there. This table is **append-only** — no `UPDATE`/`DELETE` path is defined or needed.


---

## Location / variable / lead-time awareness (§7 of the brief)
**Design chosen: one global active version, with the stratified §H/§I scoring machinery deciding whether that global version should change — not 40 independent per-station production versions.** Reasoning:

- `weights` already gives every location's blend its own adaptive per-region/season/lead trust *within* a single active version (this is the existing, working adaptive-weighting design from `AAGAM_PRD.md §4` — nothing here changes that). The switching question this document addresses is one level up: *when do we trust an entirely new fit of that same adaptive machinery over the current one* — and that is inherently a network-wide question, because a new Ridge/LightGBM fit changes model behavior everywhere at once, not station-by-station.
- 40 independent production versions would mean 40 independent promotion/rollback state machines, 40 independent audit trails, and — critically — would fragment the sample sizes §I already treats as marginal (30/stratum) into something far too thin per station to ever confidently promote anything. This would directly work against "prevent switching based on insufficient evidence."
- The canary mechanism (§M) is the deliberate middle ground: it *does* let the system observe location-specific behavior before a full commitment, without maintaining permanent per-location versions.

## Regime / season awareness (§8 of the brief)
**Season:** used directly, via the existing `skill_scores.season` column (winter/premonsoon/monsoon/postmonsoon) — this is not invented, it's the classification AAGAM already computes every verification cycle, reused as one of §F's three windows.
**Weather regime (heavy rain / heat / strong wind / normal):** **not** used as a promotion-evaluation axis in this design, deliberately. Reasoning, directly per your instruction not to hardcode an arbitrary regime classifier: AAGAM's only existing regime-like concept is the *intensity bucket* used for weight-fallback (`AAGAM_PRD.md §8.1`: rain `<2.5/2.5–15.5/15.6–64.4/≥64.5` etc.), which the design's brief itself already describes as "a data-driven proxy... not a full classification." Building automatic model promotion on top of an admittedly-approximate proxy classifier risks exactly the false-confidence problem this whole task is trying to avoid. Season is a real, unambiguous, already-computed label; regime is not, today. **This is flagged as a legitimate candidate extension once/if a more principled regime classification exists** (§Y notes it as a follow-up), not silently worked around with the existing proxy.
**Single-event dominance is prevented structurally, not by a special case:** the long-term window (§F) is the primary gate, and §I's ≥10-event floor for CSI plus the sample-count-weighted aggregation in §H mean one extreme day already can't dominate a multi-week composite — no additional regime-specific damping is needed on top of mechanisms already justified above.

## Statistical robustness (§19 of the brief)
Explicitly considered and **rejected** where not justified by AAGAM's actual data volume, per your instruction not to blindly implement techniques:
- **Winsorization:** not applied — RMSE (§G) already exists specifically to be sensitive to large errors, and clipping extremes before scoring would work against the CSI/rain-hazard use case where the extremes *are* the thing being evaluated.
- **Bootstrap confidence intervals:** not used. A proper bootstrap over the per-location, per-lead-day forecast errors would need to account for the fact that errors are **correlated across nearby locations and across lead times for the same issue cycle** (your brief's own "correlated locations" and "lead-time correlation" concerns) — doing this correctly requires a block/cluster bootstrap keyed on synoptic situation, which is a real statistical undertaking this document isn't positioned to design responsibly from the data available today. Instead, Decision 5 adopts **Formulation B**: an operational promotion-risk margin with sample-size penalties and a mandatory regional non-regression guardrail (§K.1), explicitly avoiding any pretension of being a formal statistical standard error.
- **Weighted aggregation:** used — sample-count weighting in §H, directly justified above.
- **Stratified evaluation:** used — the entire §F/§H/§I structure is stratified by construction.
- **Robust metrics (e.g., median absolute error instead of mean):** not substituted for MAE, to stay consistent with the PRD's existing skill-score definitions (`AAGAM_PRD.md §2.3`, M1/M2) — introducing a different central-tendency metric here than the one used everywhere else in the product would make the two hard to compare.

## Computational cost (§20 of the brief)
- **Evaluation frequency:** the full §H/§I scoring runs **once per 6-hourly cycle** for whichever versions are currently in `evaluating`/`shadow`/`canary`/`active`-being-monitored-for-rollback — there is normally at most one non-active version in flight (§E's one-candidate-at-a-time rule), so this is at most two versions' worth of scoring per cycle (the active one, for rollback monitoring, and the one candidate, for promotion progress), not a combinatorial search.
- **Incremental, not full-recompute:** scoring reads `skill_scores` rows that `verify-daily.yml` has *already computed and written* — this design adds a read-and-aggregate step, not a new source of heavy computation. The 180-day/26-week retention already defined for `skill_scores` (`AAGAM_UPGRADE_PACK.md §7.4`) is exactly the data this design's Long-term window consumes; no additional raw-forecast recomputation is introduced.
- **Materialization:** each cycle's composite scores (§H) for whichever version(s) are being evaluated are written to `model_version_evaluations` (§S) as a small, append-only row set (a handful of rows: 3 windows × up to ~24 strata, at most) — cheap to write, cheap to query later for the audit trail, and avoids ever recomputing a past cycle's composite from scratch.
- **Where this runs:** as an additional step inside the existing `ingest-blend.yml` 6-hourly job (for shadow/canary/rollback-monitoring, which need to react within days) and the existing `train-weekly.yml`/`verify-daily.yml` jobs (for the `evaluating`/`eligible` transitions, which are inherently weekly-cadence per §K). No new scheduled workflow is introduced — see §U.

---

## S. Database changes

**Extend `model_versions`** (additive columns only, per §D — full list there, not repeated). All new columns nullable or defaulted so existing rows and existing readers remain valid with zero migration risk to current functionality.
```sql
ALTER TABLE model_versions
  ADD COLUMN parent_version_id INT REFERENCES model_versions(id),
  ADD COLUMN algorithm_type TEXT NOT NULL DEFAULT 'ridge_lgbm_v1',
  ADD COLUMN evaluation_policy TEXT NOT NULL DEFAULT 'legacy_single_gate',
  ADD COLUMN config_hash TEXT,
  ADD COLUMN training_window_start DATE,
  ADD COLUMN training_window_end DATE,
  ADD COLUMN validation_window_start DATE,
  ADD COLUMN validation_window_end DATE,
  ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('draft','candidate','evaluating','eligible','shadow','canary',
                       'active','superseded','rejected','rolled_back','retired')),
  ADD COLUMN activated_at TIMESTAMPTZ,
  ADD COLUMN deactivated_at TIMESTAMPTZ,
  ADD COLUMN created_by TEXT NOT NULL DEFAULT 'pipeline:legacy';
-- Backfill: existing rows get status = 'active'/'superseded' matching their current is_active value,
-- evaluation_policy = 'legacy_single_gate', created_by = 'pipeline:legacy' — a one-time UPDATE, not a
-- behavioral change to any existing row.
```

**New table `model_version_evaluations`** — one row per (version, window, evaluation cycle); the materialized §H/§I output.
```sql
CREATE TABLE model_version_evaluations (
    id                 BIGSERIAL PRIMARY KEY,
    version_id         INT NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
    pipeline_run_id    BIGINT REFERENCES pipeline_runs(id),
    window_type        TEXT NOT NULL CHECK (window_type IN ('recent','seasonal','longterm')),
    window_start       DATE NOT NULL,
    window_end         DATE NOT NULL,
    composite_score    REAL,
    strata_included    INT NOT NULL,
    strata_excluded    INT NOT NULL,       -- failed §I floors
    locations_covered  INT NOT NULL,
    lead_days_covered  INT NOT NULL,
    sample_counts      JSONB NOT NULL,     -- per-metric counts, incl. excluded pending/unverifiable/degraded rows
    metrics_detail     JSONB NOT NULL,     -- per-stratum mae/rmse/bias/csi and their skill-vs-reference values
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON model_version_evaluations (version_id, window_type, computed_at DESC);
```
*(Append-only. Retention: keep indefinitely — this is the evidentiary record for every decision in `model_version_decisions`; volume is small, at most a few hundred rows per version's lifetime.)*

**New table `model_version_decisions`** — schema per §R, the audit trail:
```sql
CREATE TABLE model_version_decisions (
    id                     BIGSERIAL PRIMARY KEY,
    decision               TEXT NOT NULL CHECK (decision IN (
                              'PROMOTED','ROLLED_BACK','REJECTED','INSUFFICIENT_DATA',
                              'NO_IMPROVEMENT','OPERATIONAL_FAILURE','COOLDOWN','FROZEN','NOT_CONFIRMED')),
    previous_version_id    INT REFERENCES model_versions(id),
    candidate_version_id   INT REFERENCES model_versions(id),
    composite_recent_prev  REAL, composite_recent_cand  REAL,
    composite_seasonal_prev REAL, composite_seasonal_cand REAL,
    composite_longterm_prev REAL, composite_longterm_cand REAL,
    sample_counts          JSONB NOT NULL,
    evaluation_window_start DATE, evaluation_window_end DATE,
    reason                 TEXT NOT NULL,
    triggered_by            TEXT,           -- rollback trigger name, null for promotion-path rows
    pipeline_run_id         BIGINT REFERENCES pipeline_runs(id),
    algorithm_version        TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON model_version_decisions (candidate_version_id, created_at DESC);
CREATE INDEX ON model_version_decisions (decision, created_at DESC);
-- Append-only, retained indefinitely (this IS the audit trail; volume is at most a few rows per week).
```

**New table `model_version_canary_assignments`** — which version serves which location during canary (§M):
```sql
CREATE TABLE model_version_canary_assignments (
    location_id   INT NOT NULL REFERENCES locations(id),
    version_id    INT NOT NULL REFERENCES model_versions(id),
    assigned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at   TIMESTAMPTZ,
    PRIMARY KEY (location_id, version_id, assigned_at)
);
-- Read by the live-blend job to decide, per location, whether to also compute/serve the canary version's
-- blend as the displayed one for that location during the canary window. Append-only (released_at marks
-- the end of an assignment rather than deleting the row, preserving history of what served what, when).
```

**New table `model_switching_automation_state`** — the single-row control surface for freeze/pause and cooldown bookkeeping (§16, §O):
```sql
CREATE TABLE model_switching_automation_state (
    id                      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton row
    frozen                  BOOLEAN NOT NULL DEFAULT FALSE,
    frozen_reason           TEXT,
    frozen_by               UUID REFERENCES auth.users(id),
    frozen_at               TIMESTAMPTZ,
    cooldown_until           TIMESTAMPTZ,
    rollback_count_14d       INT NOT NULL DEFAULT 0,       -- maintained by the rollback trigger logic, §O
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO model_switching_automation_state (id) VALUES (1);
```

**RLS for all four new tables:** `model_version_evaluations`, `model_version_decisions` → `SELECT` for `anon, authenticated` (transparency — this is exactly the kind of "why is this trusted" evidence `AAGAM_PRD.md`'s design principles already commit to surfacing publicly for weight maps; no reason to hide it for version decisions), **no client `INSERT`/`UPDATE`/`DELETE` policy at all** (service-role/pipeline only, same pattern as `pipeline_runs` today). `model_version_canary_assignments` → `SELECT` for `anon, authenticated` (so the dashboard can honestly show "this location is on a canary version" if desired later), same write restriction. `model_switching_automation_state` → `SELECT` for `authenticated` only (operational detail, not needed by anonymous public users) plus `UPDATE` restricted to `coordinator` role only, reusing the existing `is_coordinator()` helper function from Part A of this audit — this is the one table a human can write to, and only a Coordinator, matching §16 of your brief exactly.

---

## T. API changes

Kept minimal and read-heavy, per your instruction not to leak sensitive internals through public endpoints:

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v1/models/active` | GET | public | Current active version's id, `algorithm_type`, `activated_at`, and its most recent `model_version_evaluations` summary — this is the public "why do we trust today's forecast" answer, already implied by the existing Pipeline Health page's transparency goal |
| `/api/v1/models/versions` | GET | public | List of versions with `status`, `created_at`, `activated_at`/`deactivated_at` — no raw `metrics`/`config_hash` internals, just lifecycle facts |
| `/api/v1/models/versions/{id}/evaluations` | GET | public | The `model_version_evaluations` rows for one version — the stratified evidence, already designed to be publicly readable per §S |
| `/api/v1/models/decisions` | GET | public | Paginated `model_version_decisions` feed — the audit trail, publicly queryable exactly as `AAGAM_PRD.md`'s weight-map transparency principle already establishes for other operational data |
| `/api/v1/models/automation/status` | GET | `forecaster+` | Current `model_switching_automation_state` row (frozen?, cooldown?, current candidate's state) — operational detail, not public |
| `/api/v1/models/automation/freeze` | POST | `coordinator` | Sets `frozen=true` with a mandatory `reason` field (reuses the exact `LENGTH(reason) >= 10` pattern already enforced on `weight_overrides.reason`) — **new** capability, direct answer to §16 "freeze automatic promotion" |
| `/api/v1/models/automation/unfreeze` | POST | `coordinator` | Clears `frozen` |
| `/api/v1/models/automation/force-last-known-good` | POST | `coordinator` | Immediately sets `status='active'` on whatever version is currently each other version's most recent surviving `active`/`rolled_back`-target ancestor (i.e., walks `parent_version_id` from the current active version back to the nearest version that was never itself rolled back) — writes a `model_version_decisions` row with `decision='ROLLED_BACK'`, `triggered_by='manual_coordinator_action'` |
| `/api/v1/models/candidates/{id}/disable` | POST | `coordinator` | Sets a candidate straight to `rejected` regardless of its current evaluation state — direct answer to §16 "disable a candidate" |
| `/api/v1/models/{id}/activate` | POST | — | **Left exactly as-is: hard-disabled, always 403, for every role.** Per Part A of this audit, this endpoint already exists and is intentionally neutered; this design does not re-enable direct arbitrary activation even for Coordinators — the *only* human lever over which version is active is the freeze/force-last-known-good/disable-candidate trio above, which act on the automated state machine rather than bypassing it outright. This is a deliberate choice: it keeps "how did we get to this active version" always answerable via §R's audit trail, even when a human intervened, rather than reopening a path where a version could become active with no `model_version_decisions` row explaining why. |

Every manual action above writes a `model_version_decisions` row (`decision='FROZEN'`/`'COOLDOWN'`-adjacent/`'ROLLED_BACK'` as appropriate) with `triggered_by` set to the Coordinator's `user_id`, satisfying "any manual intervention must be authenticated, authorized, audited, reversible" from §16 directly — reversible because `unfreeze`/re-enabling a disabled candidate are both available, and nothing here deletes a row.

---

## U. Pipeline integration — exact ordering

Directly answering §25's question with a concrete choice and reasoning:

```
ingest (existing)
  ↓
verify previous forecasts (existing verify-daily.yml — unchanged, still writes skill_scores)
  ↓
evaluate rollback triggers for the CURRENTLY ACTIVE version (§O) — reads skill_scores just written above
  ↓                                                                 [if rollback fires: revert is_active,
  ↓                                                                  write decision row, SKIP remaining
  ↓                                                                  steps this cycle, alert generation
  ↓                                                                  continues against the reinstated version]
evaluate the in-flight candidate's current state-machine step (§N) — only if one exists in
  candidate/evaluating/eligible/shadow/canary; a no-op most cycles
  ↓
select active version for this cycle's blend (existing behavior: whichever version now has is_active=true,
  possibly just-changed by either step above)
  ↓
generate current blend (existing ingest-blend logic, unchanged) — PLUS, if a candidate is in shadow or
  canary, an additional blend pass using the candidate's artifacts, written to model_version_evaluations'
  backing data (shadow) or blended_forecasts for the 5 canary locations only (canary), never displacing
  the active version's output for the other 35 locations
  ↓
alerts (existing, unchanged — always generated from whichever forecast is actually being displayed
  per location, i.e. respects canary assignment)
```

**Why rollback-evaluation comes before candidate-evaluation, and both come before blend generation:** a rollback decision can change which version is `active` for *this very cycle's* blend, so it must resolve first; the candidate's own state-machine step never affects which version is `active` in the same cycle it advances (per §N, `canary → active` only happens after the full 14-day window, never synchronously with a single cycle's evaluation) so its ordering relative to blend generation is not safety-critical, but placing it before blend generation keeps the causal story simple: **every version-related decision for a cycle happens before that cycle's forecast is produced**, never after — this is also what keeps §18 (data leakage) structurally impossible: no evaluation step ever has access to the blend it's about to help decide.

**Weekly-cadence steps** (`evaluating → eligible`, `eligible → shadow` confirmation) run inside `train-weekly.yml`, immediately after the existing retrain + `register_version()` call, reusing the same transaction pattern already in `registry.py` rather than a new scheduled job.

**This new work is explicitly excluded from `pipeline_runs`' existing `job='ingest-blend'`/`job='verify-daily'` success/failure accounting** — it writes its own `pipeline_run_id`-linked rows to the new tables (§S), and a failure in candidate-evaluation or rollback-evaluation logic is caught and logged separately, **never** allowed to mark the underlying ingest/verify cycle itself as failed. This is a direct, explicit safeguard for Milestone M4 (`docs/PHASE_9_REPORT.md`): the 14-day/56-cycle soak gate must not be put at risk by a bug in this new, additive feature.

---

## V. Security / RBAC implications

- No new role is introduced; every new write path checks the existing `is_coordinator()`/`is_forecaster_or_coordinator()` helpers (Part A of this audit already found and validated these) — this design explicitly does **not** create anything resembling the old `admin` role.
- All automatic transitions (§N, §O) execute via the service-role DB connection the pipeline already uses (`DATABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`, already GitHub-secret-scoped per `train-weekly.yml`/`ingest-blend.yml`) — **never** through the public API, so RLS's `anon`/`authenticated` policies are irrelevant to whether automation *can* act (exactly like today's `register_version()` auto-activation, which already works this way) — RLS only governs what humans and the frontend can read or (for Coordinators) manually trigger.
- The four new manual-action endpoints in §T are the **only** new attack surface, and each requires `require_role("coordinator")` plus a mandatory, length-checked `reason` field, plus an audit row — directly satisfying "any manual intervention must be authenticated, authorized, audited, reversible."
- **This design assumes Part A's three CRITICAL authentication findings (AUTH-001, AUTH-002, RBAC-001) are fixed first.** Until the hardcoded demo-token bypass and the client-controlled-role signup path are closed, `require_role("coordinator")` on the new freeze/force/disable endpoints is not a meaningful boundary — those endpoints must not be built or deployed ahead of Part A's Phase 1 fixes. This is stated explicitly rather than left implicit, because this feature adds *more* Coordinator-privileged actions, which directly increases the blast radius of the still-open AUTH-001/002/RBAC-001 findings if built first.
- Explicit safety-rule confirmation (§26 of your brief, checked one by one against this design): never activates with insufficient data (§I is a hard gate in §N), never deletes last-known-good (§P), never switches repeatedly in short intervals (§K.3 dwell time + §O cooldown/circuit-breaker), never uses future data (§D's stored window bounds + §U's ordering make this structurally checkable), never promotes on one metric alone (§H is multi-metric by construction), never promotes on one station alone (§I's ≥50%-locations floor), never promotes because of a transient API failure (§O's coverage/error triggers are about *rollback*, not promotion — a candidate simply can't accumulate qualifying samples during an outage, so it stalls rather than wrongly promotes), never treats missing observations as poor performance (§I's exclusion rules), never treats `high_uncertainty` as normal error (§O's triggers are keyed to MAE/RMSE/bias/CSI on rain/heat/wind hazards specifically, not the separate `high_uncertainty` hazard type, which remains a spread-based signal untouched by this design), never promotes with incomplete coverage (§I), never bypasses RLS (§V above), never bypasses audit logging (§R/§S — every transition writes a row, unconditionally), never modifies user roles (nothing in this design touches `profiles` at all).

---

## W. Performance / cost analysis
Covered in-line above ("Computational cost," between §I and §S). Summary: no new heavy computation is introduced — this design is a read-and-decide layer over data `verify-daily.yml`/`ingest-blend.yml` already produce, materialized into small, append-only tables, evaluated for at most two versions (active + one candidate) per cycle, with weekly-cadence steps kept at weekly cadence rather than pulled into the 6-hourly loop unnecessarily.


---

## X. Pseudocode — end-to-end algorithm

```
# ============================================================
# Runs every 6-hourly cycle, inside ingest-blend, AFTER verify-daily's
# skill_scores write for this cycle, BEFORE blend generation (§U).
# ============================================================
function six_hourly_version_step(pipeline_run_id):
    automation = read model_switching_automation_state  # singleton row

    # ---- 1. ROLLBACK CHECK (active version) ----
    active = get_version(status='active')
    for trigger in ROLLBACK_TRIGGERS:                      # §O table
        window_data = load_skill_scores(
            version=active, window=trigger.window, min_samples=trigger.min_samples)
        if window_data.sample_count < trigger.min_samples:
            continue                                        # not enough evidence either way — skip, don't fire
        if trigger.condition_met(window_data, baseline=active.shadow_canary_baseline):
            parent = get_version(id=active.parent_version_id)
            assert parent is not null                        # §P: active version always has a real parent
                                                               #     once past the very first bootstrap version
            execute_rollback(from_version=active, to_version=parent, trigger=trigger,
                              pipeline_run_id=pipeline_run_id)
            automation.rollback_count_14d += 1
            automation.cooldown_until = now() + 7 days
            if automation.rollback_count_14d >= 2 within trailing 14 days:
                automation.frozen = true
                automation.frozen_reason = "circuit breaker: 2 rollbacks within 14 days"
                write_decision(decision='FROZEN', reason=automation.frozen_reason,
                               pipeline_run_id=pipeline_run_id)
            save(automation)
            active = parent                                  # blend generation below uses the reinstated version
            break                                             # only one trigger needs to fire; don't double-rollback

    # ---- 2. ROLLBACK CHECK (canary version, if any) ----
    canary = get_version(status='canary')
    if canary is not null:
        for trigger in ROLLBACK_TRIGGERS:
            window_data = load_skill_scores(version=canary, window=trigger.window,
                                             min_samples=trigger.canary_min_samples)   # relaxed floor, §M
            if window_data.sample_count < trigger.canary_min_samples:
                continue
            if trigger.condition_met(window_data, baseline=canary.shadow_baseline):
                revert_canary_to_incumbent(canary, active)     # 5 locations revert
                set_status(canary, 'rejected')
                write_decision(decision='ROLLED_BACK', candidate=canary, previous=active,
                                triggered_by=trigger.name, pipeline_run_id=pipeline_run_id)
                canary = null
                break

    # ---- 3. CANDIDATE STATE-MACHINE ADVANCE (at most one candidate in flight, §E) ----
    if not automation.frozen and now() >= automation.cooldown_until:
        candidate = get_version(status in ('candidate','evaluating','eligible','shadow'))
        if candidate is not null:
            advance_candidate_state(candidate, active, pipeline_run_id)  # §N transition table, see below

    # ---- 4. BLEND GENERATION (existing logic + shadow/canary passes) ----
    for location in ALL_40_LOCATIONS:
        serving_version = active
        if canary is not null:
            assignment = get_canary_assignment(location, canary)
            if assignment is not null and assignment.released_at is null:
                serving_version = canary
        blend = compute_blend(location, serving_version)       # existing blend logic, unchanged
        write_to_blended_forecasts(location, blend, version=serving_version)

        if candidate is not null and candidate.status in ('shadow',):
            shadow_blend = compute_blend(location, candidate)  # silent, not written to blended_forecasts
            write_to_shadow_scoring_buffer(location, shadow_blend, candidate)

    # ---- 5. ALERTS (existing, unchanged) — reads blended_forecasts as already written above ----
    run_extreme_weather_rules()


function advance_candidate_state(candidate, active, pipeline_run_id):
    match candidate.status:
        case 'candidate':
            set_status(candidate, 'evaluating')

        case 'evaluating':
            recent    = score_window(candidate, active, 'recent')      # §F, §H
            seasonal  = score_window(candidate, active, 'seasonal')
            longterm  = score_window(candidate, active, 'longterm')
            save_evaluation_rows(candidate, [recent, seasonal, longterm], pipeline_run_id)

            if not longterm.floors_met:                                 # §I
                set_status(candidate, 'rejected')
                write_decision(decision='INSUFFICIENT_DATA', candidate=candidate, previous=active,
                                reason=longterm.floor_failure_reason, pipeline_run_id=pipeline_run_id)
                return

            margin = required_margin(longterm)                          # §K.1
            veto = (recent.floors_met and recent.composite < active_ref - margin) or \
                   (seasonal.floors_met and seasonal.composite < active_ref - margin)

            if longterm.composite >= active_longterm_ref + margin and not veto:
                set_status(candidate, 'eligible')
                write_decision(decision='PROMOTED', ... )   # actually: interim "cycle-1 pass" — see note below
            else:
                set_status(candidate, 'rejected')
                write_decision(decision='NO_IMPROVEMENT', candidate=candidate, previous=active,
                                reason=f"longterm composite {longterm.composite} vs required "
                                       f"{active_longterm_ref + margin}", pipeline_run_id=pipeline_run_id)

        case 'eligible':
            # §K.2 — this branch only runs on the NEXT weekly cycle, window has rolled forward
            longterm = score_window(candidate, active, 'longterm')       # re-scored, later data
            save_evaluation_rows(candidate, [longterm], pipeline_run_id)
            margin = required_margin(longterm)
            if longterm.floors_met and longterm.composite >= active_longterm_ref + margin:
                set_status(candidate, 'shadow')
                candidate.shadow_started_at = now()
            else:
                set_status(candidate, 'rejected')
                write_decision(decision='NOT_CONFIRMED', candidate=candidate, previous=active,
                                pipeline_run_id=pipeline_run_id)

        case 'shadow':
            if days_since(candidate.shadow_started_at) < 7:
                return                                                    # still accumulating, no-op
            shadow_eval = score_shadow_buffer(candidate, active)          # §L, concurrent-window comparison
            save_evaluation_rows(candidate, [shadow_eval], pipeline_run_id)
            if not shadow_eval.floors_met:
                set_status(candidate, 'rejected')
                write_decision(decision='INSUFFICIENT_DATA', ...); return
            if shadow_eval.composite >= shadow_eval.active_concurrent_composite + required_margin(shadow_eval):
                set_status(candidate, 'canary')
                assign_canary_locations(candidate, one_per_region())      # §M
                candidate.canary_started_at = now()
            else:
                set_status(candidate, 'rejected')
                write_decision(decision='NO_IMPROVEMENT', ...)

        case 'canary':
            if days_since(candidate.canary_started_at) < 14:
                return
            pooled_eval = score_pooled(shadow_data=candidate, canary_data=candidate)  # §M
            save_evaluation_rows(candidate, [pooled_eval], pipeline_run_id)
            if pooled_eval.floors_met and \
               pooled_eval.composite >= active_longterm_ref + required_margin(pooled_eval):
                promote_to_active(candidate, active, pipeline_run_id)      # flips is_active, stamps
                                                                             # activated_at/deactivated_at,
                                                                             # releases canary assignments
                write_decision(decision='PROMOTED', candidate=candidate, previous=active,
                                pipeline_run_id=pipeline_run_id)
            else:
                revert_canary_to_incumbent(candidate, active)
                set_status(candidate, 'rejected')
                write_decision(decision='NO_IMPROVEMENT' if pooled_eval.floors_met else 'INSUFFICIENT_DATA',
                                candidate=candidate, previous=active, pipeline_run_id=pipeline_run_id)
```
*(Note on the `'evaluating'` branch's interim pass: this is the first of the two §K.2 confirmations, not a final promotion — the `decision` row written there should use a distinct marker, e.g. `PROMOTED` is reserved for the real, final `canary → active` transition only; the interim pass writes no `model_version_decisions` row with `decision='PROMOTED'` — this is flagged here as a naming detail for whoever implements §S/§T, not left ambiguous.)*

```
# ============================================================
# Runs once, weekly, inside train-weekly.yml, immediately after
# the existing register_version() call registers a fresh 'candidate' row.
# ============================================================
function weekly_version_step():
    if automation.frozen:
        write_decision(decision='FROZEN', reason=automation.frozen_reason); return
    # the 6-hourly loop's advance_candidate_state() already drives 'evaluating'/'eligible' transitions;
    # nothing additional is needed here beyond what register_version() already does today (§A) — the
    # NEW candidate row it creates simply enters the state machine at 'candidate' and is picked up by
    # the very next 6-hourly cycle's step 3 above.
```

---

## Y. Test strategy

**Unit tests** (new, alongside the existing `tests/test_phase*.py` pattern):
- `test_model_switching_margin.py` — §K.1's `required_margin()` against hand-computed pooled-std-error examples, including the exact `0.812 vs 0.814` scenario from your brief, asserting **no promotion**.
- `test_model_switching_floors.py` — every §I floor individually: exactly-at-floor (passes), one-below-floor (fails), confirms excluded-row categories (`pending`/`unverifiable`/`degraded`) are never counted toward any floor.
- `test_model_switching_state_machine.py` — every transition in §N's table, both directions (fires / doesn't fire) for every condition, using synthetic `model_version_evaluations` fixtures — no live DB required.
- `test_model_switching_rollback_triggers.py` — each §O trigger individually, plus the explicit negative cases from your brief (single bad day, one missed event, under-floor stratum) asserting **no rollback**.
- `test_model_switching_hysteresis.py` — simulates a candidate passing cycle 1 and failing cycle 2 (asserts `rejected`, not `active`), and a candidate failing shadow after passing eligibility (asserts `rejected`).
- `test_model_switching_cooldown.py` — asserts no promotion can complete during an active cooldown window, and that a second rollback within 14 days sets `frozen=true`.
- `test_model_switching_audit.py` — asserts every state transition produces exactly one `model_version_decisions` row with every required field populated (no nulls in `reason`, `sample_counts`, etc.).

**Data-leakage regression test:** `test_model_switching_temporal_safety.py` — asserts, for every `model_version_evaluations` row ever written in a test run, that `window_end` is strictly before the `pipeline_run_id`'s own `started_at`, and that a candidate's `training_window_end`/`validation_window_end` never overlaps its own evaluation windows — mirrors the existing `max(train_date) < min(val_date) < min(test_date)` assertion already planned in `AAGAM_PRD.md §7.4`, extended to this feature.

**Integration test (against a disposable test DB, not production):** a scripted 90-simulated-day run seeding synthetic `skill_scores` for two versions (one genuinely better, one genuinely worse, one statistically indistinguishable) and asserting the state machine reaches the expected end state for each — this is the "another engineer can implement it without making architectural assumptions" check on the design itself, run once the implementation exists.

**Manual acceptance tests** (for whoever eventually implements this, listed here so Part-B-equivalent implementation work has concrete exit criteria): trigger a `workflow_dispatch` candidate manually against a seeded scenario; confirm freeze/unfreeze via the Coordinator API actually halts/resumes progression; confirm `force-last-known-good` correctly walks `parent_version_id` past a rolled-back version rather than landing on it.

**Explicitly out of scope for this design's own test strategy** (flagged, not silently ignored): load-testing the added per-cycle computation, and live-email/notification behavior if version changes are ever surfaced to subscribers — neither is part of this feature as designed.

---
**End of design.** The separate Anti-Gravity Implementation Specification for this feature is in `AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md`. Per your explicit instruction, **nothing in either document has been implemented, migrated, committed, or branched** — this is design output for your review before any of it goes to Anti-Gravity.
