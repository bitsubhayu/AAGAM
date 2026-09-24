-- ==============================================================================
-- Migration: 20260924000011_normalize_cancelled_and_backfill_events.sql
-- Description: Normalizes cancelled alert rows, backfills alerts.event_id, and adds performance indexes
-- Authoritative Specifications: AAGAM Final Alert System Correction (Tasks 3, 4, 5)
-- ==============================================================================

-- 1. Normalize existing alert rows where lifecycle_state is cancelled but status is active
UPDATE alerts
SET status = 'cancelled'
WHERE status = 'active'
  AND lifecycle_state = 'cancelled';

-- 2. Backfill alerts.event_id for existing rows that were left unattached
UPDATE alerts a
SET event_id = best_e.best_event_id
FROM (
    SELECT a2.id as alert_id, best.id as best_event_id
    FROM alerts a2
    JOIN LATERAL (
        SELECT e.id
        FROM alert_events e
        WHERE e.location_id = a2.location_id
          AND e.hazard = a2.hazard
          AND a2.valid_date >= e.start_date
          AND a2.valid_date <= e.end_date
        ORDER BY
          (e.status = a2.status) DESC,
          ABS(EXTRACT(EPOCH FROM (e.last_updated_at - a2.issue_time))) ASC
        LIMIT 1
    ) best ON true
    WHERE a2.event_id IS NULL
) best_e
WHERE a.id = best_e.alert_id;

-- 3. Helpful operational query performance indexes
CREATE INDEX IF NOT EXISTS idx_alerts_event_id ON alerts(event_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status_lifecycle ON alerts(status, lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_alert_events_status_dates ON alert_events(status, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_alert_events_loc_hazard_peak ON alert_events(location_id, hazard, severity_peak);
