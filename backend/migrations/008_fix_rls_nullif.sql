-- ============================================================================
-- Fix RLS tenant_isolation policies: handle empty string from current_setting
--
-- PROBLEM:
--   current_setting('app.company_id', true) returns '' (empty string) when
--   the session variable is not set. Casting ''::int raises:
--     "invalid input syntax for type integer"
--   This blocks service_bypass connections (email ingestion) because
--   PostgreSQL evaluates ALL policies even if one already returns true.
--
-- FIX:
--   Wrap in NULLIF(..., '') so empty strings become NULL.
--   NULL::int = NULL, and company_id = NULL => false (fail-closed, safe).
--
-- This migration is idempotent: safe to re-run.
-- ============================================================================

BEGIN;

DROP POLICY IF EXISTS tenant_isolation ON agents;
CREATE POLICY tenant_isolation ON agents
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON agent_shares;
CREATE POLICY tenant_isolation ON agent_shares
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON documents;
CREATE POLICY tenant_isolation ON documents
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON document_chunks;
CREATE POLICY tenant_isolation ON document_chunks
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON agent_actions;
CREATE POLICY tenant_isolation ON agent_actions
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON teams;
CREATE POLICY tenant_isolation ON teams
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON conversations;
CREATE POLICY tenant_isolation ON conversations
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON messages;
CREATE POLICY tenant_isolation ON messages
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON notion_links;
CREATE POLICY tenant_isolation ON notion_links
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

DROP POLICY IF EXISTS tenant_isolation ON weekly_recap_logs;
CREATE POLICY tenant_isolation ON weekly_recap_logs
    USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int)
    WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int);

COMMIT;
