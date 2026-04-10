-- ============================================================================
-- Tier 1 Data Sovereignty Migration - Phase 2
-- Enable Row-Level Security (RLS) on all tenant-scoped tables
-- ============================================================================
--
-- PREREQUISITES:
--   1. Migration 001 must have been run (columns + backfill + indexes)
--   2. New Python code must already be deployed (sets app.company_id session var)
--   3. The DB user used by the app must NOT be a superuser (superusers bypass RLS)
--
-- HOW IT WORKS:
--   The FastAPI middleware sets:  SET LOCAL app.company_id = '<id>';
--   at the start of each request.  RLS policies then restrict all SELECTs,
--   INSERTs, UPDATEs, and DELETEs to rows matching that company_id.
--
--   Rows with company_id IS NULL (legacy / pre-org users) are invisible
--   to all tenants — this is intentional (strong isolation).
--
-- This migration is idempotent: safe to re-run.
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: Enable RLS on all tenant-scoped tables
-- ============================================================================

ALTER TABLE agents            ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_shares      ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents         ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks   ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_actions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams             ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages          ENABLE ROW LEVEL SECURITY;
ALTER TABLE notion_links      ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_recap_logs ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- STEP 2: Create tenant isolation policies
--
-- Each policy uses:
--   current_setting('app.company_id', true)::int
--
-- The second arg `true` means "return NULL instead of error if not set".
-- This makes queries return empty results (not errors) if the session var
-- is missing — fail-closed behavior.
-- ============================================================================

-- agents
DROP POLICY IF EXISTS tenant_isolation ON agents;
CREATE POLICY tenant_isolation ON agents
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- agent_shares
DROP POLICY IF EXISTS tenant_isolation ON agent_shares;
CREATE POLICY tenant_isolation ON agent_shares
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- documents
DROP POLICY IF EXISTS tenant_isolation ON documents;
CREATE POLICY tenant_isolation ON documents
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- document_chunks
DROP POLICY IF EXISTS tenant_isolation ON document_chunks;
CREATE POLICY tenant_isolation ON document_chunks
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- agent_actions
DROP POLICY IF EXISTS tenant_isolation ON agent_actions;
CREATE POLICY tenant_isolation ON agent_actions
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- teams
DROP POLICY IF EXISTS tenant_isolation ON teams;
CREATE POLICY tenant_isolation ON teams
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- conversations
DROP POLICY IF EXISTS tenant_isolation ON conversations;
CREATE POLICY tenant_isolation ON conversations
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- messages
DROP POLICY IF EXISTS tenant_isolation ON messages;
CREATE POLICY tenant_isolation ON messages
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- notion_links
DROP POLICY IF EXISTS tenant_isolation ON notion_links;
CREATE POLICY tenant_isolation ON notion_links
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- weekly_recap_logs
DROP POLICY IF EXISTS tenant_isolation ON weekly_recap_logs;
CREATE POLICY tenant_isolation ON weekly_recap_logs
    USING (company_id = current_setting('app.company_id', true)::int)
    WITH CHECK (company_id = current_setting('app.company_id', true)::int);

-- ============================================================================
-- STEP 3: Force RLS even for table owners
--
-- By default, table owners bypass RLS. This ensures the app user
-- (which may own the tables) is also subject to the policies.
-- ============================================================================

ALTER TABLE agents            FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_shares      FORCE ROW LEVEL SECURITY;
ALTER TABLE documents         FORCE ROW LEVEL SECURITY;
ALTER TABLE document_chunks   FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_actions     FORCE ROW LEVEL SECURITY;
ALTER TABLE teams             FORCE ROW LEVEL SECURITY;
ALTER TABLE conversations     FORCE ROW LEVEL SECURITY;
ALTER TABLE messages          FORCE ROW LEVEL SECURITY;
ALTER TABLE notion_links      FORCE ROW LEVEL SECURITY;
ALTER TABLE weekly_recap_logs FORCE ROW LEVEL SECURITY;

COMMIT;

-- ============================================================================
-- VERIFICATION: Check that RLS is enabled
-- ============================================================================
--
--   SELECT tablename, rowsecurity
--   FROM pg_tables
--   WHERE schemaname = 'public'
--     AND tablename IN (
--       'agents', 'agent_shares', 'documents', 'document_chunks',
--       'agent_actions', 'teams', 'conversations', 'messages',
--       'notion_links', 'weekly_recap_logs'
--     );
--
-- All rows should show rowsecurity = true.
--
-- TEST: Verify isolation works:
--   SET LOCAL app.company_id = '1';
--   SELECT COUNT(*) FROM agents;  -- Should only show company 1's agents
--
--   SET LOCAL app.company_id = '2';
--   SELECT COUNT(*) FROM agents;  -- Should only show company 2's agents
--
--   RESET app.company_id;
--   SELECT COUNT(*) FROM agents;  -- Should return 0 (fail-closed)
-- ============================================================================
