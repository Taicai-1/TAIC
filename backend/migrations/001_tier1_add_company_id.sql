-- ============================================================================
-- Tier 1 Data Sovereignty Migration - Phase 1
-- Add company_id tenant isolation column to all tenant-scoped tables
-- ============================================================================
--
-- Deployment order:
--   1. Run THIS file (001_tier1_add_company_id.sql) in Cloud SQL
--      -> Safe to run while the old Python code is still deployed.
--         Old code will simply ignore the new column.
--   2. Deploy the new Python code (adds company_id filters + SET LOCAL session var)
--   3. Run 002_tier1_enable_rls.sql in Cloud SQL
--      -> Only after new Python is live, otherwise all queries will fail.
--
-- This migration is idempotent: safe to re-run.
-- Wraps everything in a transaction for atomicity.
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- 1. ADD COLUMNS (nullable FK to companies.id)
-- ----------------------------------------------------------------------------

ALTER TABLE agents            ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE agent_shares      ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE documents         ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE document_chunks   ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE agent_actions     ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE teams             ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE conversations     ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE messages          ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE notion_links      ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE weekly_recap_logs ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);

-- ----------------------------------------------------------------------------
-- 2. BACKFILL
--    Order matters: parent tables must be populated before children.
--    Legacy rows where the chain reaches a NULL users.company_id stay NULL
--    (invisible after RLS, matches the "strong isolation" decision).
-- ----------------------------------------------------------------------------

-- 2a. agents <- users.company_id
UPDATE agents a
SET company_id = u.company_id
FROM users u
WHERE a.user_id = u.id
  AND a.company_id IS NULL;

-- 2b. documents <- users.company_id
UPDATE documents d
SET company_id = u.company_id
FROM users u
WHERE d.user_id = u.id
  AND d.company_id IS NULL;

-- 2c. document_chunks <- documents.company_id (depends on 2b)
UPDATE document_chunks dc
SET company_id = d.company_id
FROM documents d
WHERE dc.document_id = d.id
  AND dc.company_id IS NULL;

-- 2d. conversations <- users.company_id
UPDATE conversations c
SET company_id = u.company_id
FROM users u
WHERE c.user_id = u.id
  AND c.company_id IS NULL;

-- 2e. messages <- conversations.company_id (depends on 2d)
UPDATE messages m
SET company_id = c.company_id
FROM conversations c
WHERE m.conversation_id = c.id
  AND m.company_id IS NULL;

-- 2f. agent_shares <- agents.company_id (depends on 2a)
--     The agent's tenant is the source of truth; the receiving user must
--     already belong to the same org (enforced in share_agent endpoint).
UPDATE agent_shares ash
SET company_id = a.company_id
FROM agents a
WHERE ash.agent_id = a.id
  AND ash.company_id IS NULL;

-- 2g. notion_links <- agents.company_id (depends on 2a)
UPDATE notion_links nl
SET company_id = a.company_id
FROM agents a
WHERE nl.agent_id = a.id
  AND nl.company_id IS NULL;

-- 2h. agent_actions <- users.company_id (fallback to agents if user is NULL)
UPDATE agent_actions aa
SET company_id = u.company_id
FROM users u
WHERE aa.user_id = u.id
  AND aa.company_id IS NULL;

UPDATE agent_actions aa
SET company_id = a.company_id
FROM agents a
WHERE aa.agent_id = a.id
  AND aa.company_id IS NULL;

-- 2i. teams <- users.company_id
UPDATE teams t
SET company_id = u.company_id
FROM users u
WHERE t.user_id = u.id
  AND t.company_id IS NULL;

-- 2j. weekly_recap_logs <- users.company_id
UPDATE weekly_recap_logs wrl
SET company_id = u.company_id
FROM users u
WHERE wrl.user_id = u.id
  AND wrl.company_id IS NULL;

-- ----------------------------------------------------------------------------
-- 3. INDEXES on company_id (fast tenant filtering + required for RLS perf)
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_agents_company_id            ON agents(company_id);
CREATE INDEX IF NOT EXISTS idx_agent_shares_company_id      ON agent_shares(company_id);
CREATE INDEX IF NOT EXISTS idx_documents_company_id         ON documents(company_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_company_id   ON document_chunks(company_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_company_id     ON agent_actions(company_id);
CREATE INDEX IF NOT EXISTS idx_teams_company_id             ON teams(company_id);
CREATE INDEX IF NOT EXISTS idx_conversations_company_id     ON conversations(company_id);
CREATE INDEX IF NOT EXISTS idx_messages_company_id          ON messages(company_id);
CREATE INDEX IF NOT EXISTS idx_notion_links_company_id      ON notion_links(company_id);
CREATE INDEX IF NOT EXISTS idx_weekly_recap_logs_company_id ON weekly_recap_logs(company_id);

COMMIT;

-- ============================================================================
-- VERIFICATION QUERIES (run these after commit to check backfill state)
-- ============================================================================
--
-- Legacy NULL rows (users with no company_id):
--   SELECT COUNT(*) FROM users WHERE company_id IS NULL;
--
-- Rows NOT backfilled (should equal rows owned by users with NULL company_id):
--   SELECT 'agents'            AS t, COUNT(*) FROM agents            WHERE company_id IS NULL
--   UNION ALL SELECT 'agent_shares',      COUNT(*) FROM agent_shares      WHERE company_id IS NULL
--   UNION ALL SELECT 'documents',         COUNT(*) FROM documents         WHERE company_id IS NULL
--   UNION ALL SELECT 'document_chunks',   COUNT(*) FROM document_chunks   WHERE company_id IS NULL
--   UNION ALL SELECT 'agent_actions',     COUNT(*) FROM agent_actions     WHERE company_id IS NULL
--   UNION ALL SELECT 'teams',             COUNT(*) FROM teams             WHERE company_id IS NULL
--   UNION ALL SELECT 'conversations',     COUNT(*) FROM conversations     WHERE company_id IS NULL
--   UNION ALL SELECT 'messages',          COUNT(*) FROM messages          WHERE company_id IS NULL
--   UNION ALL SELECT 'notion_links',      COUNT(*) FROM notion_links      WHERE company_id IS NULL
--   UNION ALL SELECT 'weekly_recap_logs', COUNT(*) FROM weekly_recap_logs WHERE company_id IS NULL;
--
-- Cross-tenant sanity check (should be 0 - agent and its shares must match):
--   SELECT COUNT(*) FROM agent_shares ash
--   JOIN agents a ON ash.agent_id = a.id
--   WHERE ash.company_id IS DISTINCT FROM a.company_id;
--
-- ============================================================================
