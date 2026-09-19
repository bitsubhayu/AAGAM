-- ==============================================================================
-- AAGAM — Phase 0 Setup & PostGIS Verification Migration
-- ==============================================================================
-- Migration: 20260919000001_phase0_setup.sql
-- Purpose: Enable PostGIS and create the Phase 0 setup verification table
-- ==============================================================================

-- 1. Enable PostGIS extension for geospatial queries and location points
CREATE EXTENSION IF NOT EXISTS postgis;

-- 2. Create minimal setup check table for hello-world database read verification
CREATE TABLE IF NOT EXISTS _aagam_setup_check (
    id SERIAL PRIMARY KEY,
    component TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details JSONB DEFAULT '{}'::jsonb
);

-- Enable Row Level Security
ALTER TABLE _aagam_setup_check ENABLE ROW LEVEL SECURITY;

-- Allow anonymous read access for hello-world verification endpoint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = '_aagam_setup_check' AND policyname = 'allow_anon_read_setup'
    ) THEN
        CREATE POLICY allow_anon_read_setup 
        ON _aagam_setup_check 
        FOR SELECT 
        TO anon, authenticated, service_role 
        USING (true);
    END IF;
END $$;

-- 3. Insert baseline verification record
INSERT INTO _aagam_setup_check (component, status, details)
VALUES (
    'supabase_database',
    'verified',
    '{
        "project": "AAGAM",
        "phase": "Phase 0",
        "postgis_enabled": true,
        "purpose": "PRD Phase 0 Hello-World Database Read Verification",
        "timestamp": "2026-09-19T00:00:00Z"
    }'::jsonb
)
ON CONFLICT (component) DO UPDATE 
SET verified_at = NOW(), status = 'verified';
