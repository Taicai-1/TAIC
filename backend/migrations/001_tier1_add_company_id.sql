-- ============================================================================
-- Tier 1 Data Sovereignty Migration - Phase 1
-- Add company_id tenant isolation column to all tenant-scoped tables
-- ============================================================================
--
-- DEPLOYMENT ORDER:
--   1. Run THIS file (001) in Cloud SQL — safe while old code is deployed
--   2. Deploy the new Python code (propagates company_id on all writes)
--   3. Run 002_tier1_enable_rls.sql — ONLY after new Python is live
--
-- This migration is idempotent: safe to re-run.
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 1: ADD COLUMNS (nullable FK to companies.id)
-- ============================================================================

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

-- ============================================================================
-- STEP 2: ASSIGN ORPHAN USERS TO TAIC COMPANY
--
-- Users without a company_id would lose access after RLS activation.
-- Assign them to the TAIC company (id=3) so their data stays accessible.
-- ============================================================================

UPDATE users SET company_id = 3 WHERE company_id IS NULL;

-- ============================================================================
-- STEP 3: BACKFILL company_id ON ALL TENANT-SCOPED TABLES
--
-- Order matters: parent tables before children.
-- Runs in two passes:
--   Pass A: resolve from parent relationships (user -> agent -> doc, etc.)
--   Pass B: force remaining NULLs to TAIC (catches orphaned rows)
-- ============================================================================

-- --- Pass A: Resolve from relationships ---

-- agents <- users.company_id
UPDATE agents a SET company_id = u.company_id
FROM users u WHERE a.user_id = u.id AND a.company_id IS NULL;

-- documents <- users.company_id
UPDATE documents d SET company_id = u.company_id
FROM users u WHERE d.user_id = u.id AND d.company_id IS NULL;

-- document_chunks <- documents.company_id
UPDATE document_chunks dc SET company_id = d.company_id
FROM documents d WHERE dc.document_id = d.id AND dc.company_id IS NULL;

-- conversations <- users.company_id
UPDATE conversations c SET company_id = u.company_id
FROM users u WHERE c.user_id = u.id AND c.company_id IS NULL;

-- messages <- conversations.company_id
UPDATE messages m SET company_id = c.company_id
FROM conversations c WHERE m.conversation_id = c.id AND m.company_id IS NULL;

-- agent_shares <- agents.company_id
UPDATE agent_shares ash SET company_id = a.company_id
FROM agents a WHERE ash.agent_id = a.id AND ash.company_id IS NULL;

-- notion_links <- agents.company_id
UPDATE notion_links nl SET company_id = a.company_id
FROM agents a WHERE nl.agent_id = a.id AND nl.company_id IS NULL;

-- agent_actions <- users.company_id (fallback to agents)
UPDATE agent_actions aa SET company_id = u.company_id
FROM users u WHERE aa.user_id = u.id AND aa.company_id IS NULL;

UPDATE agent_actions aa SET company_id = a.company_id
FROM agents a WHERE aa.agent_id = a.id AND aa.company_id IS NULL;

-- teams <- users.company_id
UPDATE teams t SET company_id = u.company_id
FROM users u WHERE t.user_id = u.id AND t.company_id IS NULL;

-- weekly_recap_logs <- users.company_id
UPDATE weekly_recap_logs wrl SET company_id = u.company_id
FROM users u WHERE wrl.user_id = u.id AND wrl.company_id IS NULL;

-- --- Pass B: Force remaining NULLs to TAIC (company_id = 3) ---
-- Catches rows that weren't resolved via relationships (orphaned data).

UPDATE agents            SET company_id = 3 WHERE company_id IS NULL;
UPDATE documents         SET company_id = 3 WHERE company_id IS NULL;
UPDATE document_chunks   SET company_id = 3 WHERE company_id IS NULL;
UPDATE conversations     SET company_id = 3 WHERE company_id IS NULL;
UPDATE messages          SET company_id = 3 WHERE company_id IS NULL;
UPDATE agent_shares      SET company_id = 3 WHERE company_id IS NULL;
UPDATE notion_links      SET company_id = 3 WHERE company_id IS NULL;
UPDATE agent_actions     SET company_id = 3 WHERE company_id IS NULL;
UPDATE teams             SET company_id = 3 WHERE company_id IS NULL;
UPDATE weekly_recap_logs SET company_id = 3 WHERE company_id IS NULL;

-- ============================================================================
-- STEP 4: INDEXES on company_id (fast tenant filtering + required for RLS perf)
-- ============================================================================

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
-- VERIFICATION (run after commit — all counts must be 0)
-- ============================================================================
--
--   SELECT 'users'              AS t, COUNT(*) FROM users              WHERE company_id IS NULL
--   UNION ALL SELECT 'agents',            COUNT(*) FROM agents            WHERE company_id IS NULL
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
--   -- Cross-tenant sanity (must be 0):
--   SELECT COUNT(*) FROM agent_shares ash
--   JOIN agents a ON ash.agent_id = a.id
--   WHERE ash.company_id IS DISTINCT FROM a.company_id;
-- ============================================================================
