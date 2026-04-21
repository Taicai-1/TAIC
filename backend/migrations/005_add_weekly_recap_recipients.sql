-- ============================================================================
-- Migration 005 - Add weekly_recap_recipients to agents
-- ============================================================================
--
-- Adds a column to store additional email recipients (JSON array) for the
-- weekly recap feature. The agent owner always receives the recap; this field
-- stores extra team members who should also receive it.
--
-- This migration is idempotent: safe to re-run.
-- ============================================================================

BEGIN;

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS weekly_recap_recipients TEXT;

COMMIT;

-- ============================================================================
-- VERIFICATION:
--   SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_name = 'agents' AND column_name = 'weekly_recap_recipients';
-- ============================================================================
