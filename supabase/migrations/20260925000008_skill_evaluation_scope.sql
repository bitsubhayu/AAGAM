-- Migration 20260925000008: Add evaluation_scope and contingency counts to skill_scores
-- Supports dynamic live verification window and separate held-out 90-day benchmark (PRD §12, FR-VER-1, FR-VER-2)

ALTER TABLE skill_scores 
ADD COLUMN IF NOT EXISTS evaluation_scope TEXT NOT NULL DEFAULT 'live';

ALTER TABLE skill_scores
ADD COLUMN IF NOT EXISTS hits INT,
ADD COLUMN IF NOT EXISTS false_alarms INT,
ADD COLUMN IF NOT EXISTS misses INT,
ADD COLUMN IF NOT EXISTS correct_negatives INT;

CREATE INDEX IF NOT EXISTS skill_scores_scope_lookup_idx 
ON skill_scores (evaluation_scope, variable, is_weekly, computed_at DESC);
