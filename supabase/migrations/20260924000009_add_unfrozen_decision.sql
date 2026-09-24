-- ==============================================================================
-- AAGAM — Add UNFROZEN to model_version_decisions decision CHECK constraint
-- ==============================================================================
-- Migration: 20260924000009_add_unfrozen_decision.sql
-- Description: Additive schema migration to allow distinct 'UNFROZEN' audit records
--              in model_version_decisions, ensuring freeze and unfreeze actions are
--              semantically distinguishable in the durable audit trail.
-- Authoritative source: AAGAM_MODEL_VERSIONING_DESIGN.md §S, §T, Phase 4 resolution
-- ==============================================================================

ALTER TABLE model_version_decisions 
  DROP CONSTRAINT IF EXISTS model_version_decisions_decision_check;

ALTER TABLE model_version_decisions 
  ADD CONSTRAINT model_version_decisions_decision_check 
  CHECK (decision IN (
    'PROMOTED',
    'ROLLED_BACK',
    'REJECTED',
    'INSUFFICIENT_DATA',
    'NO_IMPROVEMENT',
    'OPERATIONAL_FAILURE',
    'COOLDOWN',
    'FROZEN',
    'UNFROZEN',
    'NOT_CONFIRMED',
    'ELIGIBLE'
  ));
