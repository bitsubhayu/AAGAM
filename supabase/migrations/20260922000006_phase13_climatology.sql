-- ==============================================================================
-- Migration: 20260922000006_phase13_climatology.sql
-- Description: Phase 13 — Climatology Percentiles Table & Public RLS Read Policy
-- Authoritative Specifications: AAGAM_PRD.md §11.2, §11.4, AAGAM_TECH_STACK.md §6
-- ==============================================================================

-- 1. Create climatology_percentiles table matching PRD §11 exact schema
CREATE TABLE IF NOT EXISTS climatology_percentiles (
    location_id INT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
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

-- Fast lookup index for climatology percentile queries by station, variable, metric, and DOY
CREATE INDEX IF NOT EXISTS idx_climatology_percentiles_lookup
    ON climatology_percentiles (location_id, variable, metric, doy_window);

-- 2. Row Level Security (RLS) Configuration for Phase 13 (PRD §11.4)
ALTER TABLE climatology_percentiles ENABLE ROW LEVEL SECURITY;

-- Public read access (anon, authenticated, service_role)
DROP POLICY IF EXISTS allow_read_climatology_percentiles ON climatology_percentiles;
CREATE POLICY allow_read_climatology_percentiles ON climatology_percentiles
    FOR SELECT TO anon, authenticated, service_role USING (true);
