-- ==============================================================================
-- AAGAM — Phase 5 Live Pipeline, Database, Storage & Scheduler Migration
-- ==============================================================================
-- Migration: 20260921000003_phase5_schema_and_rls.sql
-- Tables: model_versions, blended_forecasts, weights, skill_scores, alerts,
--         profiles, weight_overrides, chat_audit
-- Constraints: PRD §11 & Tech Stack §6.3
-- ==============================================================================

-- 1. Model Versions Table (FR-OPS-1, FR-OPS-2)
CREATE TABLE IF NOT EXISTS model_versions (
    id           SERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    storage_path TEXT NOT NULL,                     -- models/{yyyymmdd}/
    metrics      JSONB NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Partial index: strictly only one model version can be active at any time
CREATE UNIQUE INDEX IF NOT EXISTS one_active_version 
ON model_versions (is_active) 
WHERE is_active = true;

CREATE INDEX IF NOT EXISTS model_versions_created_idx ON model_versions (created_at DESC);


-- 2. Blended Forecasts Table (Latest issue per location/variable/valid_date)
CREATE TABLE IF NOT EXISTS blended_forecasts (
    location_id           INT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    variable              TEXT NOT NULL CHECK (variable IN ('rain_mm', 'tmax_c', 'wind_max_kmh')),
    valid_date            DATE NOT NULL,
    issue_time            TIMESTAMPTZ NOT NULL,
    lead_days             SMALLINT NOT NULL,
    blended               REAL,
    ridge                 REAL,
    lgbm                  REAL,
    equal_mean            REAL,
    spread                REAL,
    models_over_threshold SMALLINT,
    degraded              BOOLEAN NOT NULL DEFAULT FALSE,
    version_id            INT REFERENCES model_versions(id) ON DELETE SET NULL,
    PRIMARY KEY (location_id, variable, valid_date, issue_time)
);

CREATE INDEX IF NOT EXISTS blended_latest_idx ON blended_forecasts (variable, issue_time DESC);
CREATE INDEX IF NOT EXISTS blended_valid_date_idx ON blended_forecasts (valid_date);
CREATE INDEX IF NOT EXISTS blended_location_idx ON blended_forecasts (location_id, valid_date);


-- 3. Weights Table (Hierarchical weights per model version)
CREATE TABLE IF NOT EXISTS weights (
    version_id     INT NOT NULL REFERENCES model_versions(id) ON DELETE CASCADE,
    variable       TEXT NOT NULL CHECK (variable IN ('rain_mm', 'tmax_c', 'wind_max_kmh')),
    region         TEXT NOT NULL,
    season         TEXT NOT NULL CHECK (season IN ('winter', 'premonsoon', 'pre_monsoon', 'monsoon', 'postmonsoon', 'post_monsoon', 'all')),
    lead_days      SMALLINT NOT NULL,
    model          TEXT NOT NULL,
    weight         REAL NOT NULL CHECK (weight >= 0 AND weight <= 1),
    method         TEXT NOT NULL,                     -- 'ridge' | 'inv_mae'
    n_samples      INT NOT NULL,
    fallback_level TEXT NOT NULL,                     -- 'full_bucket' | 'drop_regime' | 'global'
    PRIMARY KEY (version_id, variable, region, season, lead_days, model, method)
);

ALTER TABLE weights DROP CONSTRAINT IF EXISTS weights_season_check;
ALTER TABLE weights ADD CONSTRAINT weights_season_check 
    CHECK (season IN ('winter', 'premonsoon', 'pre_monsoon', 'monsoon', 'postmonsoon', 'post_monsoon', 'all'));

CREATE INDEX IF NOT EXISTS weights_lookup_idx ON weights (version_id, variable, region, season, lead_days);


-- 4. Skill Scores Table (Verification metrics per window and threshold)
CREATE TABLE IF NOT EXISTS skill_scores (
    computed_at   TIMESTAMPTZ NOT NULL,
    window_days   INT NOT NULL,
    variable      TEXT NOT NULL,
    region        TEXT NOT NULL,
    season        TEXT NOT NULL,
    lead_days     SMALLINT NOT NULL,
    model         TEXT NOT NULL,                      -- 'gfs' | 'ecmwf_ifs' | 'icon' | 'aifs' | 'equal_mean' | 'ridge' | 'lgbm' | 'blend'
    mae           REAL,
    rmse          REAL,
    bias          REAL,
    n             INT,
    pod           REAL,
    far           REAL,
    csi           REAL,
    threshold_mm  REAL NOT NULL DEFAULT 0,            -- 0 = continuous metric
    is_weekly     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (computed_at, window_days, variable, region, season, lead_days, model, threshold_mm, is_weekly)
);

CREATE INDEX IF NOT EXISTS skill_scores_lookup_idx ON skill_scores (variable, is_weekly, computed_at DESC);


-- 5. Alerts Table (Extreme weather hazard guidance alerts)
CREATE TABLE IF NOT EXISTS alerts (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    issue_time       TIMESTAMPTZ NOT NULL,
    location_id      INT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    hazard           TEXT NOT NULL CHECK (hazard IN ('heavy_rain', 'heatwave', 'high_wind', 'high_uncertainty')),
    severity         TEXT NOT NULL CHECK (severity IN ('advisory', 'watch', 'alert')),
    valid_date       DATE NOT NULL,
    lead_days        SMALLINT NOT NULL,
    value            REAL,
    models_over      SMALLINT,
    spread           REAL,
    rule             JSONB NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'acknowledged')),
    acknowledged_by  UUID,
    acknowledged_at  TIMESTAMPTZ,
    CONSTRAINT unique_alert_occurrence UNIQUE (issue_time, location_id, hazard, valid_date, lead_days)
);

CREATE INDEX IF NOT EXISTS alerts_query_idx ON alerts (status, hazard, valid_date);
CREATE INDEX IF NOT EXISTS alerts_location_idx ON alerts (location_id, issue_time DESC);


-- 6. Profiles Table (User roles & access control)
CREATE TABLE IF NOT EXISTS profiles (
    user_id      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'forecaster', 'admin')),
    display_name TEXT,
    org          TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- 7. Weight Overrides Table (Forecaster/Admin manual interventions)
CREATE TABLE IF NOT EXISTS weight_overrides (
    id         BIGSERIAL PRIMARY KEY,
    created_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    variable   TEXT NOT NULL CHECK (variable IN ('rain_mm', 'tmax_c', 'wind_max_kmh')),
    region     TEXT NOT NULL,
    season     TEXT NOT NULL,
    lead_days  SMALLINT NOT NULL,
    weights    JSONB NOT NULL,
    reason     TEXT NOT NULL CHECK (LENGTH(reason) >= 10),
    expires_at TIMESTAMPTZ,
    active     BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS weight_overrides_active_idx ON weight_overrides (active, variable, region, season, lead_days);


-- 8. Chat Audit Table (Assistant query audit and telemetry per PRD §11)
CREATE TABLE IF NOT EXISTS chat_audit (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    question   TEXT,
    mode       TEXT,
    tools      JSONB,
    model      TEXT,
    tokens_in  INT,
    tokens_out INT,
    latency_ms INT,
    cached     BOOLEAN,
    flagged    BOOLEAN,
    feedback   SMALLINT
);

CREATE INDEX IF NOT EXISTS chat_audit_user_idx ON chat_audit (user_id, created_at DESC);


-- ==============================================================================
-- Security Definer Role Helper Functions
-- Avoids infinite recursion when evaluating RLS policies against profiles
-- ==============================================================================

CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM profiles 
        WHERE user_id = auth.uid() AND role = 'admin'
    );
$$;

CREATE OR REPLACE FUNCTION public.is_forecaster_or_admin()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM profiles 
        WHERE user_id = auth.uid() AND role IN ('forecaster', 'admin')
    );
$$;


-- Auto-create profile trigger on auth.users insert
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (user_id, role, display_name)
    VALUES (NEW.id, 'viewer', COALESCE(NEW.raw_user_meta_data->>'display_name', NEW.email))
    ON CONFLICT (user_id) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();


-- ==============================================================================
-- Row Level Security (RLS) Configuration
-- ==============================================================================

ALTER TABLE model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE blended_forecasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE weights ENABLE ROW LEVEL SECURITY;
ALTER TABLE skill_scores ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE weight_overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_audit ENABLE ROW LEVEL SECURITY;

-- Read policies for public/authenticated/service_role
DO $$
BEGIN
    -- model_versions
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'model_versions' AND policyname = 'allow_read_model_versions') THEN
        CREATE POLICY allow_read_model_versions ON model_versions FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    -- blended_forecasts
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'blended_forecasts' AND policyname = 'allow_read_blended_forecasts') THEN
        CREATE POLICY allow_read_blended_forecasts ON blended_forecasts FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    -- weights
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'weights' AND policyname = 'allow_read_weights') THEN
        CREATE POLICY allow_read_weights ON weights FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    -- skill_scores
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'skill_scores' AND policyname = 'allow_read_skill_scores') THEN
        CREATE POLICY allow_read_skill_scores ON skill_scores FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    -- alerts
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'alerts' AND policyname = 'allow_read_alerts') THEN
        CREATE POLICY allow_read_alerts ON alerts FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    -- profiles
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'profiles' AND policyname = 'allow_read_profiles') THEN
        CREATE POLICY allow_read_profiles ON profiles FOR SELECT TO authenticated, service_role 
        USING (user_id = auth.uid() OR public.is_admin());
    END IF;

    -- weight_overrides
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'weight_overrides' AND policyname = 'allow_read_weight_overrides') THEN
        CREATE POLICY allow_read_weight_overrides ON weight_overrides FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    -- chat_audit
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'chat_audit' AND policyname = 'allow_read_chat_audit') THEN
        CREATE POLICY allow_read_chat_audit ON chat_audit FOR SELECT TO authenticated, service_role 
        USING (user_id = auth.uid() OR public.is_admin());
    END IF;

    -- Write policies for weight_overrides
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'weight_overrides' AND policyname = 'allow_insert_weight_overrides') THEN
        CREATE POLICY allow_insert_weight_overrides ON weight_overrides FOR INSERT TO authenticated
        WITH CHECK (created_by = auth.uid() AND public.is_forecaster_or_admin());
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'weight_overrides' AND policyname = 'allow_update_weight_overrides') THEN
        CREATE POLICY allow_update_weight_overrides ON weight_overrides FOR UPDATE TO authenticated
        USING (public.is_forecaster_or_admin())
        WITH CHECK (public.is_forecaster_or_admin());
    END IF;

    -- Write policies for alerts (acknowledgement)
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'alerts' AND policyname = 'allow_ack_alerts') THEN
        CREATE POLICY allow_ack_alerts ON alerts FOR UPDATE TO authenticated
        USING (public.is_forecaster_or_admin())
        WITH CHECK (public.is_forecaster_or_admin());
    END IF;

    -- Write policies for chat_audit
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'chat_audit' AND policyname = 'allow_insert_chat_audit') THEN
        CREATE POLICY allow_insert_chat_audit ON chat_audit FOR INSERT TO authenticated
        WITH CHECK (user_id = auth.uid());
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'chat_audit' AND policyname = 'allow_update_chat_audit') THEN
        CREATE POLICY allow_update_chat_audit ON chat_audit FOR UPDATE TO authenticated
        USING (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid());
    END IF;

    -- Write policies for profiles
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'profiles' AND policyname = 'allow_insert_profiles') THEN
        CREATE POLICY allow_insert_profiles ON profiles FOR INSERT TO authenticated
        WITH CHECK (user_id = auth.uid());
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'profiles' AND policyname = 'allow_update_profiles') THEN
        CREATE POLICY allow_update_profiles ON profiles FOR UPDATE TO authenticated
        USING (user_id = auth.uid() OR public.is_admin())
        WITH CHECK (user_id = auth.uid() OR public.is_admin());
    END IF;
END $$;
