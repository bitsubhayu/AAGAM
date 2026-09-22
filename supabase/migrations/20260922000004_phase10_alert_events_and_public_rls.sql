-- ==============================================================================
-- Migration: 20260922000004_phase10_alert_events_and_public_rls.sql
-- Description: Phase 10 — Alert Events, Lifecycle Columns & Public RLS Read Access
-- Authoritative Specifications: AAGAM_PRD.md §11, AAGAM_TECH_STACK.md §6
-- ==============================================================================

-- 1. Create alert_events table
CREATE TABLE IF NOT EXISTS alert_events (
    id                BIGSERIAL PRIMARY KEY,
    location_id       INT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    hazard            TEXT NOT NULL CHECK (hazard IN ('heavy_rain', 'heatwave', 'high_wind', 'high_uncertainty', 'heavy_rain_3day')),
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'expired', 'cancelled')),
    severity_peak     TEXT NOT NULL CHECK (severity_peak IN ('advisory', 'watch', 'alert')),
    value_peak        REAL,
    start_date        DATE NOT NULL,
    end_date          DATE NOT NULL,
    first_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome           TEXT NOT NULL DEFAULT 'pending' CHECK (outcome IN ('hit', 'false_alarm', 'pending', 'unverifiable')),
    verified_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS alert_events_loc_hazard_idx ON alert_events (location_id, hazard, status);
CREATE INDEX IF NOT EXISTS idx_alert_events_loc_hazard_status ON alert_events (location_id, hazard, status);
CREATE INDEX IF NOT EXISTS alert_events_dates_idx ON alert_events (start_date, end_date);

-- 2. Extend alerts table with lifecycle and event tracking
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS event_id BIGINT REFERENCES alert_events(id) ON DELETE SET NULL;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS lifecycle_state TEXT CHECK (lifecycle_state IN ('new', 'upgraded', 'downgraded', 'unchanged', 'cancelled'));
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS previous_severity TEXT CHECK (previous_severity IN ('advisory', 'watch', 'alert'));
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS rarity_label TEXT;

-- Update hazard check constraint on alerts to support heavy_rain_3day
ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_hazard_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_hazard_check CHECK (hazard IN ('heavy_rain', 'heatwave', 'high_wind', 'high_uncertainty', 'heavy_rain_3day'));

CREATE INDEX IF NOT EXISTS alerts_event_id_idx ON alerts (event_id);
CREATE INDEX IF NOT EXISTS alerts_valid_date_idx ON alerts (valid_date);

-- 3. Row Level Security (RLS) Configuration for Phase 10
ALTER TABLE alert_events ENABLE ROW LEVEL SECURITY;

-- Configure public read access (anon, authenticated, service_role) on all core operational data
DROP POLICY IF EXISTS allow_read_locations ON locations;
CREATE POLICY allow_read_locations ON locations FOR SELECT TO anon, authenticated, service_role USING (true);

DROP POLICY IF EXISTS allow_read_blended_forecasts ON blended_forecasts;
CREATE POLICY allow_read_blended_forecasts ON blended_forecasts FOR SELECT TO anon, authenticated, service_role USING (true);

DROP POLICY IF EXISTS allow_read_weights ON weights;
CREATE POLICY allow_read_weights ON weights FOR SELECT TO anon, authenticated, service_role USING (true);

DROP POLICY IF EXISTS allow_read_skill_scores ON skill_scores;
CREATE POLICY allow_read_skill_scores ON skill_scores FOR SELECT TO anon, authenticated, service_role USING (true);

DROP POLICY IF EXISTS allow_read_alerts ON alerts;
CREATE POLICY allow_read_alerts ON alerts FOR SELECT TO anon, authenticated, service_role USING (true);

DROP POLICY IF EXISTS allow_read_alert_events ON alert_events;
CREATE POLICY allow_read_alert_events ON alert_events FOR SELECT TO anon, authenticated, service_role USING (true);

DROP POLICY IF EXISTS allow_read_weight_overrides ON weight_overrides;
CREATE POLICY allow_read_weight_overrides ON weight_overrides FOR SELECT TO anon, authenticated, service_role USING (true);

-- Protected Writes for alert_events (acknowledgement by forecaster/admin)
DROP POLICY IF EXISTS allow_ack_alert_events ON alert_events;
CREATE POLICY allow_ack_alert_events ON alert_events FOR UPDATE TO authenticated
    USING (public.is_forecaster_or_admin())
    WITH CHECK (public.is_forecaster_or_admin());
