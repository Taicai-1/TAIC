-- ============================================================
-- MIGRATION PROD: Mise à jour de la BDD de production
-- À exécuter sur: applydi-db / readme_to_recover
-- Date: 2026-03-25
-- ============================================================
-- 6 tables à créer + colonnes manquantes sur users
-- Tables orphelines ignorées: agent_tool_configs, tool_call_logs
-- ============================================================

BEGIN;

-- ============================================================
-- 1. TABLE: companies
-- ============================================================
CREATE TABLE IF NOT EXISTS companies (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    neo4j_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    invite_code VARCHAR(32) UNIQUE,
    invite_code_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    neo4j_uri TEXT,
    neo4j_user TEXT,
    neo4j_password TEXT,
    notion_api_key TEXT,
    slack_bot_token TEXT,
    slack_signing_secret TEXT,
    slack_team_id VARCHAR(64)
);
CREATE INDEX IF NOT EXISTS ix_companies_id ON companies(id);

-- ============================================================
-- 2. TABLE: company_memberships
-- ============================================================
CREATE TABLE IF NOT EXISTS company_memberships (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    joined_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_user_company UNIQUE (user_id, company_id)
);
CREATE INDEX IF NOT EXISTS ix_company_memberships_id ON company_memberships(id);
CREATE INDEX IF NOT EXISTS ix_company_memberships_user_id ON company_memberships(user_id);
CREATE INDEX IF NOT EXISTS ix_company_memberships_company_id ON company_memberships(company_id);

-- ============================================================
-- 3. TABLE: company_invitations
-- ============================================================
CREATE TABLE IF NOT EXISTS company_invitations (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    email VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    token VARCHAR(128) UNIQUE NOT NULL,
    invited_by_user_id INTEGER NOT NULL REFERENCES users(id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_company_invitations_id ON company_invitations(id);
CREATE INDEX IF NOT EXISTS ix_company_invitations_company_id ON company_invitations(company_id);

-- ============================================================
-- 4. TABLE: agent_shares
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_shares (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    shared_by_user_id INTEGER REFERENCES users(id),
    can_edit BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_agent_share UNIQUE (agent_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_agent_shares_id ON agent_shares(id);
CREATE INDEX IF NOT EXISTS ix_agent_shares_agent_id ON agent_shares(agent_id);
CREATE INDEX IF NOT EXISTS ix_agent_shares_user_id ON agent_shares(user_id);

-- ============================================================
-- 5. TABLE: notion_links
-- ============================================================
CREATE TABLE IF NOT EXISTS notion_links (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    notion_resource_id VARCHAR(64) NOT NULL,
    resource_type VARCHAR(20) NOT NULL,
    label VARCHAR(255),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_notion_links_id ON notion_links(id);

-- ============================================================
-- 6. TABLE: weekly_recap_logs
-- ============================================================
CREATE TABLE IF NOT EXISTS weekly_recap_logs (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    recap_content TEXT,
    sent_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_weekly_recap_logs_id ON weekly_recap_logs(id);

-- ============================================================
-- 7. COLONNES MANQUANTES: users
--    (IF NOT EXISTS safe — ignoré si déjà présent)
-- ============================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id);
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_backup_codes TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_setup_completed_at TIMESTAMP WITHOUT TIME ZONE;

-- Rendre hashed_password nullable (pour les users OAuth)
ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL;

-- ============================================================
-- 8. COLONNES MANQUANTES: documents
--    notion_link_id existe déjà — ajout FK vers notion_links
-- ============================================================
-- La colonne notion_link_id existe mais la table notion_links n'existait pas.
-- Ajouter la contrainte FK maintenant que la table existe:
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'documents_notion_link_id_fkey'
        AND table_name = 'documents'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_notion_link_id_fkey
            FOREIGN KEY (notion_link_id) REFERENCES notion_links(id);
    END IF;
END $$;

-- Index sur documents.notion_link_id
CREATE INDEX IF NOT EXISTS ix_documents_notion_link_id ON documents(notion_link_id);

-- ============================================================
-- 9. INDEX manquants sur tables existantes
-- ============================================================
CREATE INDEX IF NOT EXISTS ix_users_company_id ON users(company_id);
CREATE INDEX IF NOT EXISTS ix_agents_user_id ON agents(user_id);
CREATE INDEX IF NOT EXISTS ix_documents_user_id ON documents(user_id);
CREATE INDEX IF NOT EXISTS ix_documents_agent_id ON documents(agent_id);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations(user_id);

COMMIT;

-- ============================================================
-- VÉRIFICATION (à exécuter après la migration)
-- ============================================================
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema='public' ORDER BY table_name;
--
-- Résultat attendu: 18 tables (12 existantes + 6 nouvelles)
-- (agent_tool_configs et tool_call_logs ne sont PAS migrées
--  car absentes du code — tables orphelines en dev)
-- ============================================================
