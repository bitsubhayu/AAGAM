-- ==============================================================================
-- Migration: 20260923000007_rbac_three_roles_and_coordinator.sql
-- Description: Transition AAGAM to authoritative 3-role model:
--              'public', 'forecaster', 'coordinator'
-- ==============================================================================

-- 1. Drop old constraint first so new role values can be updated
ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_role_check;

-- 2. Migrate existing profile roles safely
UPDATE profiles SET role = 'coordinator' WHERE role = 'admin';
UPDATE profiles SET role = 'public' WHERE role = 'viewer';

-- 3. Add new check constraint and set default
ALTER TABLE profiles ADD CONSTRAINT profiles_role_check CHECK (role IN ('public', 'forecaster', 'coordinator'));
ALTER TABLE profiles ALTER COLUMN role SET DEFAULT 'public';

-- 4. Replace security definer helper functions
CREATE OR REPLACE FUNCTION public.is_coordinator()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM profiles 
        WHERE user_id = auth.uid() AND role = 'coordinator'
    );
$$;

CREATE OR REPLACE FUNCTION public.is_forecaster_or_coordinator()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM profiles 
        WHERE user_id = auth.uid() AND role IN ('forecaster', 'coordinator')
    );
$$;

-- Keep legacy function names mapped to new logic for backwards safety during migration transition
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT public.is_coordinator();
$$;

CREATE OR REPLACE FUNCTION public.is_forecaster_or_admin()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
STABLE
AS $$
    SELECT public.is_forecaster_or_coordinator();
$$;

-- 5. Update trigger on auth.users insert to default to 'public'
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (user_id, role, display_name, org)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'role', 'public'),
        COALESCE(NEW.raw_user_meta_data->>'display_name', NEW.email),
        NEW.raw_user_meta_data->>'org'
    )
    ON CONFLICT (user_id) DO UPDATE
    SET updated_at = NOW();
    RETURN NEW;
END;
$$;

-- 6. Update RLS policies for public meteorological and alert data
-- Allow public (anon + authenticated) to read meteorological data
DO $$
BEGIN
    -- locations
    DROP POLICY IF EXISTS "Public locations read" ON locations;
    CREATE POLICY "Public locations read" ON locations FOR SELECT TO anon, authenticated USING (true);

    -- blended_forecasts
    DROP POLICY IF EXISTS "Public blended forecasts read" ON blended_forecasts;
    CREATE POLICY "Public blended forecasts read" ON blended_forecasts FOR SELECT TO anon, authenticated USING (true);

    -- weights
    DROP POLICY IF EXISTS "Public weights read" ON weights;
    CREATE POLICY "Public weights read" ON weights FOR SELECT TO anon, authenticated USING (true);

    -- skill_scores
    DROP POLICY IF EXISTS "Public skill scores read" ON skill_scores;
    CREATE POLICY "Public skill scores read" ON skill_scores FOR SELECT TO anon, authenticated USING (true);

    -- alerts
    DROP POLICY IF EXISTS "Public alerts read" ON alerts;
    CREATE POLICY "Public alerts read" ON alerts FOR SELECT TO anon, authenticated USING (true);

    -- alert_events
    DROP POLICY IF EXISTS "Public alert events read" ON alert_events;
    CREATE POLICY "Public alert events read" ON alert_events FOR SELECT TO anon, authenticated USING (true);

    -- weight_overrides
    DROP POLICY IF EXISTS "Public weight overrides read" ON weight_overrides;
    CREATE POLICY "Public weight overrides read" ON weight_overrides FOR SELECT TO anon, authenticated USING (true);

    DROP POLICY IF EXISTS "Forecasters create weight overrides" ON weight_overrides;
    CREATE POLICY "Forecasters create weight overrides" ON weight_overrides FOR INSERT TO authenticated
    WITH CHECK (public.is_forecaster_or_coordinator());

    DROP POLICY IF EXISTS "Forecasters update weight overrides" ON weight_overrides;
    CREATE POLICY "Forecasters update weight overrides" ON weight_overrides FOR UPDATE TO authenticated
    USING (public.is_forecaster_or_coordinator())
    WITH CHECK (public.is_forecaster_or_coordinator());
END $$;
