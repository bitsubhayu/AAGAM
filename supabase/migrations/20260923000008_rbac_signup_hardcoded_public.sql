-- ==============================================================================
-- Migration: 20260923000008_rbac_signup_hardcoded_public.sql
-- Description: RBAC-001 fix — handle_new_user() trigger must NEVER trust
--              raw_user_meta_data->>'role' for role assignment.
--              New users always get role = 'public'.
--              Only the promote_to_coordinator workflow can assign elevated roles.
-- ==============================================================================

-- Replace the signup trigger function with a hardcoded 'public' role
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    -- RBAC-001 fix: role is ALWAYS 'public' for new signups.
    -- Elevated roles (forecaster, coordinator) are assigned ONLY through
    -- the verified forecaster onboarding flow or the coordinator promotion endpoint.
    -- raw_user_meta_data->>'role' is NEVER trusted for role assignment.
    INSERT INTO public.profiles (user_id, role, display_name, org)
    VALUES (
        NEW.id,
        'public',
        COALESCE(NEW.raw_user_meta_data->>'display_name', NEW.email),
        NEW.raw_user_meta_data->>'org'
    )
    ON CONFLICT (user_id) DO UPDATE
    SET updated_at = NOW();
    RETURN NEW;
END;
$$;
