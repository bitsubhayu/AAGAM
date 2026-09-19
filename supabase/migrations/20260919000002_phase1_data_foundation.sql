-- ==============================================================================
-- AAGAM — Phase 1 Data Foundation Migration
-- ==============================================================================
-- Migration: 20260919000002_phase1_data_foundation.sql
-- Tables: locations, model_forecasts, pipeline_runs
-- Constraints: Validated against PRD §11 & Tech Stack §6.3
-- ==============================================================================

-- 1. Locations Table
CREATE TABLE IF NOT EXISTS locations (
    id        SERIAL PRIMARY KEY,
    slug      TEXT UNIQUE NOT NULL,
    name      TEXT NOT NULL,
    state     TEXT NOT NULL,
    region    TEXT NOT NULL CHECK (region IN ('NW', 'CENTRAL', 'EAST_NE', 'SOUTH', 'HIMALAYAN')),
    terrain   TEXT NOT NULL CHECK (terrain IN ('plains', 'coastal', 'hills')),
    geog      geography(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS locations_geog_idx ON locations USING GIST (geog);
CREATE INDEX IF NOT EXISTS locations_slug_idx ON locations (slug);
CREATE INDEX IF NOT EXISTS locations_region_idx ON locations (region);

-- 2. Model Forecasts Table (Latest run upserted per valid_date)
CREATE TABLE IF NOT EXISTS model_forecasts (
    location_id INT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    model       TEXT NOT NULL CHECK (model IN ('gfs', 'ecmwf_ifs', 'icon', 'aifs')),
    variable    TEXT NOT NULL CHECK (variable IN ('rain_mm', 'tmax_c', 'wind_max_kmh')),
    valid_date  DATE NOT NULL,
    lead_days   SMALLINT NOT NULL,
    issue_time  TIMESTAMPTZ NOT NULL,
    value       REAL,
    PRIMARY KEY (location_id, model, variable, valid_date)
);

CREATE INDEX IF NOT EXISTS model_forecasts_valid_date_idx ON model_forecasts (valid_date);
CREATE INDEX IF NOT EXISTS model_forecasts_lead_idx ON model_forecasts (lead_days);

-- 3. Pipeline Runs Table (Observability per FR-DATA-5)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id            BIGSERIAL PRIMARY KEY,
    job           TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        TEXT NOT NULL,
    rows_written  INT,
    api_calls_est NUMERIC,
    message       TEXT
);

CREATE INDEX IF NOT EXISTS pipeline_runs_job_idx ON pipeline_runs (job, started_at DESC);

-- 4. Enable Row Level Security (RLS)
ALTER TABLE locations ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_forecasts ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;

-- 5. Read Policies
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'locations' AND policyname = 'allow_read_locations'
    ) THEN
        CREATE POLICY allow_read_locations ON locations 
        FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'model_forecasts' AND policyname = 'allow_read_model_forecasts'
    ) THEN
        CREATE POLICY allow_read_model_forecasts ON model_forecasts 
        FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'pipeline_runs' AND policyname = 'allow_read_pipeline_runs'
    ) THEN
        CREATE POLICY allow_read_pipeline_runs ON pipeline_runs 
        FOR SELECT TO anon, authenticated, service_role USING (true);
    END IF;
END $$;
