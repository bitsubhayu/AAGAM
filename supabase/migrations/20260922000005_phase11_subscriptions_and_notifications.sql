-- ==============================================================================
-- Migration: 20260922000005_phase11_subscriptions_and_notifications.sql
-- Description: Phase 11 — Subscriptions, notifications_log & RLS
-- Authoritative Specifications: AAGAM_PRD.md §11, AAGAM_TECH_STACK.md §8a, §11
-- ==============================================================================

-- 1. Subscriptions Table
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email            TEXT NOT NULL,
    location_ids     INT[] NOT NULL DEFAULT '{}',
    hazards          TEXT[] NOT NULL DEFAULT '{heavy_rain,heatwave,high_wind,heavy_rain_3day}',
    min_severity     TEXT NOT NULL DEFAULT 'watch' CHECK (min_severity IN ('advisory','watch','alert')),
    daily_summary    BOOLEAN NOT NULL DEFAULT true,
    lifecycle_emails BOOLEAN NOT NULL DEFAULT true,
    active           BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS subscriptions_active_idx ON subscriptions (active);

-- Enable RLS on subscriptions
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

-- Subscriptions policy: strictly own-row access for authenticated users
DROP POLICY IF EXISTS "own subscription" ON subscriptions;
CREATE POLICY "own subscription" ON subscriptions FOR ALL TO authenticated
    USING (user_id = auth.uid())
    WITH CHECK (user_id = auth.uid());

-- Allow service_role full access to subscriptions
DROP POLICY IF EXISTS "service_role full access subscriptions" ON subscriptions;
CREATE POLICY "service_role full access subscriptions" ON subscriptions FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

-- 2. Notifications Log Table
CREATE TABLE IF NOT EXISTS notifications_log (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind                TEXT NOT NULL CHECK (kind IN ('otp','daily_summary','lifecycle')),
    event_id            BIGINT REFERENCES alert_events(id) ON DELETE SET NULL,
    lifecycle_state     TEXT,
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status              TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent','failed')),
    provider_message_id TEXT,
    dedup_key           TEXT
);

CREATE INDEX IF NOT EXISTS notifications_log_dedup_idx ON notifications_log (dedup_key);
CREATE INDEX IF NOT EXISTS notifications_log_user_kind_idx ON notifications_log (user_id, kind, sent_at);
CREATE INDEX IF NOT EXISTS notifications_log_event_idx ON notifications_log (event_id);

-- Enable RLS on notifications_log (service-role only, clients denied)
ALTER TABLE notifications_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role full access notifications_log" ON notifications_log;
CREATE POLICY "service_role full access notifications_log" ON notifications_log FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);
