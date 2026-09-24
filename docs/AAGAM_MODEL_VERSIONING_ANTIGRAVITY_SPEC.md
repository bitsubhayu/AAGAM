# AAGAM — Automated Model-Version Switching: Anti-Gravity Implementation Specification
**Companion to `AAGAM_MODEL_VERSIONING_DESIGN.md` — read that document first; this file only gives exact file/function/table-level instructions and does not re-derive the reasoning behind them.**

> **NOT FOR IMMEDIATE USE.** Per your explicit instruction, this specification has not been implemented, migrated, committed, or branched. You said you will review the design before this goes to Anti-Gravity — treat this file as ready-to-paste *once you've done that review*, not as something already actioned.
>
> **Hard prerequisite:** Do not implement any phase below until Part A's AUTH-001 (hardcoded demo-token bypass), AUTH-002 (client-metadata role trust), and RBAC-001 (signup-trigger role trust) are fixed and deployed. This feature adds new `coordinator`-gated endpoints (Phase 4 below); building them on top of a currently-bypassable auth layer would extend the blast radius of those still-open findings.

---

## Phase 1 — Schema (additive only, zero behavior change on deploy)

**New migration file:** `supabase/migrations/20260924000008_model_version_switching.sql`

Contents, in order:
1. `ALTER TABLE model_versions ADD COLUMN ...` — exact columns and the one-time backfill `UPDATE`, per Design Doc §D and §S.
2. `CREATE TABLE model_version_evaluations (...)` — exact schema per Design Doc §S.
3. `CREATE TABLE model_version_decisions (...)` — exact schema per Design Doc §S.
4. `CREATE TABLE model_version_canary_assignments (...)` — exact schema per Design Doc §S.
5. `CREATE TABLE model_switching_automation_state (...)` plus the singleton-row `INSERT` — exact schema per Design Doc §S.
6. RLS: `ENABLE ROW LEVEL SECURITY` on all four new tables + the read/write policies exactly as specified in Design Doc §S's "RLS for all four new tables" paragraph, reusing `public.is_coordinator()` (already exists, confirmed working in Part A of this audit — do not redefine it).

**Test:** `tests/test_model_versioning_schema.py` — asserts the migration applies cleanly against a copy of the current schema, asserts the backfill `UPDATE` leaves exactly one `model_versions` row with `status='active'` matching the pre-migration `is_active=true` row, asserts every existing query in `pipeline/models/registry.py` (`get_active_version`, `list_versions`, `rollback_to_version`) still returns correct results unmodified against the post-migration schema.

**Acceptance:** deploy this phase alone to a staging Supabase project; confirm the existing live-blend job, `api/app/routers/models.py`, and `api/app/routers/pipeline.py` all continue to function with zero code changes (they only ever read `is_active`/`metrics`/`storage_path`, all untouched).

---

## Phase 2 — Evaluation engine (library code, not yet wired into any scheduled job)

**New module:** `pipeline/versioning/` (new package)
- `pipeline/versioning/__init__.py`
- `pipeline/versioning/scoring.py` — implements Design Doc §H's `stratum_score`/`composite_score` functions, reading from `skill_scores` (existing table, unchanged). Pure functions: input a DataFrame of `skill_scores` rows + a window spec, output a `WindowEvaluation` dataclass (`composite_score`, `strata_included`, `strata_excluded`, `sample_counts`, `metrics_detail`, `floors_met: bool`, `floor_failure_reason: Optional[str]`).
- `pipeline/versioning/floors.py` — Design Doc §I's floor checks as independently testable functions (`check_min_samples_per_stratum`, `check_min_strata`, `check_min_regions_represented` [all 5 AAGAM regions], `check_min_lead_days`, `check_min_extreme_events`).
- `pipeline/versioning/margin.py` — Design Doc §K.1's `required_margin()` implementing approved Formulation B: `required_margin = BASE_MARGIN * (1 + lambda_sample + lambda_inconsistency)` where `BASE_MARGIN = 0.02` is an absolute composite-score margin, combined with the mandatory regional non-regression guardrail ($\min_r \text{regional\_score}_r \ge -0.01$). Bounded by configuration in `config/model_switching.yaml`.
- `pipeline/versioning/config.py` — loader for `config/model_switching.yaml` (new config file, see Phase 3) — all weights (`w_mae`, `w_rmse`, `w_bias`, `w_csi`), `BASE_MARGIN`, `target_sample_volume`, `min_total_sample_floor`, `regional_non_regression_limit`, sample floors, window lengths, dwell times, cooldown lengths live here, not hardcoded in `scoring.py`/`floors.py`/`margin.py`.
- `pipeline/versioning/state_machine.py` — Design Doc §N's transition table + §X's `advance_candidate_state()` pseudocode, translated to real code against the Phase 1 schema.
- `pipeline/versioning/rollback.py` — Design Doc §O's trigger table + `execute_rollback()`.
- `pipeline/versioning/decisions.py` — `write_decision(...)` helper, single write path into `model_version_decisions`, used by every other module above (so every transition really does produce exactly one audit row, per the Design Doc §Y test).

**New config file:** `config/model_switching.yaml` — every numeric constant named in Design Doc §H/§I/§K, with the exact justification comments from the design doc reproduced inline as YAML comments (so a future reviewer sees *why* each number was chosen without re-reading this whole spec).

**Tests:** all seven `test_model_switching_*.py` files listed in Design Doc §Y, implemented against this Phase-2 code, using synthetic fixtures — **no live DB, no scheduled job wiring yet.** This phase should be fully mergeable and fully tested in complete isolation from the live pipeline.

**Acceptance:** `pytest tests/test_model_switching_*.py` passes; code coverage on `pipeline/versioning/` ≥ 90%; a reviewer can trace every constant in `config/model_switching.yaml` back to a specific paragraph in the design doc.

---

## Phase 3 — Pipeline wiring (this is where behavior actually changes)

**File:** `pipeline/live/runner.py` (existing 6-hourly ingest-blend orchestrator)
- Add a new step, ordered exactly per Design Doc §U's diagram, between the existing verify-step and the existing blend-generation step: call `pipeline/versioning/rollback.py::evaluate_active_rollback_triggers()`, then (if a canary exists) `evaluate_canary_rollback_triggers()`, then `pipeline/versioning/state_machine.py::advance_candidate_state()`.
- Modify the existing blend-generation loop to consult `model_version_canary_assignments` per location (Design Doc §X step 4) and to write an additional shadow-scoring pass when a candidate is in `shadow` status.
- **Wrap the entire new step in its own try/except that logs to `pipeline_runs` under a distinct `job='model-versioning'` row — never lets an exception here mark the existing `job='ingest-blend'` row as failed** (Design Doc §U's explicit M4-protection requirement). This is the single most safety-critical line of this phase; flag it for extra review.

**File:** `pipeline/live/retrain_runner.py` (existing weekly retrain orchestrator)
- After the existing `model_registry.register_version(...)` call, if the new row's `evaluation_policy='staged_v2'` (i.e., this feature is turned on — see Phase 5's rollout flag), do **not** let `register_version()`'s existing auto-activate-on-pass behavior fire; instead the new candidate enters the Phase-2 state machine at `status='candidate'` and is picked up by the next 6-hourly cycle, per Design Doc §N/§X. This requires a small, explicit change to `registry.py::register_version()`: gate its existing `should_activate = force_activate or gate_passed` auto-activation behind `evaluation_policy != 'staged_v2'`, so the **existing** legacy path is fully preserved for any deployment that hasn't opted into this feature (see Phase 5).

**File:** `pipeline/models/registry.py`
- Fix the incidental dead-code duplicate `return` at lines 148-149 (found during Design Doc research) while this file is being touched anyway.
- Add `parent_version_id` population to `register_version()` (set to whatever version currently has `status='active'` at registration time).

**Tests:** `tests/test_phase5_pipeline.py` (existing file) gets new cases covering the new step's ordering and its failure-isolation from `job='ingest-blend'` accounting. New `tests/test_model_switching_pipeline_integration.py` runs the full `pipeline/live/runner.py` against a seeded staging DB with a synthetic candidate at each state-machine stage and asserts correct advancement, per Design Doc §Y's integration-test description.

**Acceptance:** a full dry-run cycle against staging, with `evaluation_policy='staged_v2'` **not yet set on any real candidate** (i.e., this phase is deployed but dormant — see Phase 5), produces zero behavior change versus today; confirmed by diffing `blended_forecasts`/`alerts` output before/after this phase's deploy for an identical input cycle.

---

## Phase 4 — API endpoints

**New router file:** `api/app/routers/model_versioning.py`, registered in `api/app/main.py` alongside the existing routers.
- Implement the six endpoints from Design Doc §T's table (`/models/active`, `/models/versions`, `/models/versions/{id}/evaluations`, `/models/decisions` — all `require_role("public")`; `/models/automation/status` — `require_role("forecaster+")`; `/models/automation/freeze`, `/models/automation/unfreeze`, `/models/automation/force-last-known-good`, `/models/candidates/{id}/disable` — all `require_role("coordinator")`).
- `freeze` and `force-last-known-good` both require a `reason` field, `Field(..., min_length=10)` — mirror the existing `WeightOverrideRequest` schema's pattern in `core/schemas.py` exactly, don't reinvent it.
- Every one of the four `coordinator`-only endpoints calls `pipeline/versioning/decisions.py::write_decision(...)` before returning, with `triggered_by=current_user.user_id`.
- **Do not touch `api/app/routers/models.py`'s existing `POST /models/{id}/activate`** — per Design Doc §T, it stays hard-disabled exactly as Part A of this audit found it.

**New schemas:** `core/schemas.py` gets `ModelVersionSummary`, `ModelVersionEvaluationItem`, `ModelVersionDecisionItem`, `AutomationStateResponse`, `FreezeRequest`, `ForceLastKnownGoodRequest`, `DisableCandidateRequest` — field names matching Design Doc §S's table schemas directly (no ad-hoc renaming between DB and API layers).

**Tests:** `api/tests/test_model_versioning_api.py` — role-matrix test (public/forecaster/coordinator × all 9 endpoints, asserting exactly the auth matrix in Design Doc §T), plus a test that `force-last-known-good` correctly walks `parent_version_id` past an already-`rolled_back` version (the specific edge case Design Doc §T calls out).

**Acceptance:** contract tests pass; a Coordinator (using a **real, non-demo-token** authenticated session — see the Phase 1 prerequisite above) can freeze automation via the API and the very next 6-hourly cycle's `pipeline/versioning/state_machine.py::advance_candidate_state()` call confirms `automation.frozen` and no-ops.

---

## Phase 5 — Rollout flag and gradual enablement

This feature should **not** flip on for the real, already-active production version the day it merges. Add:
- `config/model_switching.yaml`: top-level `enabled: false` flag, checked at the very top of every function in `pipeline/versioning/state_machine.py` and `pipeline/versioning/rollback.py` — when `false`, these functions are no-ops and the system behaves exactly as it does today (existing `registry.py` single-shot gate, unchanged).
- Once `enabled: true` is deliberately set (a config change, reviewable in a PR, not a code change), the **next** weekly retrain's candidate is the first one to go through the full Design Doc §N state machine instead of the legacy path — the currently-active version is untouched and keeps serving throughout, since nothing in Phase 1-4 ever modifies an existing `active` row except through the normal transition rules.

**Acceptance:** with `enabled: false` (the shipped default), every existing test in `api/tests/`, `tests/`, and this feature's own test files still passes, and a full staging deploy shows byte-identical `model_versions`/`blended_forecasts`/`alerts` behavior to pre-feature code for an identical input cycle. Only after that is confirmed should `enabled: true` be considered, and even then, only after Part A's M4 soak (currently PENDING per `docs/PHASE_9_REPORT.md`) has reached its own 14-day/56-cycle success bar — deliberately not run concurrently with a new, still-unproven feature's first live cycles.

---

## Summary of every new/modified file
```
NEW   supabase/migrations/20260924000008_model_version_switching.sql
NEW   pipeline/versioning/__init__.py
NEW   pipeline/versioning/scoring.py
NEW   pipeline/versioning/floors.py
NEW   pipeline/versioning/margin.py
NEW   pipeline/versioning/config.py
NEW   pipeline/versioning/state_machine.py
NEW   pipeline/versioning/rollback.py
NEW   pipeline/versioning/decisions.py
NEW   config/model_switching.yaml
MOD   pipeline/live/runner.py               (new ordered step, isolated failure handling)
MOD   pipeline/live/retrain_runner.py       (gate legacy auto-activate behind evaluation_policy)
MOD   pipeline/models/registry.py           (parent_version_id population; dead-code cleanup)
NEW   api/app/routers/model_versioning.py
MOD   api/app/main.py                        (register new router)
MOD   core/schemas.py                        (new response/request models)
NEW   tests/test_model_switching_margin.py
NEW   tests/test_model_switching_floors.py
NEW   tests/test_model_switching_state_machine.py
NEW   tests/test_model_switching_rollback_triggers.py
NEW   tests/test_model_switching_hysteresis.py
NEW   tests/test_model_switching_cooldown.py
NEW   tests/test_model_switching_audit.py
NEW   tests/test_model_switching_temporal_safety.py
NEW   tests/test_model_switching_pipeline_integration.py
NEW   tests/test_model_versioning_schema.py
NEW   api/tests/test_model_versioning_api.py
```
No existing file outside the four `MOD` lines above is touched. No existing endpoint's behavior changes. No existing scheduled job's success/failure accounting changes.
