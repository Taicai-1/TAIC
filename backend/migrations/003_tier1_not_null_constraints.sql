-- ============================================================================
-- Tier 1 Data Sovereignty Migration - Phase 3 (optional)
-- Enforce NOT NULL on company_id columns
-- ============================================================================
--
-- PREREQUISITES:
--   1. Migration 001 fully run (0 NULL company_id rows anywhere)
--   2. Migration 002 run (RLS active)
--   3. New Python code deployed (all new rows get company_id automatically)
--
-- This makes it impossible to insert a row without company_id, even if the
-- application code has a bug. Belt-and-suspenders with RLS.
--
-- This migration is idempotent: safe to re-run.
-- ============================================================================

BEGIN;

ALTER TABLE users              ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE agents             ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE documents          ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE document_chunks    ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE conversations      ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE messages           ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE teams              ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE agent_shares       ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE notion_links       ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE agent_actions      ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE weekly_recap_logs  ALTER COLUMN company_id SET NOT NULL;

COMMIT;

-- ============================================================================
-- VERIFICATION:
--   SELECT table_name, column_name, is_nullable
--   FROM information_schema.columns
--   WHERE column_name = 'company_id'
--     AND table_schema = 'public'
--   ORDER BY table_name;
--
-- All rows should show is_nullable = 'NO'.
-- ============================================================================
