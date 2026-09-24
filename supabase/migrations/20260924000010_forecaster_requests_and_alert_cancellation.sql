-- ==============================================================================
-- Migration: 20260924000010_forecaster_requests_and_alert_cancellation.sql
-- Description: Forecaster Access Requests Table & Alert Cancellation Architecture
-- Authoritative Specifications: Final RBAC, Forecaster Access & Alert Lifecycle
-- ==============================================================================

-- 1. Create forecaster_access_requests table
CREATE TABLE IF NOT EXISTS forecaster_access_requests (
    id                BIGSERIAL PRIMARY KEY,
    name              TEXT NOT NULL,
    email             TEXT NOT NULL,
    institution       TEXT,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_by       UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    reviewed_at       TIMESTAMPTZ,
    rejection_reason  TEXT
);

CREATE INDEX IF NOT EXISTS idx_forecaster_req_email_status ON forecaster_access_requests (email, status);
CREATE INDEX IF NOT EXISTS idx_forecaster_req_created ON forecaster_access_requests (created_at DESC);

-- Enable RLS on forecaster_access_requests
ALTER TABLE forecaster_access_requests ENABLE ROW LEVEL SECURITY;

-- Read policy: Coordinators can read all requests; users can see their own request by email
DROP POLICY IF EXISTS allow_read_forecaster_requests ON forecaster_access_requests;
CREATE POLICY allow_read_forecaster_requests ON forecaster_access_requests
    FOR SELECT TO anon, authenticated, service_role
    USING (
        public.is_coordinator()
        OR current_user = 'service_role'
        OR email = auth.jwt() ->> 'email'
    );

-- Insert policy: Anyone can submit an access request
DROP POLICY IF EXISTS allow_insert_forecaster_requests ON forecaster_access_requests;
CREATE POLICY allow_insert_forecaster_requests ON forecaster_access_requests
    FOR INSERT TO anon, authenticated, service_role
    WITH CHECK (true);

-- Update policy: Only coordinators can approve/reject requests
DROP POLICY IF EXISTS allow_update_forecaster_requests ON forecaster_access_requests;
CREATE POLICY allow_update_forecaster_requests ON forecaster_access_requests
    FOR UPDATE TO authenticated, service_role
    USING (public.is_coordinator() OR current_user = 'service_role')
    WITH CHECK (public.is_coordinator() OR current_user = 'service_role');

-- 2. Extend alerts table for cancellation
ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_status_check;
ALTER TABLE alerts ADD CONSTRAINT alerts_status_check CHECK (status IN ('active', 'expired', 'acknowledged', 'cancelled'));

ALTER TABLE alerts ADD COLUMN IF NOT EXISTS cancelled_by UUID REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

-- 3. Extend alert_events table for cancellation tracking
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS cancelled_by UUID REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE alert_events ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

-- Ensure update policies on alerts and alert_events allow forecaster or coordinator
DROP POLICY IF EXISTS allow_ack_alerts ON alerts;
CREATE POLICY allow_ack_alerts ON alerts FOR UPDATE TO authenticated
    USING (public.is_forecaster_or_coordinator())
    WITH CHECK (public.is_forecaster_or_coordinator());

DROP POLICY IF EXISTS allow_ack_alert_events ON alert_events;
CREATE POLICY allow_ack_alert_events ON alert_events FOR UPDATE TO authenticated
    USING (public.is_forecaster_or_coordinator())
    WITH CHECK (public.is_forecaster_or_coordinator());
