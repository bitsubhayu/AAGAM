-- ==============================================================================
-- AAGAM — Model Version Switching Database Schema & RLS Migration
-- ==============================================================================
-- Migration: 20260924000008_model_version_switching.sql
-- Description: Additive schema extensions to support multi-metric, stratified,
--              gated model version lifecycle management (Phase 1).
-- Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §D, §S, §K.1
--                       AAGAM_MODEL_VERSIONING_ANTIGRAVITY_SPEC.md Phase 1
-- ==============================================================================

-- 1. Extend model_versions with lifecycle fields (Design Doc §D, §S)
ALTER TABLE model_versions
  ADD COLUMN IF NOT EXISTS parent_version_id INT REFERENCES model_versions(id),
  ADD COLUMN IF NOT EXISTS algorithm_type TEXT NOT NULL DEFAULT 'ridge_lgbm_v1',
  ADD COLUMN IF NOT EXISTS evaluation_policy TEXT NOT NULL DEFAULT 'legacy_single_gate',
  ADD COLUMN IF NOT EXISTS config_hash TEXT,
  ADD COLUMN IF NOT EXISTS training_window_start DATE,
  ADD COLUMN IF NOT EXISTS training_window_end DATE,
  ADD COLUMN IF NOT EXISTS validation_window_start DATE,
  ADD COLUMN IF NOT EXISTS validation_window_end DATE,
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('draft','candidate','evaluating','eligible','shadow','canary',
                      'active','superseded','rejected','rolled_back','retired')),
  ADD COLUMN IF NOT EXISTS activated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS shadow_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS canary_started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT 'pipeline:legacy';

-- 2. Backfill existing rows to preserve is_active invariant (Design Doc §S)
UPDATE model_versions
SET status = 'active',
    activated_at = COALESCE(activated_at, created_at)
WHERE is_active = true;

UPDATE model_versions
SET status = 'superseded',
    deactivated_at = COALESCE(deactivated_at, created_at)
WHERE is_active = false;

-- 3. Create model_version_evaluations table (Design Doc §S)
CREATE TABLE IF NOT EXISTS model_version_evaluations (
    id                 BIGSERIAL PRIMARY KEY,
    version_id         INT NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
    pipeline_run_id    BIGINT REFERENCES pipeline_runs(id),
    window_type        TEXT NOT NULL CHECK (window_type IN ('recent','seasonal','longterm')),
    window_start       DATE NOT NULL,
    window_end         DATE NOT NULL,
    composite_score    REAL,
    strata_included    INT NOT NULL,
    strata_excluded    INT NOT NULL,
    regions_covered    INT NOT NULL DEFAULT 0,
    lead_days_covered  INT NOT NULL,
    sample_counts      JSONB NOT NULL,
    metrics_detail     JSONB NOT NULL,
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS mve_version_window_computed_idx 
  ON model_version_evaluations (version_id, window_type, computed_at DESC);

-- 4. Create model_version_decisions table (Design Doc §R, §S)
CREATE TABLE IF NOT EXISTS model_version_decisions (
    id                      BIGSERIAL PRIMARY KEY,
    decision                TEXT NOT NULL CHECK (decision IN (
                              'PROMOTED','ROLLED_BACK','REJECTED','INSUFFICIENT_DATA',
                              'NO_IMPROVEMENT','OPERATIONAL_FAILURE','COOLDOWN','FROZEN',
                              'NOT_CONFIRMED','ELIGIBLE'
                            )),
    previous_version_id     INT REFERENCES model_versions(id),
    candidate_version_id    INT REFERENCES model_versions(id),
    composite_recent_prev   REAL,
    composite_recent_cand   REAL,
    composite_seasonal_prev REAL,
    composite_seasonal_cand REAL,
    composite_longterm_prev REAL,
    composite_longterm_cand REAL,
    sample_counts           JSONB NOT NULL,
    evaluation_window_start DATE,
    evaluation_window_end   DATE,
    reason                  TEXT NOT NULL,
    triggered_by            TEXT,
    pipeline_run_id         BIGINT REFERENCES pipeline_runs(id),
    algorithm_version       TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS mvd_candidate_created_idx 
  ON model_version_decisions (candidate_version_id, created_at DESC);
CREATE INDEX IF NOT EXISTS mvd_decision_created_idx 
  ON model_version_decisions (decision, created_at DESC);

-- 5. Create model_version_canary_assignments table (Design Doc §M, §S)
CREATE TABLE IF NOT EXISTS model_version_canary_assignments (
    location_id   INT NOT NULL REFERENCES locations(id),
    version_id    INT NOT NULL REFERENCES model_versions(id),
    assigned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    released_at   TIMESTAMPTZ,
    PRIMARY KEY (location_id, version_id, assigned_at)
);

CREATE INDEX IF NOT EXISTS mvca_location_active_idx 
  ON model_version_canary_assignments (location_id) 
  WHERE released_at IS NULL;

-- 6. Create model_switching_automation_state table (Design Doc §S)
CREATE TABLE IF NOT EXISTS model_switching_automation_state (
    id                 SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    frozen             BOOLEAN NOT NULL DEFAULT FALSE,
    frozen_reason      TEXT,
    frozen_by          UUID REFERENCES auth.users(id),
    frozen_at          TIMESTAMPTZ,
    cooldown_until     TIMESTAMPTZ,
    rollback_count_14d INT NOT NULL DEFAULT 0,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO model_switching_automation_state (id, frozen, rollback_count_14d)
VALUES (1, false, 0)
ON CONFLICT (id) DO NOTHING;

-- 7. Row Level Security Policies (Design Doc §S)
ALTER TABLE model_version_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_version_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_version_canary_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_switching_automation_state ENABLE ROW LEVEL SECURITY;

-- Public read for evaluations (transparency)
DROP POLICY IF EXISTS mve_select_policy ON model_version_evaluations;
CREATE POLICY mve_select_policy ON model_version_evaluations
  FOR SELECT USING (true);

-- Public read for decisions audit trail (transparency)
DROP POLICY IF EXISTS mvd_select_policy ON model_version_decisions;
CREATE POLICY mvd_select_policy ON model_version_decisions
  FOR SELECT USING (true);

-- Public read for canary assignments
DROP POLICY IF EXISTS mvca_select_policy ON model_version_canary_assignments;
CREATE POLICY mvca_select_policy ON model_version_canary_assignments
  FOR SELECT USING (true);

-- Authenticated read for automation state
DROP POLICY IF EXISTS msas_select_policy ON model_switching_automation_state;
CREATE POLICY msas_select_policy ON model_switching_automation_state
  FOR SELECT TO authenticated USING (true);

-- Coordinator-only write/update for automation state (freeze / unfreeze)
DROP POLICY IF EXISTS msas_update_coordinator_policy ON model_switching_automation_state;
CREATE POLICY msas_update_coordinator_policy ON model_switching_automation_state
  FOR UPDATE TO authenticated USING (public.is_coordinator()) WITH CHECK (public.is_coordinator());
